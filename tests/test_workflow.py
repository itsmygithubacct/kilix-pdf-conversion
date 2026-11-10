from __future__ import annotations

import json
from dataclasses import replace

import pytest

from kilix_pdf_conversion.config import AppConfig, ValidationSettings, WorkflowSettings
from kilix_pdf_conversion.models import (
    DocumentKind,
    EngineName,
    Profile,
    QualityReport,
    QualityStatus,
)
from kilix_pdf_conversion.workflow import Workflow

from .helpers import make_native_pdf


class StubEngine:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def passing_report(engine: EngineName, score: float) -> QualityReport:
    return QualityReport(
        engine=engine,
        status=QualityStatus.PASS,
        score=score,
        markdown_bytes=1000,
        token_count=100,
        heading_count=1,
        table_block_count=0,
        max_markdown_table_columns=0,
        image_reference_count=0,
        image_placeholder_count=0,
        broken_image_reference_count=0,
        absolute_image_reference_count=0,
        external_image_reference_count=0,
        escaping_image_reference_count=0,
        native_token_recall=1.0,
        native_token_precision=1.0,
        expected_table_captions=0,
        observed_table_captions=0,
        expected_figure_captions=0,
        observed_figure_captions=0,
        repeated_short_line=None,
        repeated_short_line_count=0,
        empty_math_block_count=0,
    )


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
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["recommendation"]["recommended_engine"] == "pymupdf4llm"
    assert manifest["recommendation_overridden"] is False


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
    archived = list((output_root / ".history").iterdir())
    assert len(archived) == 1
    assert (archived[0] / "stale-candidate.txt").read_text(encoding="utf-8") == "old"


def test_incomplete_run_is_archived_before_retry(tmp_path) -> None:
    source = make_native_pdf(tmp_path / "source.pdf")
    output_root = tmp_path / "runs"
    config = AppConfig(
        workflow=WorkflowSettings(
            profile=Profile.FAST,
            output_root=output_root,
            render_visual_pages=False,
        ),
        validation=ValidationSettings(minimum_markdown_bytes=20),
    )
    with Workflow(config) as workflow:
        first = workflow.convert(source)
    first.manifest_path.unlink()
    stale = first.run_dir / "stale-candidate.txt"
    stale.write_text("partial", encoding="utf-8")

    with Workflow(config) as workflow:
        retried = workflow.convert(source)

    assert retried.manifest_path.is_file()
    archives = list((output_root / ".history").iterdir())
    assert len(archives) == 1
    assert (archives[0] / "stale-candidate.txt").read_text(encoding="utf-8") == "partial"


def test_cache_rejects_corrupt_canonical_output(tmp_path) -> None:
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
    (first.run_dir / "canonical.md").write_text("tampered\n", encoding="utf-8")

    with Workflow(config) as workflow:
        with pytest.raises(RuntimeError, match="missing or corrupt"):
            workflow.convert(source)


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


@pytest.mark.parametrize("old_schema", [2, 3])
def test_old_quality_pass_cannot_be_reused_as_new_validation(tmp_path, old_schema) -> None:
    source = make_native_pdf(tmp_path / "source.pdf")
    config = AppConfig(workflow=WorkflowSettings(
        profile=Profile.FAST, output_root=tmp_path / "runs", render_visual_pages=False,
    ))
    with Workflow(config) as workflow:
        first = workflow.convert(source)
    old = json.loads(first.manifest_path.read_text())
    old["schema_version"] = old_schema
    old.pop("content_accuracy")
    first.manifest_path.write_text(json.dumps(old))
    before = first.manifest_path.read_bytes()
    with Workflow(config) as workflow:
        with pytest.raises(RuntimeError, match="unsupported manifest"):
            workflow.convert(source)
    assert first.manifest_path.read_bytes() == before


def test_changed_text_evidence_policy_invalidates_cached_validation(tmp_path, monkeypatch):
    from kilix_pdf_conversion import workflow as module

    source = make_native_pdf(tmp_path / "source.pdf")
    config = AppConfig(workflow=WorkflowSettings(
        profile=Profile.FAST, output_root=tmp_path / "runs", render_visual_pages=False,
    ))
    with Workflow(config) as workflow:
        first = workflow.convert(source)
    before = first.manifest_path.read_bytes()
    monkeypatch.setattr(module, "TEXT_EVIDENCE_POLICY_VERSION",
                        module.TEXT_EVIDENCE_POLICY_VERSION + 1)
    with Workflow(config) as workflow:
        with pytest.raises(RuntimeError, match="different conversion settings"):
            workflow.convert(source)
    assert first.manifest_path.read_bytes() == before


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
    assert "No complete-coverage candidate passed" in (
        result.run_dir / "report.md"
    ).read_text(encoding="utf-8")


def test_complete_coverage_candidate_beats_higher_scoring_partial_candidate() -> None:
    workflow = Workflow(AppConfig())
    reports = {
        EngineName.PYMUPDF: passing_report(EngineName.PYMUPDF, 100.0),
        EngineName.GRANITE_PURE: passing_report(EngineName.GRANITE_PURE, 90.0),
    }

    chosen = workflow._choose(
        reports,
        DocumentKind.MIXED,
        (EngineName.GRANITE_PURE, EngineName.MARKER),
    )

    assert chosen is EngineName.GRANITE_PURE


def test_partial_candidate_is_not_canonical_without_complete_coverage() -> None:
    workflow = Workflow(AppConfig())
    reports = {
        EngineName.PYMUPDF: passing_report(EngineName.PYMUPDF, 100.0),
    }

    chosen = workflow._choose(
        reports,
        DocumentKind.MIXED,
        (EngineName.GRANITE_PURE, EngineName.MARKER),
    )

    assert chosen is None


def test_configured_model_directories_are_fingerprinted() -> None:
    from pathlib import Path

    from kilix_pdf_conversion.config import GraniteSettings, OCRSettings
    from kilix_pdf_conversion.routing import plan_route

    from .helpers import analysis_stub

    plan = plan_route(analysis_stub(Path("x.pdf")), Profile.BALANCED)
    plain = Workflow(AppConfig())._configuration_sha256(plan, 3)
    granite = Workflow(AppConfig(granite=GraniteSettings(model_directory=Path("/m"))))
    ocr = Workflow(AppConfig(ocr=OCRSettings(model_directory=Path("/m"))))
    other = Workflow(AppConfig(ocr=OCRSettings(model_directory=Path("/n"))))
    digests = {plain, granite._configuration_sha256(plan, 3), ocr._configuration_sha256(plan, 3),
               other._configuration_sha256(plan, 3)}
    assert len(digests) == 4
    assert Workflow(AppConfig(ocr=OCRSettings(dpi=300)))._configuration_sha256(plan, 3) != plain
