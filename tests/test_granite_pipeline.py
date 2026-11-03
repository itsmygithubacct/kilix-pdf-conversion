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
    (EngineName.GRANITE_HYBRID, "Visual transcription."),
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
        if mode is EngineName.GRANITE_HYBRID:
            decision = result.metadata["hybrid_text"]["decisions"][0]
            assert decision["action"] == "retain"
            assert decision["reason"] == "conflicting_text"
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


def test_real_backend_equivalent_wrapping_can_be_used(controlled_adapter, tmp_path, monkeypatch):
    def equivalent(self, inputs):
        outputs = prediction(self, inputs)
        for row, output in zip(self.records, outputs, strict=True):
            text = row["text"].replace("Visual transcription.", "Actual\nbackend text.")
            row.update(text=text, raw_text=text)
            output.text = text
        return outputs

    monkeypatch.setattr(granite_runtime.LocalGraniteEngine, "predict_batch", equivalent)
    engine = granite_engine.GraniteEngine(EngineName.GRANITE_HYBRID, GraniteSettings())
    try:
        result = engine.convert(controlled_adapter, tmp_path / "equivalent")
        assert result.status == "success", result.error
        decision = result.metadata["hybrid_text"]["decisions"][0]
        assert decision["action"] == "replace"
        assert decision["selected_text"] == "Actual backend text."
        assert (tmp_path / "equivalent/hybrid-text.json").exists()
    finally:
        engine.close()


def test_background_ink_cannot_authorize_equivalent_backend_substitution(
    controlled_adapter, tmp_path, monkeypatch,
):
    source = tmp_path / "invisible.pdf"
    model_text = "HARBOR          archive"
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.draw_rect(pymupdf.Rect(94, 54, 96, 59), color=None, fill=(0, 0, 0))
        page.insert_text((40, 60), model_text, fontsize=11, color=(1, 1, 1))
        doc.save(source)

    def equivalent(self, inputs):
        outputs = prediction(self, inputs)
        for row, output in zip(self.records, outputs, strict=True):
            text = row["text"].replace("Visual transcription.", model_text)
            row.update(text=text, raw_text=text)
            output.text = text
        return outputs

    monkeypatch.setattr(granite_runtime.LocalGraniteEngine, "predict_batch", equivalent)
    engine = granite_engine.GraniteEngine(EngineName.GRANITE_HYBRID, GraniteSettings())
    try:
        result = engine.convert(source, tmp_path / "unsupported")
        assert result.status == "success", result.error
        decision = result.metadata["hybrid_text"]["decisions"][0]
        assert " ".join(decision["backend_text"].split()) == " ".join(model_text.split())
        assert decision["action"] == "retain"
        assert decision["reason"] == "source_text_not_trusted"
        assert decision["selected_text"] == decision["model_text"]
    finally:
        engine.close()
