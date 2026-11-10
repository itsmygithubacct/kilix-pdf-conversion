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
    PAGE_OCR = "page-ocr"


class Profile(StrEnum):
    FAST = "fast"
    BALANCED = "balanced"
    QUALITY = "quality"
    FORENSIC = "forensic"


class QualityStatus(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class RecommendationConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


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
    source_text_trust: str = "unknown"


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
    source_text_evidence: dict[str, Any] = field(default_factory=dict)

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
class ConversionRecommendation:
    policy_version: int
    profile: Profile
    recommended_engine: EngineName
    best_available_engine: EngineName | None
    best_partial_engine: EngineName | None
    candidate_priority: tuple[EngineName, ...]
    comparison_engines: tuple[EngineName, ...]
    fallback_engines: tuple[EngineName, ...]
    complete_coverage_engines: tuple[EngineName, ...]
    confidence: RecommendationConfidence
    available_engines: tuple[EngineName, ...] | None
    rationale: tuple[str, ...]
    review_reasons: tuple[str, ...]
    route: RoutePlan

    def to_dict(self) -> dict[str, Any]:
        route_engines = tuple(
            dict.fromkeys(self.route.initial_engines + self.route.fallback_engines)
        )
        unavailable = (
            None
            if self.available_engines is None
            else [
                engine.value
                for engine in route_engines
                if engine not in self.available_engines
            ]
        )
        return {
            "policy_version": self.policy_version,
            "profile": self.profile.value,
            "recommended_engine": self.recommended_engine.value,
            "recommended_engine_available": (
                None
                if self.available_engines is None
                else self.recommended_engine in self.available_engines
            ),
            "best_available_engine": (
                self.best_available_engine.value if self.best_available_engine else None
            ),
            "best_partial_engine": (
                self.best_partial_engine.value if self.best_partial_engine else None
            ),
            "candidate_priority": [
                engine.value for engine in self.candidate_priority
            ],
            "comparison_engines": [
                engine.value for engine in self.comparison_engines
            ],
            "fallback_engines": [engine.value for engine in self.fallback_engines],
            "complete_coverage_engines": [
                engine.value for engine in self.complete_coverage_engines
            ],
            "confidence": self.confidence.value,
            "available_engines": (
                None
                if self.available_engines is None
                else [engine.value for engine in self.available_engines]
            ),
            "unavailable_route_engines": unavailable,
            "rationale": list(self.rationale),
            "review_reasons": list(self.review_reasons),
            "route": self.route.to_dict(),
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
    external_image_reference_count: int
    escaping_image_reference_count: int
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
    source_text_evidence: dict[str, Any] = field(default_factory=dict)
    score_kind: str = "heuristic_checks"
    content_accuracy: str = "unverified"
    fallback_recommended: bool = True

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
