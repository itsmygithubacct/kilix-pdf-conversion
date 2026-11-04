from __future__ import annotations

import gc
import json
import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from ..config import GraniteSettings
from ..models import EngineName, EngineResult
from .base import ConversionEngine, EngineUnavailable
from .classifier_asset import prepare_classifier_stage
from .granite_support import REPOSITORY, REVISION, check_runtime, verify_asset


def _require_chart_assets() -> None:
    # Verify the classifier on the actual request path, but keep the separate
    # chart decoder and workflow routing gate closed until independently qualified.
    try:
        prepare_classifier_stage()
    except EngineUnavailable as error:
        raise EngineUnavailable(
            f"Chart extraction requires accepted, pinned classifier and chart assets: {error}"
        ) from error
    raise EngineUnavailable(
        "Chart extraction requires accepted, pinned classifier and chart assets: "
        "chart decoder and routing are not qualified"
    )


def _relative_asset_references(markdown: str, assets_dir: Path) -> str:
    """Replace Docling's absolute artifact prefix with a portable local one."""
    resolved = assets_dir.resolve()
    prefixes = (
        f"{resolved.as_posix().rstrip('/')}/",
        f"{resolved.as_uri().rstrip('/')}/",
    )
    for prefix in prefixes:
        markdown = markdown.replace(prefix, "assets/")
    return markdown


