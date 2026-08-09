from __future__ import annotations

import gc
import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from ..config import MarkerSettings
from ..models import EngineName, EngineResult
from ..util import atomic_write_text
from .base import ConversionEngine, EngineUnavailable


class MarkerEngine(ConversionEngine):
    name = EngineName.MARKER

    def __init__(self, settings: MarkerSettings) -> None:
        self.settings = settings
        self._converter = None

    @property
    def converter(self):
        if self._converter is None:
            try:
                from marker.converters.pdf import PdfConverter
                from marker.models import create_model_dict
            except ImportError as error:
                raise EngineUnavailable(
                    "Marker is unavailable; install the marker extra"
                ) from error
            model_device = None if self.settings.device == "auto" else self.settings.device
            self._converter = PdfConverter(
                config={"output_format": "markdown", "extract_images": True},
                artifact_dict=create_model_dict(device=model_device),
                processor_list=None,
                renderer=None,
            )
        return self._converter

    def convert(self, source: Path, output_dir: Path) -> EngineResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        assets_dir = output_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        markdown_path = output_dir / "document.md"
        started = time.monotonic()
        try:
            rendered = self.converter(str(source))
            markdown = rendered.markdown
            for image_name, image in rendered.images.items():
                target = assets_dir / image_name
                target.parent.mkdir(parents=True, exist_ok=True)
                if image.mode != "RGB":
                    image = image.convert("RGB")
                image.save(target)
                markdown = markdown.replace(f"]({image_name})", f"](assets/{image_name})")
            atomic_write_text(markdown_path, markdown.strip() + "\n")
            elapsed = time.monotonic() - started
            try:
                engine_version = version("marker-pdf")
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
                    "device": self.settings.device,
                    "image_mode": "referenced",
                },
            )
        except EngineUnavailable:
            raise
        except Exception as error:
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
