from __future__ import annotations

from kilix_pdf_conversion.capabilities import available_engine_names
from kilix_pdf_conversion.models import EngineName


def test_available_engine_names_maps_shared_docling_runtime() -> None:
    capabilities = {
        "base": {
            "pymupdf": {"available": True},
            "pymupdf4llm": {"available": True},
        },
        "optional": {
            "docling": {"available": True},
            "marker": {"available": False},
        },
        "granite": {"available": True},
    }

    assert available_engine_names(capabilities) == {
        EngineName.PYMUPDF,
        EngineName.GRANITE_HYBRID,
        EngineName.GRANITE_PURE,
    }
    capabilities["granite"]["available"] = False
    assert available_engine_names(capabilities) == {EngineName.PYMUPDF}


def test_page_ocr_is_available_when_either_ocr_engine_is() -> None:
    capabilities = {
        "base": {"pymupdf": {"available": True}, "pymupdf4llm": {"available": True}},
        "optional": {"docling": {"available": False}, "marker": {"available": False}},
        "granite": {"available": False},
        "ocr": {"available": True, "engines": {}},
    }
    assert available_engine_names(capabilities) == {EngineName.PYMUPDF, EngineName.PAGE_OCR}
    capabilities["ocr"]["available"] = False
    assert available_engine_names(capabilities) == {EngineName.PYMUPDF}
    del capabilities["ocr"]
    assert available_engine_names(capabilities) == {EngineName.PYMUPDF}


def test_detected_capabilities_report_each_ocr_engine(tmp_path, monkeypatch) -> None:
    from kilix_pdf_conversion.capabilities import detect_capabilities
    from kilix_pdf_conversion.config import OCRSettings

    monkeypatch.setenv("KILIX_OCR_TESSERACT", str(tmp_path / "no-tesseract"))
    capabilities = detect_capabilities(ocr_settings=OCRSettings(model_directory=tmp_path))
    engines = capabilities["ocr"]["engines"]
    assert set(engines) == {"tesseract", "rapidocr"}
    assert not engines["tesseract"]["available"]
    assert "tesseract-ocr" in engines["tesseract"]["error"]
    assert not engines["rapidocr"]["available"]
    assert capabilities["ocr"]["available"] is False
