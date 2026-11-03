from __future__ import annotations

from pathlib import Path

from .models import (
    DocumentAnalysis,
    EngineName,
    EngineResult,
    QualityReport,
    QualityStatus,
    RoutePlan,
)
from .util import atomic_write_text


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def write_run_report(
    path: Path,
    analysis: DocumentAnalysis,
    plan: RoutePlan,
    recommended_engine: EngineName,
    required_coverage_engines: tuple[EngineName, ...],
    engine_results: dict[EngineName, EngineResult],
    quality_reports: dict[EngineName, QualityReport],
    canonical_engine: EngineName | None,
    status: QualityStatus,
) -> None:
    lines = [
        "# Conversion report",
        "",
        f"- Status: **{status.value}**",
        "- Content accuracy: **not independently verified**",
        "- Status and score describe automated checks, not a percentage of correct content.",
        f"- Document class: **{analysis.document_kind.value}**",
        f"- Layout complexity: **{analysis.complexity.value}**",
        f"- Pages: {analysis.page_count}",
        f"- Source SHA-256: {analysis.source_sha256}",
        f"- Profile: {plan.profile.value}",
        f"- Recommended engine: {recommended_engine.value}",
        f"- Canonical engine: {canonical_engine.value if canonical_engine else 'none'}",
        "",
        "## Route",
        "",
    ]
    lines.extend(f"- {reason}" for reason in plan.rationale)
    lines.extend(
        [
            "",
            "## Candidates",
            "",
            "| Engine | Conversion | Checks | Heuristic score | Runtime | Supported-text agreement | Tables | Images |",
            "|---|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for engine, result in engine_results.items():
        quality = quality_reports.get(engine)
        lines.append(
            "| "
            + " | ".join(
                [
                    engine.value,
                    result.status,
                    quality.status.value if quality else "n/a",
                    f"{quality.score:.1f}" if quality else "n/a",
                    f"{result.elapsed_seconds:.2f} s",
                    _percent(quality.native_token_recall if quality else None),
                    str(quality.table_block_count) if quality else "n/a",
                    str(quality.image_reference_count) if quality else "n/a",
                ]
            )
            + " |"
        )
    for engine, quality in quality_reports.items():
        if not quality.errors and not quality.warnings:
            continue
        lines.extend(["", f"### {engine.value}", ""])
        lines.extend(f"- Error: {message}" for message in quality.errors)
        lines.extend(f"- Warning: {message}" for message in quality.warnings)
    if canonical_engine is None and required_coverage_engines:
        lines.extend(
            [
                "",
                "## Coverage decision",
                "",
                "No complete-coverage candidate passed. Partial candidates were retained "
                "for inspection but were not published as canonical.",
                "",
                "Required coverage engines: "
                + ", ".join(engine.value for engine in required_coverage_engines),
            ]
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "The canonical file is the highest-ranked usable candidate under the configured "
            "checks. A pass means no covered issue was detected; a warning requires review. "
            "Neither status verifies transcription, numeric cells or reading order. "
            "Extracted text can itself be inaccurate, especially in invisible OCR layers. "
            "Candidate outputs remain available for comparison with the visible source pages.",
            "",
        ]
    )
    atomic_write_text(path, "\n".join(lines))
