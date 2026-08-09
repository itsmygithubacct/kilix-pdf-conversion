from __future__ import annotations

from dataclasses import replace

import pytest

from kilix_pdf_conversion.config import AppConfig, ValidationSettings, WorkflowSettings
from kilix_pdf_conversion.models import EngineName, Profile, QualityStatus
from kilix_pdf_conversion.workflow import Workflow

from .helpers import make_native_pdf


class StubEngine:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_fast_workflow_creates_canonical_bundle(tmp_path) -> None:
    source = make_native_pdf(tmp_path / "source.pdf")
    config = AppConfig(
        workflow=WorkflowSettings(
            profile=Profile.FAST,
            output_root=tmp_path / "runs",
            copy_source=True,
            render_visual_pages=False,
        ),
        validation=ValidationSettings(
            minimum_markdown_bytes=20,
            minimum_native_token_recall=0.70,
            maximum_repeated_short_line_count=20,
            fail_on_image_placeholders=True,
        ),
    )
    with Workflow(config) as workflow:
        result = workflow.convert(source)
    assert result.status in {QualityStatus.PASS, QualityStatus.WARN}
    assert result.canonical_engine is EngineName.PYMUPDF
    assert (result.run_dir / "canonical.md").is_file()
    assert (result.run_dir / "manifest.json").is_file()
    assert (result.run_dir / "report.md").is_file()
    assert (result.run_dir / "source.pdf").is_file()


def test_workflow_reuses_complete_manifest(tmp_path) -> None:
    source = make_native_pdf(tmp_path / "source.pdf")
    config = AppConfig(
        workflow=WorkflowSettings(
            profile=Profile.FAST,
            output_root=tmp_path / "runs",
            render_visual_pages=False,
        ),
        validation=ValidationSettings(minimum_markdown_bytes=20),
    )
    with Workflow(config) as workflow:
        first = workflow.convert(source)
        second = workflow.convert(source)
    assert second.run_dir == first.run_dir
    assert second.canonical_engine == first.canonical_engine


def test_force_replaces_the_complete_run_directory(tmp_path) -> None:
    source = make_native_pdf(tmp_path / "source.pdf")
    output_root = tmp_path / "runs"
    base = AppConfig(
        workflow=WorkflowSettings(
            profile=Profile.FAST,
            output_root=output_root,
            render_visual_pages=False,
        ),
        validation=ValidationSettings(minimum_markdown_bytes=20),
    )
    with Workflow(base) as workflow:
        first = workflow.convert(source)
    stale = first.run_dir / "stale-candidate.txt"
    stale.write_text("old", encoding="utf-8")

    forced = AppConfig(
        workflow=WorkflowSettings(
            profile=Profile.FAST,
            output_root=output_root,
            render_visual_pages=False,
            force=True,
        ),
        validation=ValidationSettings(minimum_markdown_bytes=20),
    )
    with Workflow(forced) as workflow:
        second = workflow.convert(source)

    assert second.run_dir == first.run_dir
    assert not stale.exists()
    assert second.manifest_path.is_file()


def test_cache_rejects_changed_conversion_settings(tmp_path) -> None:
    source = make_native_pdf(tmp_path / "source.pdf")
    config = AppConfig(
        workflow=WorkflowSettings(
            profile=Profile.FAST,
            output_root=tmp_path / "runs",
            render_visual_pages=False,
        ),
        validation=ValidationSettings(minimum_markdown_bytes=20),
    )
    with Workflow(config) as workflow:
        workflow.convert(source)

    changed = replace(
        config,
        validation=replace(config.validation, minimum_native_token_recall=0.99),
    )
    with Workflow(changed) as workflow:
        with pytest.raises(RuntimeError, match="different conversion settings"):
            workflow.convert(source)


def test_model_engine_switch_releases_the_previous_model(monkeypatch) -> None:
    workflow = Workflow(AppConfig())
    hybrid = StubEngine()
    pure = StubEngine()
    workflow._engines[EngineName.GRANITE_HYBRID] = hybrid  # type: ignore[assignment]
    monkeypatch.setattr(
        "kilix_pdf_conversion.workflow.create_engine",
        lambda _name, _config: pure,
    )

    selected = workflow._engine(EngineName.GRANITE_PURE)

    assert selected is pure
    assert hybrid.closed
    assert EngineName.GRANITE_HYBRID not in workflow._engines


def test_failed_candidate_is_not_published_as_canonical(tmp_path) -> None:
    source = make_native_pdf(tmp_path / "source.pdf")
    config = AppConfig(
        workflow=WorkflowSettings(
            profile=Profile.FAST,
            output_root=tmp_path / "runs",
            render_visual_pages=False,
        ),
        validation=ValidationSettings(minimum_markdown_bytes=1_000_000),
    )

    with Workflow(config) as workflow:
        result = workflow.convert(source)

    assert result.status is QualityStatus.FAIL
    assert result.canonical_engine is None
    assert not (result.run_dir / "canonical.md").exists()
