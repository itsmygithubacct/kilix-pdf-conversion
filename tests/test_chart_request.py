"""Explicit chart requests must never succeed through an unrelated native route."""

from dataclasses import replace

import pytest

from kilix_pdf_conversion.cli import main
from kilix_pdf_conversion.config import AppConfig, GraniteSettings, WorkflowSettings
from kilix_pdf_conversion.engines.base import EngineUnavailable
from kilix_pdf_conversion.models import EngineName, Profile
from kilix_pdf_conversion.workflow import Workflow

from .helpers import make_native_pdf


@pytest.mark.parametrize("engines", [None, (EngineName.PYMUPDF,), (EngineName.GRANITE_PURE,)])
def test_requested_chart_extraction_refuses_before_outputs_or_cache(tmp_path, engines):
    source = make_native_pdf(tmp_path / "source.pdf")
    output = tmp_path / "runs"
    output.mkdir()
    sentinel = output / "existing.txt"
    sentinel.write_text("existing output", encoding="utf-8")
    before = sentinel.stat().st_mtime_ns
    config = AppConfig(
        granite=GraniteSettings(chart_extraction=True),
        workflow=WorkflowSettings(profile=Profile.FAST, output_root=output, force=True),
    )
    with Workflow(config) as workflow:
        with pytest.raises(EngineUnavailable, match="accepted, pinned classifier and chart assets"):
            workflow.convert(source, explicit_engines=engines)
    assert list(output.iterdir()) == [sentinel]
    assert sentinel.read_text(encoding="utf-8") == "existing output"
    assert sentinel.stat().st_mtime_ns == before


def test_asset_gate_alone_cannot_enable_unimplemented_chart_routing(tmp_path, monkeypatch):
    source = make_native_pdf(tmp_path / "source.pdf")
    monkeypatch.setattr(
        "kilix_pdf_conversion.engines.granite_engine._require_chart_assets", lambda: None,
    )
    config = replace(AppConfig(), granite=GraniteSettings(chart_extraction=True))
    with Workflow(config) as workflow:
        with pytest.raises(EngineUnavailable, match="workflow routing is not yet available"):
            workflow.convert(source, explicit_engines=(EngineName.PYMUPDF,))


def test_cli_chart_request_returns_error_without_creating_output(tmp_path, capsys):
    source = make_native_pdf(tmp_path / "source.pdf")
    output = tmp_path / "output"
    result = main([
        "convert", str(source), "--profile", "fast", "--chart-extraction",
        "--output-root", str(output), "--json",
    ])
    assert result == 2
    assert "accepted, pinned classifier and chart assets" in capsys.readouterr().err
    assert not output.exists()


def test_batch_chart_request_fails_each_file(tmp_path, capsys):
    sources = tmp_path / "input"
    sources.mkdir()
    make_native_pdf(sources / "one.pdf")
    make_native_pdf(sources / "two.pdf")
    output = tmp_path / "output"
    result = main([
        "batch", str(sources), "--profile", "fast", "--chart-extraction",
        "--output-root", str(output), "--json",
    ])
    import json

    rows = json.loads(capsys.readouterr().out)
    assert result == 1 and len(rows) == 2
    assert all(row["status"] == "failed" and "accepted, pinned" in row["error"] for row in rows)
    assert not output.exists()
