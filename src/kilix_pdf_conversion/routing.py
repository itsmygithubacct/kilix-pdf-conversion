from __future__ import annotations

from .models import (
    Complexity,
    DocumentAnalysis,
    DocumentKind,
    EngineName,
    Profile,
    RoutePlan,
)


def _deduplicate(engines: list[EngineName]) -> tuple[EngineName, ...]:
    return tuple(dict.fromkeys(engines))


def plan_route(analysis: DocumentAnalysis, profile: Profile) -> RoutePlan:
    kind = analysis.document_kind
    complex_layout = analysis.complexity is Complexity.COMPLEX
    rationale = [
        f"classified as {kind.value}",
        f"layout complexity is {analysis.complexity.value}",
    ]

    if profile is Profile.FAST:
        return RoutePlan(
            profile=profile,
            initial_engines=(EngineName.PYMUPDF,),
            fallback_engines=(),
            rationale=tuple(rationale + ["fast profile disables model-based conversion"]),
        )

    initial: list[EngineName] = []
    fallback: list[EngineName] = []

    if kind is DocumentKind.NATIVE:
        initial.append(EngineName.PYMUPDF)
        if complex_layout or profile in {Profile.QUALITY, Profile.FORENSIC}:
            initial.append(EngineName.GRANITE_HYBRID)
            rationale.append("hybrid VLM compares visual structure with guarded text substitution")
        else:
            fallback.append(EngineName.GRANITE_HYBRID)
        fallback.extend([EngineName.GRANITE_PURE, EngineName.MARKER])
    elif kind is DocumentKind.MIXED:
        initial.extend([EngineName.PYMUPDF, EngineName.GRANITE_PURE])
        fallback.extend([EngineName.MARKER, EngineName.GRANITE_HYBRID])
        rationale.append("mixed pages retain a native baseline and use visual OCR")
    else:
        initial.append(EngineName.GRANITE_PURE)
        fallback.append(EngineName.MARKER)
        rationale.append("image-driven conversion is required for scan pages")

    if profile is Profile.QUALITY and kind is not DocumentKind.NATIVE:
        initial.append(EngineName.MARKER)
        fallback = [engine for engine in fallback if engine is not EngineName.MARKER]
        rationale.append("quality profile adds an independent OCR candidate")

    if profile is Profile.FORENSIC:
        initial = [
            EngineName.PYMUPDF,
            EngineName.GRANITE_HYBRID,
            EngineName.GRANITE_PURE,
            EngineName.MARKER,
        ]
        fallback = []
        rationale.append("forensic profile runs every engine")

    return RoutePlan(
        profile=profile,
        initial_engines=_deduplicate(initial),
        fallback_engines=_deduplicate(fallback),
        rationale=tuple(rationale),
    )
