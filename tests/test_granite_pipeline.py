"""Actual Docling rendering/assembly with only neural generation substituted."""
from __future__ import annotations

import json

import pymupdf
import pytest

pytest.importorskip("docling")
from docling.models.inference_engines.vlm.base import VlmEngineOutput

from kilix_pdf_conversion.config import GraniteSettings
from kilix_pdf_conversion.engines import granite_engine, granite_runtime
from kilix_pdf_conversion.models import EngineName


@pytest.fixture
def controlled_adapter(tmp_path, monkeypatch):
    pdf = tmp_path / "page.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((50, 80), "Actual backend text.")
    document.save(pdf)
    document.close()
    monkeypatch.setattr(granite_engine, "check_runtime", lambda: {})
    monkeypatch.setattr(granite_engine, "verify_asset", lambda _: (
        tmp_path, {"files": {"model.safetensors": {"sha256": "test-only"}}},
    ))

    def init(self, directory, threads, device):
        self.records = []
        self.model = None
        self.processor = None

    monkeypatch.setattr(granite_runtime.LocalGraniteEngine, "__init__", init)
    return pdf


def prediction(self, inputs, *, truncated=False):
    raw = ("<doctag><text><loc_0><loc_0><loc_500><loc_500>"
           "Visual transcription.</text>" + ("" if truncated else "</doctag>"))
    outputs = []
    for item in inputs:
        assert item.image.width > 500  # real backend render reached the stage
        assert item.prompt == "Convert this page to docling."
        row = {
            "text": raw, "raw_text": raw, "num_tokens": 11,
            "stop_reason": "length" if truncated else "stop_sequence",
            "truncated": truncated, "complete_doctags": not truncated,
            "generation_time": 0.1,
        }
        self.records.append(row)
        outputs.append(VlmEngineOutput(text=raw, stop_reason=row["stop_reason"], metadata=row))
    return outputs


@pytest.mark.parametrize("mode,expected", [
    (EngineName.GRANITE_PURE, "Visual transcription."),
    (EngineName.GRANITE_HYBRID, "Actual backend text."),
])
def test_real_assembly_pure_and_hybrid(controlled_adapter, tmp_path, monkeypatch, mode, expected):
    monkeypatch.setattr(granite_runtime.LocalGraniteEngine, "predict_batch", prediction)
    engine = granite_engine.GraniteEngine(mode, GraniteSettings())
    try:
        output = tmp_path / mode.value
        result = engine.convert(controlled_adapter, output)
        assert result.status == "success", result.error
        assert expected in (output / "document.md").read_text()
        assert (output / "document.json").is_file()
        generation = json.loads((output / "generation.json").read_text())
        assert generation["pages"][0]["num_tokens"] == 11
        assert generation["pages"][0]["raw_text"].endswith("</doctag>")
    finally:
        engine.close()


def test_actual_pipeline_truncation_cannot_publish_success(controlled_adapter, tmp_path, monkeypatch):
    def capped(self, inputs):
        return prediction(self, inputs, truncated=True)
    monkeypatch.setattr(granite_runtime.LocalGraniteEngine, "predict_batch", capped)
    engine = granite_engine.GraniteEngine(EngineName.GRANITE_PURE, GraniteSettings())
    try:
        output = tmp_path / "truncated"
        result = engine.convert(controlled_adapter, output)
        assert result.status == "failed"
        assert result.markdown_path is None
        assert not (output / "document.md").exists()
        row = json.loads((output / "generation.json").read_text())["pages"][0]
        assert row["stop_reason"] == "length"
        assert row["truncated"]
    finally:
        engine.close()
