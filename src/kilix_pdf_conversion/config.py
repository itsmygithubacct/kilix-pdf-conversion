from __future__ import annotations

import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .models import Profile


def _require_boolean(value: object, label: str) -> None:
    if type(value) is not bool:
        raise ValueError(f"{label} must be true or false")


def _require_integer(
    value: object,
    label: str,
    *,
    minimum: int,
    maximum: int | None = None,
) -> None:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label} must be an integer of at least {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label} must be no greater than {maximum}")


def _require_ratio(value: object, label: str) -> None:
    if type(value) not in (int, float) or not 0.0 <= float(value) <= 1.0:
        raise ValueError(f"{label} must be a number from 0 through 1")


def _require_device(value: object, label: str) -> None:
    if value not in {"auto", "cpu", "cuda"}:
        raise ValueError(f"{label} must be auto, cpu, or cuda")


@dataclass(frozen=True)
class WorkflowSettings:
    profile: Profile = Profile.BALANCED
    output_root: Path = Path("output")
    copy_source: bool = True
    render_visual_pages: bool = True
    force: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.profile, Profile):
            raise ValueError("workflow.profile must be a known profile")
        if not isinstance(self.output_root, Path):
            raise ValueError("workflow.output_root must be a filesystem path")
        _require_boolean(self.copy_source, "workflow.copy_source")
        _require_boolean(
            self.render_visual_pages,
            "workflow.render_visual_pages",
        )
        _require_boolean(self.force, "workflow.force")


@dataclass(frozen=True)
class AnalysisSettings:
    reliable_page_characters: int = 80
    native_page_ratio: float = 0.80
    scan_page_ratio: float = 0.20
    max_table_scan_pages: int = 24

    def __post_init__(self) -> None:
        _require_integer(
            self.reliable_page_characters,
            "analysis.reliable_page_characters",
            minimum=1,
        )
        _require_ratio(self.native_page_ratio, "analysis.native_page_ratio")
        _require_ratio(self.scan_page_ratio, "analysis.scan_page_ratio")
        if float(self.scan_page_ratio) >= float(self.native_page_ratio):
            raise ValueError(
                "analysis.scan_page_ratio must be below analysis.native_page_ratio"
            )
        _require_integer(
            self.max_table_scan_pages,
            "analysis.max_table_scan_pages",
            minimum=1,
        )


@dataclass(frozen=True)
class PyMuPDFSettings:
    dpi: int = 150
    write_images: bool = True
    include_headers: bool = False
    include_footers: bool = False

    def __post_init__(self) -> None:
        _require_integer(self.dpi, "pymupdf.dpi", minimum=36, maximum=1200)
        _require_boolean(self.write_images, "pymupdf.write_images")
        _require_boolean(self.include_headers, "pymupdf.include_headers")
        _require_boolean(self.include_footers, "pymupdf.include_footers")


@dataclass(frozen=True)
class GraniteSettings:
    device: str = "cpu"
    page_batch_size: int = 1
    threads: int = 2
    document_timeout: float = 1800.0
    chart_extraction: bool = False
    model_directory: Path | None = None
    max_new_tokens: int = 8192

    def __post_init__(self) -> None:
        _require_device(self.device, "granite.device")
        _require_integer(
            self.page_batch_size,
            "granite.page_batch_size",
            minimum=1,
            maximum=64,
        )
        _require_integer(self.threads, "granite.threads", minimum=1, maximum=256)
        if (
            type(self.document_timeout) not in (int, float)
            or not 0.0 < float(self.document_timeout) <= 86400.0
        ):
            raise ValueError(
                "granite.document_timeout must be greater than 0 and at most 86400"
            )
        _require_boolean(self.chart_extraction, "granite.chart_extraction")
        if self.model_directory is not None and not isinstance(self.model_directory, Path):
            raise ValueError("granite.model_directory must be a filesystem path")
        _require_integer(self.max_new_tokens, "granite.max_new_tokens", minimum=1, maximum=8192)


@dataclass(frozen=True)
class MarkerSettings:
    device: str = "auto"

    def __post_init__(self) -> None:
        _require_device(self.device, "marker.device")


@dataclass(frozen=True)
class ValidationSettings:
    minimum_markdown_bytes: int = 200
    minimum_native_token_recall: float = 0.90
    maximum_repeated_short_line_count: int = 20
    fail_on_image_placeholders: bool = True

    def __post_init__(self) -> None:
        _require_integer(
            self.minimum_markdown_bytes,
            "validation.minimum_markdown_bytes",
            minimum=1,
        )
        _require_ratio(
            self.minimum_native_token_recall,
            "validation.minimum_native_token_recall",
        )
        _require_integer(
            self.maximum_repeated_short_line_count,
            "validation.maximum_repeated_short_line_count",
            minimum=1,
        )
        _require_boolean(
            self.fail_on_image_placeholders,
            "validation.fail_on_image_placeholders",
        )


