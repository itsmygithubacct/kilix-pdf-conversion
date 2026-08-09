from __future__ import annotations

import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from ..config import PyMuPDFSettings
from ..models import EngineName, EngineResult
from ..util import atomic_write_text, changed_directory
from .base import ConversionEngine, EngineUnavailable


def _normalize_markdown(markdown: str) -> str:
    lines = [line.rstrip() for line in markdown.splitlines()]
    normalized: list[str] = []
    blank_count = 0
    for line in lines:
        if line:
            blank_count = 0
            normalized.append(line)
        else:
            blank_count += 1
            if blank_count <= 2:
                normalized.append("")
    return "\n".join(normalized).strip() + "\n"


class PyMuPDFEngine(ConversionEngine):
    name = EngineName.PYMUPDF

    def __init__(self, settings: PyMuPDFSettings) -> None:
        self.settings = settings

    def convert(self, source: Path, output_dir: Path) -> EngineResult:
        try:
            import pymupdf4llm
        except ImportError as error:
            raise EngineUnavailable(
                "PyMuPDF4LLM is unavailable; install the base project dependencies"
            ) from error

        output_dir.mkdir(parents=True, exist_ok=True)
        assets_dir = output_dir / "assets"
        if self.settings.write_images:
            assets_dir.mkdir(parents=True, exist_ok=True)
        markdown_path = output_dir / "document.md"
        started = time.monotonic()
        try:
            with changed_directory(output_dir):
                markdown = pymupdf4llm.to_markdown(
                    str(source),
                    dpi=self.settings.dpi,
                    filename=source.stem,
                    footer=self.settings.include_footers,
                    header=self.settings.include_headers,
                    image_path="assets",
                    show_progress=False,
                    use_ocr=False,
                    force_text=True,
                    write_images=self.settings.write_images,
                )
            atomic_write_text(markdown_path, _normalize_markdown(markdown))
            elapsed = time.monotonic() - started
            try:
                engine_version = version("pymupdf4llm")
            except PackageNotFoundError:
                engine_version = None
            has_assets = assets_dir.is_dir() and any(assets_dir.iterdir())
            if assets_dir.is_dir() and not has_assets:
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
                    "dpi": self.settings.dpi,
                    "headers": self.settings.include_headers,
                    "footers": self.settings.include_footers,
                    "write_images": self.settings.write_images,
                },
            )
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
