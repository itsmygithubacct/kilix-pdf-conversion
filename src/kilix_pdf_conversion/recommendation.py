from __future__ import annotations

from collections.abc import Collection

from .models import (
    Complexity,
    ConversionRecommendation,
    DocumentAnalysis,
    DocumentKind,
    EngineName,
    Profile,
    RecommendationConfidence,
)
from .routing import plan_route

RECOMMENDATION_POLICY_VERSION = 2


def _deduplicate(engines: Collection[EngineName]) -> tuple[EngineName, ...]:
    return tuple(dict.fromkeys(engines))


def _recommended_engine(analysis: DocumentAnalysis, profile: Profile) -> EngineName:
    if profile is Profile.FAST:
        return EngineName.PYMUPDF
    if analysis.document_kind is DocumentKind.NATIVE:
        return EngineName.PYMUPDF
    return EngineName.GRANITE_PURE


def _document_priority(analysis: DocumentAnalysis) -> tuple[EngineName, ...]:
    if analysis.document_kind is DocumentKind.NATIVE:
        return (
            EngineName.PYMUPDF,
            EngineName.GRANITE_HYBRID,
            EngineName.GRANITE_PURE,
            EngineName.MARKER,
        )
    if analysis.document_kind is DocumentKind.MIXED:
        return (
            EngineName.GRANITE_PURE,
            EngineName.MARKER,
            EngineName.PYMUPDF,
            EngineName.GRANITE_HYBRID,
        )
    return (
        EngineName.GRANITE_PURE,
        EngineName.MARKER,
        EngineName.PYMUPDF,
        EngineName.GRANITE_HYBRID,
    )


def _confidence(analysis: DocumentAnalysis) -> RecommendationConfidence:
    if analysis.source_text_evidence.get("trust") != "trusted":
        return RecommendationConfidence.LOW
    if analysis.warnings or analysis.replacement_character_ratio > 0.01:
        return RecommendationConfidence.LOW
    if analysis.document_kind is DocumentKind.MIXED:
        return RecommendationConfidence.MEDIUM
    if analysis.document_kind is DocumentKind.NATIVE:
        if analysis.reliable_text_page_ratio >= 0.95:
            return RecommendationConfidence.HIGH
        return RecommendationConfidence.MEDIUM
    if analysis.reliable_text_page_ratio <= 0.05:
        return RecommendationConfidence.HIGH
    return RecommendationConfidence.MEDIUM


def _rationale(
    analysis: DocumentAnalysis,
    profile: Profile,
    recommended: EngineName,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if profile is Profile.FAST:
        reasons.append("fast profile constrains the choice to native extraction")
    elif analysis.document_kind is DocumentKind.NATIVE:
        reasons.append(
            "embedded text is available for native extraction; rendering support "
            "and content uncertainty are reported separately"
        )
        if analysis.complexity is Complexity.COMPLEX:
            reasons.append(
                "complex layout merits a Granite hybrid comparison without replacing "
                "the native-text baseline"
            )
    elif analysis.document_kind is DocumentKind.MIXED:
        reasons.append(
            "some pages lack reliable text, so visual OCR is required while native "
            "extraction remains a comparison candidate"
        )
    else:
        reasons.append(
            "the document has no reliable embedded text, so image-driven OCR is required"
        )
    reasons.append(f"recommended program is {recommended.value}")
    return tuple(reasons)


def _review_reasons(analysis: DocumentAnalysis) -> tuple[str, ...]:
    reasons: list[str] = [
        "automated checks do not independently verify transcription, numeric cells or reading order"
    ]
    if analysis.document_kind is DocumentKind.SCAN:
        reasons.append("scan output has no native text reference for exactness checks")
    elif analysis.document_kind is DocumentKind.MIXED:
        reasons.append("mixed native and image-only pages can have inconsistent OCR quality")
    if analysis.detected_table_count or analysis.table_caption_numbers:
        reasons.append("tables require cell and numeric-value review")
    if analysis.figure_caption_numbers or analysis.image_count:
        reasons.append("figures and charts require visual review against source-page renders")
    if analysis.multi_column_page_count:
        reasons.append("multi-column reading order requires review")
    reasons.extend(analysis.warnings)
    return tuple(dict.fromkeys(reasons))


def recommend_conversion(
    analysis: DocumentAnalysis,
    profile: Profile = Profile.BALANCED,
    *,
    available_engines: Collection[EngineName] | None = None,
) -> ConversionRecommendation:
    route = plan_route(analysis, profile)
    recommended = _recommended_engine(analysis, profile)
    route_candidates = _deduplicate(
        route.initial_engines + route.fallback_engines
    )
    priority = _deduplicate(
        tuple(
            engine
            for engine in _document_priority(analysis)
            if engine in route_candidates
        )
        + route_candidates
    )
    comparisons = tuple(
        engine for engine in route.initial_engines if engine is not recommended
    )

    if analysis.document_kind is DocumentKind.NATIVE:
        complete_coverage = route_candidates
    else:
        complete_coverage = tuple(
            engine
            for engine in (EngineName.GRANITE_PURE, EngineName.MARKER)
            if engine in route_candidates
        )

    installed = (
        None
        if available_engines is None
        else tuple(engine for engine in EngineName if engine in available_engines)
    )
    assumed_installed = tuple(EngineName) if installed is None else installed
    best_available = next(
        (
            engine
            for engine in priority
            if engine in assumed_installed and engine in complete_coverage
        ),
        None,
    )
    best_partial = None
    if best_available is None:
        best_partial = next(
            (engine for engine in priority if engine in assumed_installed),
            None,
        )

    return ConversionRecommendation(
        policy_version=RECOMMENDATION_POLICY_VERSION,
        profile=profile,
        recommended_engine=recommended,
        best_available_engine=best_available,
        best_partial_engine=best_partial,
        candidate_priority=priority,
        comparison_engines=comparisons,
        fallback_engines=route.fallback_engines,
        complete_coverage_engines=complete_coverage,
        confidence=_confidence(analysis),
        available_engines=installed,
        rationale=_rationale(analysis, profile, recommended),
        review_reasons=_review_reasons(analysis),
        route=route,
    )
