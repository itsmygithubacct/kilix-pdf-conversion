from __future__ import annotations

from kilix_pdf_conversion.models import (
    Complexity,
    DocumentKind,
    EngineName,
    Profile,
)
from kilix_pdf_conversion.routing import plan_route

from .helpers import analysis_stub


def test_balanced_native_simple_starts_with_pymupdf(tmp_path) -> None:
    plan = plan_route(analysis_stub(tmp_path / "x.pdf"), Profile.BALANCED)
    assert plan.initial_engines == (EngineName.PYMUPDF,)
    assert plan.fallback_engines[0] is EngineName.GRANITE_HYBRID


def test_balanced_native_complex_adds_hybrid(tmp_path) -> None:
    analysis = analysis_stub(
        tmp_path / "x.pdf",
        complexity=Complexity.COMPLEX,
    )
    plan = plan_route(analysis, Profile.BALANCED)
    assert plan.initial_engines == (
        EngineName.PYMUPDF,
        EngineName.GRANITE_HYBRID,
    )


def test_mixed_document_uses_native_and_visual_candidates(tmp_path) -> None:
    analysis = analysis_stub(tmp_path / "x.pdf", kind=DocumentKind.MIXED)
    plan = plan_route(analysis, Profile.BALANCED)
    assert plan.initial_engines == (
        EngineName.PYMUPDF,
        EngineName.GRANITE_PURE,
    )
    assert plan.fallback_engines[0] is EngineName.MARKER


def test_scan_uses_pure_vlm_then_marker(tmp_path) -> None:
    analysis = analysis_stub(tmp_path / "x.pdf", kind=DocumentKind.SCAN)
    plan = plan_route(analysis, Profile.BALANCED)
    assert plan.initial_engines == (EngineName.GRANITE_PURE,)
    assert plan.fallback_engines == (EngineName.MARKER,)


def test_forensic_profile_runs_every_engine(tmp_path) -> None:
    plan = plan_route(analysis_stub(tmp_path / "x.pdf"), Profile.FORENSIC)
    assert set(plan.initial_engines) == set(EngineName)
    assert not plan.fallback_engines
