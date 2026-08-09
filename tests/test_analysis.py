from __future__ import annotations

from kilix_pdf_conversion.analysis import analyze_pdf, evenly_spaced_pages
from kilix_pdf_conversion.models import DocumentKind

from .helpers import make_native_pdf, make_scan_pdf


def test_evenly_spaced_pages_covers_ends() -> None:
    pages = evenly_spaced_pages(100, maximum=7)
    assert pages[0] == 0
    assert pages[-1] == 99
    assert len(pages) == 7


def test_native_pdf_is_classified_as_native(tmp_path) -> None:
    source = make_native_pdf(tmp_path / "native.pdf")
    analysis = analyze_pdf(source)
    assert analysis.document_kind is DocumentKind.NATIVE
    assert analysis.page_count == 1
    assert analysis.reliable_text_page_ratio == 1.0
    assert analysis.source_sha256


def test_image_only_pdf_is_classified_as_scan(tmp_path) -> None:
    source = make_scan_pdf(tmp_path / "scan.pdf")
    analysis = analyze_pdf(source)
    assert analysis.document_kind is DocumentKind.SCAN
    assert analysis.image_count >= 1
    assert analysis.reliable_text_page_ratio == 0.0
