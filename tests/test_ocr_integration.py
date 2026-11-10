"""Both real OCR engines on a rendered page.

Runs only when KILIX_OCR_INTEGRATION=1 and both engines are installed: Tesseract
on PATH or at KILIX_OCR_TESSERACT, and the accepted PP-OCRv6 small assets under
KILIX_OCR_MODEL_DIR or KILIX_CONTENT_ROOT/assets.
"""
from __future__ import annotations

import os
import socket

import pytest

if os.environ.get("KILIX_OCR_INTEGRATION") != "1":
    pytest.skip("set KILIX_OCR_INTEGRATION=1 to run the OCR engines", allow_module_level=True)

pytest.importorskip("rapidocr")

from kilix_pdf_conversion.config import OCRSettings  # noqa: E402
from kilix_pdf_conversion.ocr.reader import OcrReader  # noqa: E402

from .test_ocr_features import page  # noqa: E402


@pytest.fixture(scope="module")
def reader():
    instance = OcrReader(OCRSettings(threads=2))
    missing = {name: item["error"] for name, item in instance.availability().items()
               if not item["available"]}
    if missing:
        pytest.fail(f"OCR integration requested but engines are missing: {missing}")
    yield instance
    instance.close()


def _words(text: str) -> set[str]:
    return set(text.lower().split())


@pytest.mark.parametrize("engine", ["tesseract", "rapidocr"])
def test_engine_reads_a_rendered_page(reader, engine) -> None:
    reading = reader.read(page(lines=12, font_size=30), dpi=200, engine=engine)
    assert reading.engine == engine
    expected = {"quick", "brown", "harbour", "yellow", "kites"}
    assert expected <= _words(reading.text)


def test_rapidocr_runs_with_the_network_unreachable(reader, monkeypatch) -> None:
    def refuse(*_args, **_kwargs):
        raise OSError("network disabled for this test")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    reader.backends["rapidocr"].close()
    reading = reader.read(page(lines=10, font_size=30, columns=2), engine="rapidocr")
    assert {"quick", "brown"} <= _words(reading.text)
