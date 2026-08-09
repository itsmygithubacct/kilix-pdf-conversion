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
    engine_results: dict[EngineName, EngineResult],
    quality_reports: dict[EngineName, QualityReport],
    canonical_engine: EngineName | None,
    status: QualityStatus,
) -> None:
    lines = [
        "# Conversion report",
        "",
        f"- Status: **{status.value}**",
        f"- Document class: **{analysis.document_kind.value}**",
        f"- Layout complexity: **{analysis.complexity.value}**",
        f"- Pages: {analysis.page_count}",
        f"- Source SHA-256: {analysis.source_sha256}",
        f"- Profile: {plan.profile.value}",
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
            "| Engine | Conversion | Quality | Score | Runtime | Recall | Tables | Images |",
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
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "The canonical file is the highest-ranked candidate that passed the configured "
            "quality gates. Candidate outputs remain available for direct comparison. "
            "The source PDF remains authoritative for visual and numeric verification.",
            "",
        ]
    )
    atomic_write_text(path, "\n".join(lines))
