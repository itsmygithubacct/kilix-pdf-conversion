from __future__ import annotations

from kilix_pdf_conversion.models import (
    Complexity,
    DocumentKind,
    EngineName,
    Profile,
    RecommendationConfidence,
)
from kilix_pdf_conversion.recommendation import recommend_conversion

from .helpers import analysis_stub


def test_native_document_recommends_native_extraction(tmp_path) -> None:
    recommendation = recommend_conversion(
        analysis_stub(tmp_path / "native.pdf"),
        available_engines={EngineName.PYMUPDF},
    )

    assert recommendation.recommended_engine is EngineName.PYMUPDF
    assert recommendation.best_available_engine is EngineName.PYMUPDF
    assert recommendation.confidence is RecommendationConfidence.HIGH


def test_complex_native_document_adds_hybrid_comparison(tmp_path) -> None:
    analysis = analysis_stub(
        tmp_path / "complex.pdf",
        complexity=Complexity.COMPLEX,
    )
    recommendation = recommend_conversion(analysis)

    assert recommendation.recommended_engine is EngineName.PYMUPDF
    assert recommendation.comparison_engines == (EngineName.GRANITE_HYBRID,)


def test_mixed_document_prefers_marker_when_granite_is_unavailable(tmp_path) -> None:
    analysis = analysis_stub(tmp_path / "mixed.pdf", kind=DocumentKind.MIXED)
    recommendation = recommend_conversion(
        analysis,
        available_engines={EngineName.PYMUPDF, EngineName.MARKER},
    )

    assert recommendation.recommended_engine is EngineName.GRANITE_PURE
    assert recommendation.best_available_engine is EngineName.MARKER
    assert recommendation.complete_coverage_engines == (
        EngineName.GRANITE_PURE,
        EngineName.MARKER,
    )


def test_scan_does_not_present_native_extraction_as_suitable(tmp_path) -> None:
    analysis = analysis_stub(tmp_path / "scan.pdf", kind=DocumentKind.SCAN)
    recommendation = recommend_conversion(
        analysis,
        available_engines={EngineName.PYMUPDF},
    )

    assert recommendation.recommended_engine is EngineName.GRANITE_PURE
    assert recommendation.best_available_engine is None


def test_fast_profile_records_its_native_only_constraint(tmp_path) -> None:
    analysis = analysis_stub(tmp_path / "scan.pdf", kind=DocumentKind.SCAN)
    recommendation = recommend_conversion(analysis, Profile.FAST)

    assert recommendation.recommended_engine is EngineName.PYMUPDF
    assert recommendation.complete_coverage_engines == ()
    assert recommendation.best_available_engine is None
    assert recommendation.best_partial_engine is EngineName.PYMUPDF
    assert "constrains" in recommendation.rationale[0]


def test_native_only_install_is_partial_for_mixed_document(tmp_path) -> None:
    analysis = analysis_stub(tmp_path / "mixed.pdf", kind=DocumentKind.MIXED)
    recommendation = recommend_conversion(
        analysis,
        available_engines={EngineName.PYMUPDF},
    )

    assert recommendation.best_available_engine is None
    assert recommendation.best_partial_engine is EngineName.PYMUPDF
