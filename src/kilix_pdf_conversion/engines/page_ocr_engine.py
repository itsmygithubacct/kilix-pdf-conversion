"""Page OCR: render each page and read it with Tesseract or RapidOCR.

The choice is made per page from cheap image measurements (see ocr/policy.py).
The candidate directory holds document.md and ocr-pages.json, which records
every page's engine, the reasons, any fallback and the measurements.
"""
from __future__ import annotations

import math
import time

from ..config import OCRSettings
from ..models import EngineName, EngineResult
from ..util import atomic_write_json, atomic_write_text
from .base import ConversionEngine, EngineUnavailable

MAX_PAGE_PIXELS = 36_000_000


class PageOCREngine(ConversionEngine):
    name = EngineName.PAGE_OCR

    def __init__(self, settings: OCRSettings) -> None:
        self.settings = settings
        self._reader = None

    def _get_reader(self):
        if self._reader is None:
            try:
                from ..ocr.reader import OcrReader
            except ImportError as error:
                raise EngineUnavailable(
                    f"page OCR needs {error.name}; rebuild the frozen runtime"
                ) from error
            self._reader = OcrReader(self.settings)
        return self._reader

    def convert(self, source, output_dir) -> EngineResult:
        reader = self._get_reader()
        available = reader.available()
        if not available:
            details = "; ".join(item["error"] for item in reader.availability().values())
            raise EngineUnavailable(f"no OCR engine is available: {details}")
        if self.settings.engine != "auto" and self.settings.engine not in available:
            raise EngineUnavailable(reader.availability()[self.settings.engine]["error"])

        import pymupdf
        from PIL import Image

        from ..ocr.backends import OcrFailed
        from ..ocr.layout import markdown_escape_line
        from ..ocr.policy import ROUTER_POLICY_VERSION

        output_dir.mkdir(parents=True, exist_ok=True)
        markdown_path = output_dir / "document.md"
        started = time.monotonic()
        pages: list[dict] = []
        parts: list[str] = []
        try:
            document = pymupdf.open(source)
            try:
                for index, page in enumerate(document):
                    width_in = page.rect.width / 72
                    height_in = page.rect.height / 72
                    dpi = self.settings.dpi
                    if width_in * height_in * dpi * dpi > MAX_PAGE_PIXELS:
                        dpi = max(72, int(math.sqrt(MAX_PAGE_PIXELS / (width_in * height_in))))
                    pixmap = page.get_pixmap(dpi=dpi, alpha=False, colorspace=pymupdf.csRGB)
                    image = Image.frombytes("RGB", (pixmap.width, pixmap.height),
                                            pixmap.samples)
                    try:
                        reading = reader.read(image, dpi=dpi)
                    except (OcrFailed, EngineUnavailable) as error:
                        raise OcrFailed(f"page {index + 1}: {error}") from error
                    pages.append({"page": index + 1, "dpi": dpi, **reading.to_dict()})
                    if reading.paragraphs:
                        parts.append(f"<!-- page {index + 1} · {reading.engine} -->")
                        for paragraph in reading.paragraphs:
                            parts.append("\n".join(
                                markdown_escape_line(line) for line in paragraph.splitlines()
                            ))
                    else:
                        parts.append(f"<!-- page {index + 1} · no text found -->")
            finally:
                document.close()
            atomic_write_text(markdown_path, "\n\n".join(parts).strip() + "\n")
            atomic_write_json(output_dir / "ocr-pages.json", {
                "router_policy_version": ROUTER_POLICY_VERSION,
                "engines": reader.availability(),
                "pages": pages,
            })
        except (OcrFailed, OSError, RuntimeError, ValueError) as error:
            return EngineResult(
                engine=self.name,
                status="failed",
                markdown_path=None,
                assets_path=None,
                elapsed_seconds=round(time.monotonic() - started, 3),
                output_bytes=0,
                error=f"{type(error).__name__}: {error}",
                metadata={"pages_read": len(pages)},
            )
        status = reader.availability()
        used = {name: sum(p["engine"] == name for p in pages) for name in status}
        versions = [f"{name} {item['version']}" for name, item in status.items()
                    if item["available"]]
        return EngineResult(
            engine=self.name,
            status="success",
            markdown_path=str(markdown_path),
            assets_path=None,
            elapsed_seconds=round(time.monotonic() - started, 3),
            output_bytes=markdown_path.stat().st_size,
            engine_version=", ".join(versions),
            metadata={
                "mode": self.settings.engine,
                "dpi": self.settings.dpi,
                "language": self.settings.language,
                "router_policy_version": ROUTER_POLICY_VERSION,
                "pages_by_engine": used,
                "fallback_pages": [p["page"] for p in pages if p["fallback"]],
                "models": status.get("rapidocr", {}).get("models"),
                "page_record": "ocr-pages.json",
            },
        )

    def close(self) -> None:
        if self._reader is not None:
            self._reader.close()
            self._reader = None
