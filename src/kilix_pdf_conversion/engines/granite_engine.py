from __future__ import annotations

import gc
import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from ..config import GraniteSettings
from ..models import EngineName, EngineResult
from .base import ConversionEngine, EngineUnavailable


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

    @property
    def hybrid(self) -> bool:
        return self.name is EngineName.GRANITE_HYBRID

    def _make_converter(self):
        try:
            from docling.datamodel.accelerator_options import AcceleratorOptions
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import (
                VlmConvertOptions,
                VlmPipelineOptions,
            )
            from docling.datamodel.settings import settings as docling_settings
            from docling.document_converter import DocumentConverter, PdfFormatOption
            from docling.pipeline.vlm_pipeline import VlmPipeline
        except ImportError as error:
            raise EngineUnavailable(
                "Granite-Docling is unavailable; install the granite extra"
            ) from error

        docling_settings.perf.page_batch_size = self.settings.page_batch_size
        vlm_options = VlmConvertOptions.from_preset(
            "granite_docling",
            batch_size=self.settings.page_batch_size,
            force_backend_text=self.hybrid,
        )
        pipeline_options = VlmPipelineOptions(
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
                    pipeline_cls=VlmPipeline,
                    pipeline_options=pipeline_options,
                )
            }
        )
        converter.initialize_pipeline(InputFormat.PDF)
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
        try:
            result = self.converter.convert(source, raises_on_error=False)
            if result.status is not ConversionStatus.SUCCESS:
                errors = [str(error) for error in result.errors]
                raise RuntimeError(
                    f"conversion status {result.status.value}; errors={errors}"
                )
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
        self._converter = None
        self._release_unused_memory()
