from __future__ import annotations

import json
from dataclasses import replace

import pymupdf

from kilix_pdf_conversion.config import AppConfig
from kilix_pdf_conversion.engines.pymupdf_engine import PyMuPDFEngine
from kilix_pdf_conversion.models import EngineName, QualityStatus
from kilix_pdf_conversion.workflow import Workflow


def test_unverified_ocr_retains_native_for_review_without_loading_another_model(tmp_path, monkeypatch):
    lines = [
        "Delivery record for the main store.",
        "Check every label before moving the boxes to the shelf.",
        "The east bay and the west bay both contain twenty four cases.",
        "Keep this record beside the receipt until the delivery is complete.",
        "Repeated values describe separate locations and must be retained.",
    ]
    source = tmp_path / "ocr.pdf"
    with pymupdf.open() as visible:
        page = visible.new_page()
        for index, text in enumerate(lines):
            page.insert_text((45, 60 + index * 30), text, fontsize=11)
        raster = page.get_pixmap().tobytes("png")
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_image(page.rect, stream=raster)
        for index, text in enumerate(lines):
            page.insert_text((45, 60 + index * 30), text, fontsize=11, render_mode=3)
        doc.save(source)
    config = AppConfig()
    config = replace(config, workflow=replace(
        config.workflow, output_root=tmp_path / "output", render_visual_pages=False,
    ))
    called = []

    def native_only(self, name):
        called.append(name)
        assert name is EngineName.PYMUPDF, "uncertainty alone must not load neural OCR"
        return PyMuPDFEngine(config.pymupdf)

    monkeypatch.setattr(Workflow, "_engine", native_only)
    monkeypatch.setattr(Workflow, "_installed_engines", lambda self: frozenset(EngineName))
    with Workflow(config) as workflow:
        result = workflow.convert(source)
    assert called == [EngineName.PYMUPDF]
    assert result.canonical_engine is EngineName.PYMUPDF
    assert result.status is QualityStatus.WARN
    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["content_accuracy"] == "unverified"
    quality = manifest["quality"][EngineName.PYMUPDF.value]
    assert quality["native_token_recall"] is None
    assert not quality["fallback_recommended"]
    assert "not independently verified" in (result.run_dir / "report.md").read_text()
