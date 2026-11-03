"""Pinned, offline Granite stage composed with Docling's real PDF pipeline.

Imports are intentionally optional: the native launcher needs no torch/Docling.
The upstream page renderer, DocTags assembly and hybrid backend remain in use.
"""
from __future__ import annotations

import hashlib
import time
from functools import cache
from pathlib import Path

import torch
from docling.datamodel.pipeline_options import VlmPipelineOptions
from docling.models.inference_engines.vlm.base import VlmEngineOutput, VlmEngineType
from docling.models.stages.vlm_convert.vlm_convert_model import VlmConvertModel
from docling.pipeline.vlm_pipeline import VlmPipeline
from transformers import (
    AutoModelForImageTextToText,
    AutoProcessor,
    StoppingCriteriaList,
    StopStringCriteria,
)

from .base import EngineUnavailable
from .granite_support import REPOSITORY, REVISION, generation_summary


class GranitePipelineOptions(VlmPipelineOptions):
    granite_model_directory: Path


class LocalGraniteEngine:
    selected_engine_type = VlmEngineType.TRANSFORMERS

    def __init__(self, directory: Path, threads: int, device: str):
        if device not in {"cpu", "auto"}:
            raise EngineUnavailable("The frozen Granite runtime supports CPU; select device=cpu")
        torch.set_num_threads(threads)
        if torch.get_num_interop_threads() != 1:
            torch.set_num_interop_threads(1)
        self.records: list[dict] = []
        self.processor = AutoProcessor.from_pretrained(
            directory, revision=REVISION, local_files_only=True,
            trust_remote_code=False, use_fast=False,
        )
        self.processor.tokenizer.padding_side = "left"
        self.model = AutoModelForImageTextToText.from_pretrained(
            directory, revision=REVISION, local_files_only=True,
            trust_remote_code=False, torch_dtype=torch.float32, attn_implementation="sdpa",
        ).eval()

    def predict_batch(self, input_batch):
        # Sequential microbatches avoid padding ambiguity, per-row stop races
        # and memory spikes. This is explicit even if Docling groups pages.
        outputs = []
        tokenizer = self.processor.tokenizer
        for item in input_batch:
            image = item.image.convert("RGB")
            messages = [{"role": "user", "content": [
                {"type": "image"}, {"type": "text", "text": item.prompt},
            ]}]
            prompt = self.processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True,
            )
            started = time.monotonic()
            inputs = self.processor(text=[prompt], images=[image], return_tensors="pt", padding=True)
            preprocess_seconds = time.monotonic() - started
            input_length = inputs["input_ids"].shape[1]
            remaining = self.model.config.text_config.max_position_embeddings - input_length
            limit = min(item.max_new_tokens, remaining)
            if limit < 1:
                raise RuntimeError("Granite image prompt exhausts the configured context length")
            criteria = StopStringCriteria(tokenizer, item.stop_strings)
            started = time.monotonic()
            with torch.inference_mode():
                output_ids = self.model.generate(
                    **inputs, max_new_tokens=limit, do_sample=False, use_cache=True,
                    stopping_criteria=StoppingCriteriaList([criteria]),
                )
            generation_seconds = time.monotonic() - started
            ids = output_ids[0, input_length:].tolist()
            raw = self.processor.decode(ids, skip_special_tokens=False)
            eos = self.model.generation_config.eos_token_id
            eos_ids = set(eos if isinstance(eos, list) else [eos])
            record = generation_summary(
                ids, raw_text=raw, pad_token=tokenizer.pad_token, eos_ids=eos_ids,
                stop_matched=bool(criteria(output_ids, None).all()), effective_limit=limit,
            )
            record.update({
                "generated_ids": ids, "prompt_tokens": input_length,
                "requested_max_new_tokens": item.max_new_tokens,
                "effective_max_new_tokens": limit,
                "context_limited": limit < item.max_new_tokens,
                "generation_time": generation_seconds,
                "preprocess_seconds": preprocess_seconds,
                "image_size": list(image.size),
                "image_rgb_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
                "pixel_values_sha256": hashlib.sha256(
                    inputs["pixel_values"].contiguous().numpy().tobytes()
                ).hexdigest(),
                "input_shapes": {key: list(value.shape) for key, value in inputs.items()},
                "microbatch_size": 1,
            })
            self.records.append(record)
            outputs.append(VlmEngineOutput(
                text=record["text"], stop_reason=record["stop_reason"], metadata={
                    "num_tokens": record["num_tokens"], "generation_time": generation_seconds,
                },
            ))
        return outputs

    def cleanup(self):
        self.model = None
        self.processor = None


class LocalGraniteStage(VlmConvertModel):
    def __init__(self, options, directory: Path, accelerator):
        self.enabled = True
        self.options = options
        self.repo_id = REPOSITORY
        self.revision = REVISION
        self.engine = LocalGraniteEngine(directory, accelerator.num_threads, accelerator.device)


@cache
def granite_pipeline_class(base=VlmPipeline):
    """Allow the separately maintained enrichment lifecycle to be the base."""
    class LocalGranitePipeline(base):
        def _initialize_new_runtime_system(self, pipeline_options):
            self.force_backend_text = pipeline_options.vlm_options.force_backend_text
            self.keep_images = pipeline_options.generate_page_images
            self.build_pipe = [LocalGraniteStage(
                pipeline_options.vlm_options,
                pipeline_options.granite_model_directory,
                pipeline_options.accelerator_options,
            )]

    return LocalGranitePipeline
