from __future__ import annotations

import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .models import Profile


@dataclass(frozen=True)
class WorkflowSettings:
    profile: Profile = Profile.BALANCED
    output_root: Path = Path("output")
    copy_source: bool = True
    render_visual_pages: bool = True
    force: bool = False


@dataclass(frozen=True)
class AnalysisSettings:
    reliable_page_characters: int = 80
    native_page_ratio: float = 0.80
    scan_page_ratio: float = 0.20
    max_table_scan_pages: int = 24


@dataclass(frozen=True)
class PyMuPDFSettings:
    dpi: int = 150
    write_images: bool = True
    include_headers: bool = False
    include_footers: bool = False


@dataclass(frozen=True)
class GraniteSettings:
    device: str = "cuda"
    page_batch_size: int = 1
    threads: int = 4
    document_timeout: float = 1800.0
    chart_extraction: bool = False


@dataclass(frozen=True)
class MarkerSettings:
    device: str = "auto"


@dataclass(frozen=True)
class ValidationSettings:
    minimum_markdown_bytes: int = 200
    minimum_native_token_recall: float = 0.90
    maximum_repeated_short_line_count: int = 20
    fail_on_image_placeholders: bool = True


@dataclass(frozen=True)
class AppConfig:
    workflow: WorkflowSettings = WorkflowSettings()
    analysis: AnalysisSettings = AnalysisSettings()
    pymupdf: PyMuPDFSettings = PyMuPDFSettings()
    granite: GraniteSettings = GraniteSettings()
    marker: MarkerSettings = MarkerSettings()
    validation: ValidationSettings = ValidationSettings()


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"configuration section [{name}] must be a table")
    return value


def load_config(path: Path | None = None) -> AppConfig:
    if path is None:
        return AppConfig()
    path = path.expanduser().resolve()
    with path.open("rb") as source:
        data = tomllib.load(source)

    workflow_data = _section(data, "workflow")
    profile = Profile(workflow_data.get("profile", Profile.BALANCED.value))
    workflow = WorkflowSettings(
        profile=profile,
        output_root=Path(workflow_data.get("output_root", "output")),
        copy_source=bool(workflow_data.get("copy_source", True)),
        render_visual_pages=bool(workflow_data.get("render_visual_pages", True)),
        force=bool(workflow_data.get("force", False)),
    )
    analysis_data = _section(data, "analysis")
    analysis = AnalysisSettings(
        reliable_page_characters=int(
            analysis_data.get("reliable_page_characters", 80)
        ),
        native_page_ratio=float(analysis_data.get("native_page_ratio", 0.80)),
        scan_page_ratio=float(analysis_data.get("scan_page_ratio", 0.20)),
        max_table_scan_pages=int(analysis_data.get("max_table_scan_pages", 24)),
    )
    pymupdf_data = _section(data, "pymupdf")
    pymupdf = PyMuPDFSettings(
        dpi=int(pymupdf_data.get("dpi", 150)),
        write_images=bool(pymupdf_data.get("write_images", True)),
        include_headers=bool(pymupdf_data.get("include_headers", False)),
        include_footers=bool(pymupdf_data.get("include_footers", False)),
    )
    granite_data = _section(data, "granite")
    granite = GraniteSettings(
        device=str(granite_data.get("device", "cuda")),
        page_batch_size=int(granite_data.get("page_batch_size", 1)),
        threads=int(granite_data.get("threads", 4)),
        document_timeout=float(granite_data.get("document_timeout", 1800)),
        chart_extraction=bool(granite_data.get("chart_extraction", False)),
    )
    marker_data = _section(data, "marker")
    marker = MarkerSettings(device=str(marker_data.get("device", "auto")))
    validation_data = _section(data, "validation")
    validation = ValidationSettings(
        minimum_markdown_bytes=int(
            validation_data.get("minimum_markdown_bytes", 200)
        ),
        minimum_native_token_recall=float(
            validation_data.get("minimum_native_token_recall", 0.90)
        ),
        maximum_repeated_short_line_count=int(
            validation_data.get("maximum_repeated_short_line_count", 20)
        ),
        fail_on_image_placeholders=bool(
            validation_data.get("fail_on_image_placeholders", True)
        ),
    )
    return AppConfig(
        workflow=workflow,
        analysis=analysis,
        pymupdf=pymupdf,
        granite=granite,
        marker=marker,
        validation=validation,
    )


def with_overrides(
    config: AppConfig,
    *,
    profile: Profile | None = None,
    output_root: Path | None = None,
    force: bool | None = None,
    device: str | None = None,
) -> AppConfig:
    workflow = replace(
        config.workflow,
        profile=profile if profile is not None else config.workflow.profile,
        output_root=output_root if output_root is not None else config.workflow.output_root,
        force=force if force is not None else config.workflow.force,
    )
    granite = replace(
        config.granite,
        device=device if device is not None else config.granite.device,
    )
    marker = replace(
        config.marker,
        device=device if device is not None else config.marker.device,
    )
    return replace(config, workflow=workflow, granite=granite, marker=marker)
