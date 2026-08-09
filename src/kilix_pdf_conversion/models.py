from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class DocumentKind(StrEnum):
    NATIVE = "native"
    MIXED = "mixed"
    SCAN = "scan"


class Complexity(StrEnum):
    SIMPLE = "simple"
    COMPLEX = "complex"


class EngineName(StrEnum):
    PYMUPDF = "pymupdf4llm"
    GRANITE_HYBRID = "granite-hybrid"
    GRANITE_PURE = "granite-pure-vlm"
    MARKER = "marker"


class Profile(StrEnum):
    FAST = "fast"
    BALANCED = "balanced"
    QUALITY = "quality"
    FORENSIC = "forensic"


class QualityStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True)
class PageSignal:
    page_number: int
    native_characters: int
    nonspace_characters: int
    image_count: int
    drawing_count: int
    table_count: int
    max_table_columns: int
    multi_column: bool
    reliable_text: bool


@dataclass(frozen=True)
class DocumentAnalysis:
    source: str
    source_sha256: str
    source_bytes: int
    page_count: int
    native_text_characters: int
    reliable_text_page_ratio: float
    replacement_character_ratio: float
    image_count: int
    drawing_count_sampled: int
    detected_table_count: int
    max_detected_table_columns: int
    table_caption_numbers: tuple[int, ...]
    figure_caption_numbers: tuple[int, ...]
    multi_column_page_count: int
    sampled_page_numbers: tuple[int, ...]
    table_scanned_page_numbers: tuple[int, ...]
    document_kind: DocumentKind
    complexity: Complexity
    complexity_score: float
    pages: tuple[PageSignal, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["document_kind"] = self.document_kind.value
        data["complexity"] = self.complexity.value
        return data


@dataclass(frozen=True)
class RoutePlan:
    profile: Profile
    initial_engines: tuple[EngineName, ...]
    fallback_engines: tuple[EngineName, ...]
    rationale: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile.value,
            "initial_engines": [engine.value for engine in self.initial_engines],
            "fallback_engines": [engine.value for engine in self.fallback_engines],
            "rationale": list(self.rationale),
        }


@dataclass(frozen=True)
class EngineResult:
    engine: EngineName
    status: str
    markdown_path: str | None
    assets_path: str | None
    elapsed_seconds: float
    output_bytes: int
    engine_version: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["engine"] = self.engine.value
        return data


@dataclass(frozen=True)
class QualityReport:
    engine: EngineName
    status: QualityStatus
    score: float
    markdown_bytes: int
    token_count: int
    heading_count: int
    table_block_count: int
    max_markdown_table_columns: int
    image_reference_count: int
    image_placeholder_count: int
    broken_image_reference_count: int
    absolute_image_reference_count: int
    native_token_recall: float | None
    native_token_precision: float | None
    expected_table_captions: int
    observed_table_captions: int
    expected_figure_captions: int
    observed_figure_captions: int
    repeated_short_line: str | None
    repeated_short_line_count: int
    empty_math_block_count: int
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["engine"] = self.engine.value
        data["status"] = self.status.value
        return data


@dataclass(frozen=True)
class WorkflowResult:
    run_dir: Path
    canonical_engine: EngineName | None
    status: QualityStatus
    manifest_path: Path
