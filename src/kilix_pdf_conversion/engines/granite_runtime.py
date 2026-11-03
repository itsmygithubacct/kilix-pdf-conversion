"""Pinned, offline Granite stage composed with Docling's real PDF pipeline.

Imports are intentionally optional: the native launcher needs no torch/Docling.
The upstream page renderer, DocTags assembly and hybrid backend remain in use.
"""
from __future__ import annotations

import hashlib
import math
import time
from functools import cache
from pathlib import Path

import torch
from docling.datamodel.pipeline_options import VlmPipelineOptions
from docling.models.inference_engines.vlm.base import VlmEngineOutput, VlmEngineType
from docling.models.stages.vlm_convert.vlm_convert_model import VlmConvertModel
from docling.pipeline.vlm_pipeline import VlmPipeline
from docling_core.types.doc import BoundingBox, CoordOrigin, TextItem
from transformers import (
    AutoModelForImageTextToText,
    AutoProcessor,
    StoppingCriteriaList,
    StopStringCriteria,
)

from ..text_evidence import TextTrust, choose_hybrid_text, inspect_source_text
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
            self.guarded_backend_text = pipeline_options.vlm_options.force_backend_text
            # Always preserve the model document before making owned, auditable
            # substitution decisions. The upstream path overwrites even with "".
            self.force_backend_text = False
            self.hybrid_text = {}
            self.keep_images = pipeline_options.generate_page_images
            self.build_pipe = [LocalGraniteStage(
                pipeline_options.vlm_options,
                pipeline_options.granite_model_directory,
                pipeline_options.accelerator_options,
            )]

        def _turn_dt_into_doc(self, conv_res):
            document = super()._turn_dt_into_doc(conv_res)
            self.hybrid_text = {}
            if not self.guarded_backend_text:
                return document
            evidence = inspect_source_text(Path(conv_res.input.file))
            pages = {p.page_number: p for p in evidence.pages}
            decisions = []
            for element, _level in document.iterate_items():
                if not isinstance(element, TextItem) or not element.prov:
                    continue
                provenance = element.prov[0]
                number = provenance.page_no
                page = next((p for p in conv_res.pages if p.page_no == number), None)
                parsed_page = document.pages.get(number)
                source_page = pages.get(number)
                trust = source_page.trust if source_page else TextTrust.UNKNOWN
                geometry_valid = bool(page and page.size and parsed_page and source_page)
                crop = None
                if geometry_valid:
                    geometry_valid = all(math.isfinite(value) and value > 0 for value in (
                        page.size.width, page.size.height,
                        parsed_page.size.width, parsed_page.size.height,
                        source_page.width, source_page.height,
                    ))
                if geometry_valid:
                    box = provenance.bbox.to_top_left_origin(page_height=parsed_page.size.height)
                    scale_x = page.size.width / parsed_page.size.width
                    scale_y = page.size.height / parsed_page.size.height
                    crop = BoundingBox(
                        l=box.l * scale_x, t=box.t * scale_y,
                        r=box.r * scale_x, b=box.b * scale_y,
                        coord_origin=CoordOrigin.TOPLEFT,
                    )
                    geometry_valid = (
                        all(math.isfinite(v) for v in crop.as_tuple())
                        and 0 <= crop.l < crop.r <= source_page.width
                        and 0 <= crop.t < crop.b <= source_page.height
                    )
                proposed = self.extract_text_from_backend(page, crop) if geometry_valid else ""
                original = element.text
                decision = choose_hybrid_text(
                    original, proposed, trust, geometry_valid=geometry_valid,
                )
                element.text = decision.text
                # orig and raw generation retain the original model text.
                decisions.append({
                    "item": element.self_ref, "page": number, "source_trust": trust.value,
                    "action": decision.action, "reason": decision.reason,
                    "conflicting_text": decision.conflicting_text,
                    "geometry_valid": geometry_valid,
                    "model_text": original, "backend_text": proposed,
                    "selected_text": decision.text,
                })
            self.hybrid_text = {"source_evidence": evidence.summary(), "decisions": decisions}
            return document

    return LocalGranitePipeline
