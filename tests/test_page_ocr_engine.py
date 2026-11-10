from __future__ import annotations

import json

import pytest

pytest.importorskip("PIL")
pytest.importorskip("numpy")

from kilix_pdf_conversion.config import (  # noqa: E402
    AppConfig,
    OCRSettings,
    ValidationSettings,
    WorkflowSettings,
)
from kilix_pdf_conversion.engines.base import EngineUnavailable  # noqa: E402
from kilix_pdf_conversion.engines.factory import create_engine  # noqa: E402
from kilix_pdf_conversion.engines.page_ocr_engine import PageOCREngine  # noqa: E402
from kilix_pdf_conversion.models import EngineName, Profile  # noqa: E402
from kilix_pdf_conversion.ocr import reader as reader_module  # noqa: E402
from kilix_pdf_conversion.ocr.backends import OcrFailed  # noqa: E402
from kilix_pdf_conversion.ocr.policy import RAPIDOCR, TESSERACT, RouteDecision  # noqa: E402
from kilix_pdf_conversion.ocr.reader import PageReading  # noqa: E402
from kilix_pdf_conversion.workflow import Workflow  # noqa: E402

from .helpers import make_scan_pdf  # noqa: E402
from .test_ocr_policy import CLEAN  # noqa: E402

TEXT = (
    "A deterministic source paragraph for conversion quality testing. "
    "It contains enough words to produce a useful Markdown document. "
) * 8


class FakeReader:
    """Stands in for OcrReader: page one is RapidOCR, page two Tesseract."""

    instances: list[FakeReader] = []

    def __init__(self, settings, *, installed=(TESSERACT, RAPIDOCR), fail_on=None,
                 empty_on=None) -> None:
        self.settings = settings
        self.installed = installed
        self.fail_on = fail_on
        self.empty_on = empty_on
        self.pages = 0
        self.dpis: list[int | None] = []
        self.closed = False
        FakeReader.instances.append(self)

    def availability(self):
        return {
            name: ({"available": True, "version": "1.0"} if name in self.installed
                   else {"available": False, "error": f"{name} is not installed"})
            for name in (TESSERACT, RAPIDOCR)
        }

    def available(self):
        return tuple(self.installed)

    def read(self, image, *, dpi=None, engine=None):
        self.pages += 1
        self.dpis.append(dpi)
        if self.pages == self.fail_on:
            raise OcrFailed("both engines failed")
        engine = RAPIDOCR if self.pages % 2 else TESSERACT
        decision = RouteDecision(engine, ("because",), CLEAN)
        paragraphs = () if self.pages == self.empty_on else (TEXT, "- 1. *starred*")
        return PageReading(paragraphs, engine, decision, "", 0.01)

    def close(self):
        self.closed = True


def two_page_scan(tmp_path):
    import pymupdf

    single = make_scan_pdf(tmp_path / "one.pdf")
    document = pymupdf.open(single)
    document.insert_pdf(pymupdf.open(single))
    path = tmp_path / "scan.pdf"
    document.save(path)
    document.close()
    return path


def engine_with(reader) -> PageOCREngine:
    engine = PageOCREngine(OCRSettings(dpi=150))
    engine._reader = reader
    return engine


def test_factory_builds_the_page_ocr_engine() -> None:
    engine = create_engine(EngineName.PAGE_OCR, AppConfig())
    assert isinstance(engine, PageOCREngine)
    assert engine.name is EngineName.PAGE_OCR


def test_every_page_is_read_and_recorded(tmp_path) -> None:
    reader = FakeReader(OCRSettings(), empty_on=2)
    engine = engine_with(reader)
    result = engine.convert(two_page_scan(tmp_path), tmp_path / "out")
    assert result.status == "success"
    markdown = (tmp_path / "out" / "document.md").read_text()
    assert markdown.startswith("<!-- page 1 · rapidocr -->\n\n")
    assert "\n\\- 1. \\*starred\\*\n" in markdown
    assert "<!-- page 2 · no text found -->" in markdown
    assert reader.dpis == [150, 150]
    record = json.loads((tmp_path / "out" / "ocr-pages.json").read_text())
    assert [page["engine"] for page in record["pages"]] == [RAPIDOCR, TESSERACT]
    assert record["pages"][1]["characters"] == 0
    assert result.metadata["pages_by_engine"] == {TESSERACT: 1, RAPIDOCR: 1}
    assert result.metadata["page_record"] == "ocr-pages.json"
    assert result.engine_version == "tesseract 1.0, rapidocr 1.0"
    engine.close()
    assert reader.closed


def test_a_failed_page_fails_the_candidate(tmp_path) -> None:
    result = engine_with(FakeReader(OCRSettings(), fail_on=2)).convert(
        two_page_scan(tmp_path), tmp_path / "out")
    assert result.status == "failed"
    assert "page 2: both engines failed" in result.error
    assert result.metadata == {"pages_read": 1}


def test_no_installed_engine_is_unavailable(tmp_path) -> None:
    engine = engine_with(FakeReader(OCRSettings(), installed=()))
    with pytest.raises(EngineUnavailable, match="no OCR engine is available"):
        engine.convert(two_page_scan(tmp_path), tmp_path / "out")


def test_a_named_engine_that_is_missing_is_unavailable(tmp_path) -> None:
    engine = PageOCREngine(OCRSettings(engine=TESSERACT))
    engine._reader = FakeReader(engine.settings, installed=(RAPIDOCR,))
    with pytest.raises(EngineUnavailable, match="tesseract is not installed"):
        engine.convert(two_page_scan(tmp_path), tmp_path / "out")


def test_large_pages_are_rendered_at_reduced_dpi(tmp_path) -> None:
    import pymupdf

    path = tmp_path / "poster.pdf"
    document = pymupdf.open()
    document.new_page(width=72 * 40, height=72 * 30)
    document.save(path)
    document.close()
    reader = FakeReader(OCRSettings())
    engine = PageOCREngine(OCRSettings(dpi=300))
    engine._reader = reader
    assert engine.convert(path, tmp_path / "out").status == "success"
    assert reader.dpis[0] < 300
    assert (40 * reader.dpis[0]) * (30 * reader.dpis[0]) <= 36_000_000


def test_scan_pdf_converts_through_page_ocr_without_granite(tmp_path, monkeypatch) -> None:
    FakeReader.instances.clear()
    monkeypatch.setattr(reader_module, "OcrReader", FakeReader)
    source = make_scan_pdf(tmp_path / "scan.pdf")
    config = AppConfig(
        workflow=WorkflowSettings(
            profile=Profile.BALANCED,
            output_root=tmp_path / "runs",
            copy_source=False,
            render_visual_pages=False,
        ),
        validation=ValidationSettings(minimum_markdown_bytes=20),
    )
    with Workflow(config) as workflow:
        result = workflow.convert(source)
    assert result.canonical_engine is EngineName.PAGE_OCR
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    engines = manifest["engine_results"]
    assert engines.get("granite-pure", {"status": "unavailable"})["status"] == "unavailable"
    assert engines["page-ocr"]["status"] == "success"
    assert manifest["quality"]["page-ocr"]["status"] in {"pass", "warn"}
    assert (result.run_dir / "conversions" / "page-ocr" / "ocr-pages.json").is_file()
    assert any(instance.closed for instance in FakeReader.instances)
