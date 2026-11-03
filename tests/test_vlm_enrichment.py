from __future__ import annotations

from importlib.metadata import PackageNotFoundError

import pytest

from kilix_pdf_conversion.engines.base import EngineUnavailable
from kilix_pdf_conversion.engines.vlm_enrichment import chart_enrichment_pipeline


@pytest.fixture(autouse=True)
def clear_pipeline_cache():
    chart_enrichment_pipeline.cache_clear()
    yield
    chart_enrichment_pipeline.cache_clear()


def test_missing_optional_runtime_has_an_actionable_error(monkeypatch):
    def missing(_name):
        raise PackageNotFoundError("docling-slim")

    monkeypatch.setattr("kilix_pdf_conversion.engines.vlm_enrichment.version", missing)
    with pytest.raises(EngineUnavailable, match=r"docling-slim==2\.118\.0"):
        chart_enrichment_pipeline()


def test_unqualified_runtime_is_refused_before_importing_pipeline(monkeypatch):
    monkeypatch.setattr(
        "kilix_pdf_conversion.engines.vlm_enrichment.version", lambda _name: "2.127.0"
    )
    with pytest.raises(EngineUnavailable, match=r"found 2\.127\.0"):
        chart_enrichment_pipeline()