class GraniteEngine(ConversionEngine):
    def __init__(self, mode: EngineName, settings: GraniteSettings) -> None:
        if mode not in {EngineName.GRANITE_HYBRID, EngineName.GRANITE_PURE}:
            raise ValueError(f"unsupported Granite mode: {mode}")
        self.name = mode
        self.settings = settings
        self._converter = None
        self._pipeline = None
        self._identity: dict = {}

    @property
    def hybrid(self) -> bool:
        return self.name is EngineName.GRANITE_HYBRID

    def _make_converter(self):
        runtime = check_runtime()
        directory, manifest = verify_asset(self.settings.model_directory)
        if self.settings.chart_extraction:
            _require_chart_assets()
        try:
            from docling.datamodel.accelerator_options import AcceleratorOptions
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import (
                VlmConvertOptions,
            )
            from docling.datamodel.vlm_engine_options import TransformersVlmEngineOptions
            from docling.document_converter import DocumentConverter, PdfFormatOption

            from .granite_runtime import GranitePipelineOptions, granite_pipeline_class
            from .vlm_enrichment import chart_enrichment_pipeline
        except ImportError as error:
            raise EngineUnavailable(
                "Granite-Docling import failed; rebuild the frozen optional runtime"
            ) from error

        vlm_options = VlmConvertOptions.from_preset(
            "granite_docling",
            batch_size=self.settings.page_batch_size,
            force_backend_text=self.hybrid,
        )
        vlm_options.model_spec = vlm_options.model_spec.model_copy(deep=True)
        vlm_options.model_spec.revision = REVISION
        vlm_options.model_spec.max_new_tokens = self.settings.max_new_tokens
        vlm_options.engine_options = TransformersVlmEngineOptions(
            device="cpu", torch_dtype="float32", compile_model=False, use_kv_cache=True,
        )
        pipeline_options = GranitePipelineOptions(
            granite_model_directory=directory,
            accelerator_options=AcceleratorOptions(
                device=self.settings.device,
                num_threads=self.settings.threads,
            ),
            document_timeout=self.settings.document_timeout,
            do_chart_extraction=self.settings.chart_extraction,
            force_backend_text=self.hybrid,
            generate_page_images=True,
            generate_picture_images=True,
            vlm_options=vlm_options,
        )
        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_cls=chart_enrichment_pipeline(granite_pipeline_class()),
                    pipeline_options=pipeline_options,
                )
            }
        )
        converter.initialize_pipeline(InputFormat.PDF)
        self._pipeline = next(iter(converter.initialized_pipelines.values()))
        self._identity = {
            "repository": REPOSITORY, "revision": REVISION,
            "checkpoint_sha256": manifest["files"]["model.safetensors"]["sha256"],
            "model_directory": str(directory), "runtime": runtime,
            "dtype": "float32", "attention": "sdpa", "compiled": False,
            "actual_device": "cpu", "threads": self.settings.threads,
            "use_cache": True, "processor": "slow", "microbatch_size": 1,
        }
        return converter

    @property
    def converter(self):
        if self._converter is None:
            self._converter = self._make_converter()
        return self._converter

    def convert(self, source: Path, output_dir: Path) -> EngineResult:
        try:
            from docling.datamodel.base_models import ConversionStatus
            from docling_core.types.doc.base import ImageRefMode
        except ImportError as error:
            raise EngineUnavailable(
                "Granite-Docling is unavailable; install the granite extra"
            ) from error

        output_dir.mkdir(parents=True, exist_ok=True)
        assets_dir = output_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        markdown_path = output_dir / "document.md"
        part_path = output_dir / ".document.md.part"
        started = time.monotonic()
        generation = []
        hybrid_text = {}
        try:
            converter = self.converter
            runtime_engine = self._pipeline.build_pipe[0].engine
            runtime_engine.records.clear()
            result = converter.convert(source, raises_on_error=False)
            generation = list(runtime_engine.records)
            hybrid_text = getattr(self._pipeline, "hybrid_text", {})
            (output_dir / "generation.json").write_text(
                json.dumps({"model": self._identity, "pages": generation}, indent=2) + "\n",
                encoding="utf-8",
            )
            if self.hybrid:
                (output_dir / "hybrid-text.json").write_text(
                    json.dumps(hybrid_text, indent=2) + "\n", encoding="utf-8",
                )
            if result.status is not ConversionStatus.SUCCESS:
                errors = [str(error) for error in result.errors]
                raise RuntimeError(
                    f"conversion status {result.status.value}; errors={errors}"
                )
            if not generation or any(
                row["truncated"] or not row["complete_doctags"] for row in generation
            ):
                raise RuntimeError("Granite returned incomplete DocTags; see generation.json")
            result.document.save_as_json(output_dir / "document.json")
            result.document.save_as_markdown(
                part_path,
                artifacts_dir=assets_dir,
                image_mode=ImageRefMode.REFERENCED,
                enable_chart_tables=True,
                traverse_pictures=True,
            )
            markdown = part_path.read_text(encoding="utf-8")
            part_path.write_text(
                _relative_asset_references(markdown, assets_dir),
                encoding="utf-8",
                newline="\n",
            )
            part_path.replace(markdown_path)
            elapsed = time.monotonic() - started
            try:
                engine_version = version("docling")
            except PackageNotFoundError:
                engine_version = None
            has_assets = any(assets_dir.iterdir())
            if not has_assets:
                assets_dir.rmdir()
            return EngineResult(
                engine=self.name,
                status="success",
                markdown_path=str(markdown_path),
                assets_path=str(assets_dir) if has_assets else None,
                elapsed_seconds=round(elapsed, 3),
                output_bytes=markdown_path.stat().st_size,
                engine_version=engine_version,
                metadata={
                    "mode": "hybrid" if self.hybrid else "pure-vlm",
                    "device": self.settings.device,
                    "page_batch_size": self.settings.page_batch_size,
                    "chart_extraction": self.settings.chart_extraction,
                    "image_mode": "referenced",
                    "model": self._identity,
                    "generation": generation,
                    "hybrid_text": hybrid_text,
                },
            )
        except EngineUnavailable:
            raise
        except Exception as error:
            part_path.unlink(missing_ok=True)
            elapsed = time.monotonic() - started
            return EngineResult(
                engine=self.name,
                status="failed",
                markdown_path=None,
                assets_path=None,
                elapsed_seconds=round(elapsed, 3),
                output_bytes=0,
                error=f"{type(error).__name__}: {error}",
                metadata={"model": self._identity, "generation": generation,
                          "hybrid_text": hybrid_text},
            )
        finally:
            self._release_unused_memory()

    @staticmethod
    def _release_unused_memory() -> None:
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def close(self) -> None:
        if self._pipeline is not None:
            for stage in self._pipeline.build_pipe:
                if hasattr(stage, "engine"):
                    stage.engine.cleanup()
        self._pipeline = None
        self._converter = None
        self._release_unused_memory()
