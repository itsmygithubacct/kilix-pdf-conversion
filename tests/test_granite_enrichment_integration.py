"""Combined real adapter lifecycle; all three neural boundaries are substituted."""
from __future__ import annotations

from collections import Counter

import pytest

pytest.importorskip("docling")
from docling.models.inference_engines.vlm.base import VlmEngineOutput
from test_vlm_enrichment_docling import DOCTAGS
from test_vlm_enrichment_docling import fixture_pdf as fixture_pdf
from test_vlm_enrichment_docling import models as models

from kilix_pdf_conversion.config import GraniteSettings
from kilix_pdf_conversion.engines import granite_engine, granite_runtime
from kilix_pdf_conversion.engines.base import EngineUnavailable
from kilix_pdf_conversion.models import EngineName


def configure(monkeypatch, tmp_path, events):
    monkeypatch.setattr(granite_engine, "check_runtime", lambda: {})
    monkeypatch.setattr(granite_engine, "verify_asset", lambda _: (
        tmp_path, {"files": {"model.safetensors": {"sha256": "test-only"}}},
    ))

    def init(self, directory, threads, device):
        events.append(("construct", "page"))
        self.records = []
        self.model = self.processor = None

    def predict(self, inputs):
        outputs = []
        for _ in inputs:
            events.append(("run", "page"))
            row = {"text": DOCTAGS, "raw_text": DOCTAGS, "num_tokens": 50,
                   "stop_reason": "stop_sequence", "truncated": False,
                   "complete_doctags": True, "generation_time": 0.1}
            self.records.append(row)
            outputs.append(VlmEngineOutput(text=DOCTAGS, stop_reason="stop_sequence", metadata=row))
        return outputs

    monkeypatch.setattr(granite_runtime.LocalGraniteEngine, "__init__", init)
    monkeypatch.setattr(granite_runtime.LocalGraniteEngine, "predict_batch", predict)


@pytest.mark.parametrize("enabled", [False, True])
def test_combined_adapter_has_one_page_stage_and_correct_enrichment_lifecycle(
    models, fixture_pdf, tmp_path, monkeypatch, enabled,
):
    events, _, _ = models
    configure(monkeypatch, tmp_path, events)
    # Explicit test substitute for the unavailable accepted chart assets.
    monkeypatch.setattr(granite_engine, "_require_chart_assets", lambda: None)
    engine = granite_engine.GraniteEngine(
        EngineName.GRANITE_PURE, GraniteSettings(chart_extraction=enabled),
    )
    try:
        result = engine.convert(fixture_pdf, tmp_path / "result")
        assert result.status == "success", result.error
        counts = Counter(events)
        assert counts[("construct", "page")] == counts[("run", "page")] == 1
        for stage in ["classifier", "chart"]:
            assert counts[("construct", stage)] == counts[("run", stage)] == int(enabled)
        if enabled:
            assert events.index(("run", "classifier")) < events.index(("run", "chart"))
            assert events.index(("run", "chart")) < events.index(("unload", "backend"))
            assert "widgets" in (tmp_path / "result/document.md").read_text()
    finally:
        engine.close()


def test_combined_adapter_cannot_fetch_unaccepted_chart_assets(models, tmp_path, monkeypatch):
    events, _, _ = models
    configure(monkeypatch, tmp_path, events)
    engine = granite_engine.GraniteEngine(
        EngineName.GRANITE_PURE, GraniteSettings(chart_extraction=True),
    )
    with pytest.raises(EngineUnavailable, match="accepted, pinned"):
        engine._make_converter()
    assert events == []