@dataclass(frozen=True)
class AppConfig:
    workflow: WorkflowSettings = WorkflowSettings()
    analysis: AnalysisSettings = AnalysisSettings()
    pymupdf: PyMuPDFSettings = PyMuPDFSettings()
    granite: GraniteSettings = GraniteSettings()
    marker: MarkerSettings = MarkerSettings()
    validation: ValidationSettings = ValidationSettings()

    def __post_init__(self) -> None:
        expected = (
            (self.workflow, WorkflowSettings, "workflow"),
            (self.analysis, AnalysisSettings, "analysis"),
            (self.pymupdf, PyMuPDFSettings, "pymupdf"),
            (self.granite, GraniteSettings, "granite"),
            (self.marker, MarkerSettings, "marker"),
            (self.validation, ValidationSettings, "validation"),
        )
        for value, value_type, label in expected:
            if not isinstance(value, value_type):
                raise ValueError(f"{label} has the wrong configuration type")


def _section(
    data: dict[str, Any],
    name: str,
    allowed_keys: frozenset[str],
) -> dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"configuration section [{name}] must be a table")
    unknown = sorted(set(value) - allowed_keys)
    if unknown:
        raise ValueError(
            f"unknown option in [{name}]: {', '.join(unknown)}"
        )
    return value


def load_config(path: Path | None = None) -> AppConfig:
    if path is None:
        return AppConfig()
    path = path.expanduser().resolve()
    with path.open("rb") as source:
        data = tomllib.load(source)

    known_sections = {
        "workflow",
        "analysis",
        "pymupdf",
        "granite",
        "marker",
        "validation",
    }
    unknown_sections = sorted(set(data) - known_sections)
    if unknown_sections:
        raise ValueError(
            f"unknown configuration section: {', '.join(unknown_sections)}"
        )

    workflow_data = _section(
        data,
        "workflow",
        frozenset(
            {"profile", "output_root", "copy_source", "render_visual_pages", "force"}
        ),
    )
    profile = Profile(workflow_data.get("profile", Profile.BALANCED.value))
    output_root_value = workflow_data.get("output_root", "output")
    if not isinstance(output_root_value, str):
        raise ValueError("workflow.output_root must be a filesystem path string")
    workflow = WorkflowSettings(
        profile=profile,
        output_root=Path(output_root_value),
        copy_source=workflow_data.get("copy_source", True),
        render_visual_pages=workflow_data.get("render_visual_pages", True),
        force=workflow_data.get("force", False),
    )
    analysis_data = _section(
        data,
        "analysis",
        frozenset(
            {
                "reliable_page_characters",
                "native_page_ratio",
                "scan_page_ratio",
                "max_table_scan_pages",
            }
        ),
    )
    analysis = AnalysisSettings(
        reliable_page_characters=analysis_data.get("reliable_page_characters", 80),
        native_page_ratio=analysis_data.get("native_page_ratio", 0.80),
        scan_page_ratio=analysis_data.get("scan_page_ratio", 0.20),
        max_table_scan_pages=analysis_data.get("max_table_scan_pages", 24),
    )
    pymupdf_data = _section(
        data,
        "pymupdf",
        frozenset({"dpi", "write_images", "include_headers", "include_footers"}),
    )
    pymupdf = PyMuPDFSettings(
        dpi=pymupdf_data.get("dpi", 150),
        write_images=pymupdf_data.get("write_images", True),
        include_headers=pymupdf_data.get("include_headers", False),
        include_footers=pymupdf_data.get("include_footers", False),
    )
    granite_data = _section(
        data,
        "granite",
        frozenset(
            {
                "device",
                "page_batch_size",
                "threads",
                "document_timeout",
                "chart_extraction",
                "model_directory",
                "max_new_tokens",
            }
        ),
    )
    model_directory = granite_data.get("model_directory")
    if model_directory is not None and not isinstance(model_directory, str):
        raise ValueError("granite.model_directory must be a filesystem path string")
    granite = GraniteSettings(
        device=granite_data.get("device", "cpu"),
        page_batch_size=granite_data.get("page_batch_size", 1),
        threads=granite_data.get("threads", 2),
        document_timeout=granite_data.get("document_timeout", 1800),
        chart_extraction=granite_data.get("chart_extraction", False),
        model_directory=Path(model_directory) if model_directory is not None else None,
        max_new_tokens=granite_data.get("max_new_tokens", 8192),
    )
    marker_data = _section(data, "marker", frozenset({"device"}))
    marker = MarkerSettings(device=marker_data.get("device", "auto"))
    validation_data = _section(
        data,
        "validation",
        frozenset(
            {
                "minimum_markdown_bytes",
                "minimum_native_token_recall",
                "maximum_repeated_short_line_count",
                "fail_on_image_placeholders",
            }
        ),
    )
    validation = ValidationSettings(
        minimum_markdown_bytes=validation_data.get("minimum_markdown_bytes", 200),
        minimum_native_token_recall=validation_data.get(
            "minimum_native_token_recall", 0.90
        ),
        maximum_repeated_short_line_count=validation_data.get(
            "maximum_repeated_short_line_count", 20
        ),
        fail_on_image_placeholders=validation_data.get(
            "fail_on_image_placeholders", True
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
