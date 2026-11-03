from __future__ import annotations

import pymupdf
import pytest

from kilix_pdf_conversion.analysis import analyze_pdf
from kilix_pdf_conversion.config import ValidationSettings
from kilix_pdf_conversion.models import EngineName, QualityStatus
from kilix_pdf_conversion.quality import validate_markdown
from kilix_pdf_conversion.text_evidence import (
    TextTrust,
    choose_hybrid_text,
    inspect_source_text,
)


def make_text_pdf(path, lines, *, mode="visible"):
    with pymupdf.open() as doc:
        page = doc.new_page(width=612, height=792)
        options = {"fontsize": 11}
        if mode == "invisible":
            options["render_mode"] = 3
        if mode == "transparent":
            options["fill_opacity"] = 0
        if mode == "white":
            options["color"] = (1, 1, 1)
        for index, line in enumerate(lines):
            page.insert_text((40, 50 + index * 20), line, **options)
        if mode == "covered":
            page.draw_rect(page.rect, color=None, fill=(1, 1, 1))
        doc.save(path)
    return path


@pytest.mark.parametrize("mode,expected", [
    ("visible", TextTrust.TRUSTED), ("invisible", TextTrust.UNKNOWN),
    ("transparent", TextTrust.UNKNOWN), ("white", TextTrust.SUSPECT),
    ("covered", TextTrust.UNKNOWN),
])
def test_rendering_evidence_does_not_treat_extraction_as_visible(tmp_path, mode, expected):
    source = make_text_pdf(tmp_path / "page.pdf", ["Record 12 and keep both copies."], mode=mode)
    evidence = inspect_source_text(source)
    assert evidence.trust is expected
    assert bool(evidence.reference_text) == (expected is TextTrust.TRUSTED)
    assert evidence.summary()["content_accuracy"] == "unverified"


@pytest.mark.parametrize("model,backend,trust,action", [
    ("Total 42.", "", "trusted", "retain"),
    ("Keep all 27 parts.", "27 parts.", "trusted", "retain"),
    ("Level -8.", "Level +8.", "trusted", "retain"),
    ("6 6 6", "6 6", "trusted", "retain"),
    ("Bay 12.", "Bay 12.", "unknown", "retain"),
    ("Close\nthe hatch.", "Close the hatch.", "trusted", "replace"),
])
def test_complete_item_and_numeric_multiplicity_are_preserved(model, backend, trust, action):
    decision = choose_hybrid_text(model, backend, trust)
    assert decision.action == action
    assert decision.text == (backend if action == "replace" else model)


def test_invalid_geometry_never_substitutes_even_agreeing_text():
    result = choose_hybrid_text("A 24", "A 24", "trusted", geometry_valid=False)
    assert result.action == "retain"


def test_untrusted_layer_neither_certifies_agreement_nor_rejects_disagreement(tmp_path):
    source = make_text_pdf(tmp_path / "hidden.pdf", ["Incorrect 999 layer."], mode="invisible")
    analysis = analyze_pdf(source)
    settings = ValidationSettings(minimum_markdown_bytes=1)
    for index, text in enumerate(["Incorrect 999 layer.", "Correct visible transcription 24."]):
        markdown = tmp_path / f"{index}.md"
        markdown.write_text(text)
        report = validate_markdown(source, markdown, EngineName.PYMUPDF, analysis, settings)
        assert report.status is QualityStatus.WARN
        assert report.native_token_recall is None
        assert report.content_accuracy == "unverified"
        assert report.fallback_recommended is False


def test_legitimate_repeated_values_are_not_a_decoder_loop(tmp_path):
    lines = ["Daily readings", "Every row is a separate observation."] + ["7"] * 24
    source = make_text_pdf(tmp_path / "repeated.pdf", lines)
    analysis = analyze_pdf(source)
    markdown = tmp_path / "output.md"
    markdown.write_text("\n\n".join(lines))
    settings = ValidationSettings(minimum_markdown_bytes=1)
    report = validate_markdown(source, markdown, EngineName.PYMUPDF, analysis, settings)
    assert report.repeated_short_line_count == 24
    assert report.status is QualityStatus.PASS
    assert report.content_accuracy == "unverified"
    markdown.write_text(markdown.read_text() + "\n\n7")
    excess = validate_markdown(source, markdown, EngineName.PYMUPDF, analysis, settings)
    assert excess.status is QualityStatus.FAIL
    assert any("supported source contains 24" in error for error in excess.errors)
