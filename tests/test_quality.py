from __future__ import annotations

from dataclasses import replace

from kilix_pdf_conversion.config import ValidationSettings
from kilix_pdf_conversion.models import EngineName, QualityStatus
from kilix_pdf_conversion.quality import (
    FIGURE_CAPTION_LINE,
    TABLE_CAPTION_LINE,
    image_reference_metrics,
    markdown_table_metrics,
    repeated_short_line,
    validate_markdown,
)

from .helpers import analysis_stub, make_native_pdf


def test_markdown_table_metrics_counts_valid_blocks() -> None:
    markdown = """
| A | B | C |
|---|---|---|
| 1 | 2 | 3 |

not a table

<table><tr><td>x</td></tr></table>
"""
    assert markdown_table_metrics(markdown) == (2, 3)


def test_repeated_short_line_ignores_blank_lines() -> None:
    value, count = repeated_short_line("text\n\n2\n\n2\n\n2\n")
    assert value == "2"
    assert count == 3


def test_caption_lines_do_not_count_prose_references() -> None:
    markdown = """
The values shown in Table 3 agree with Figure 4.

**Table 3. Measurements**

| A | B |
|---|---|

### Figure 4. Trend
"""
    assert TABLE_CAPTION_LINE.findall(markdown) == ["3"]
    assert FIGURE_CAPTION_LINE.findall(markdown) == ["4"]


def test_image_reference_metrics_checks_local_assets(tmp_path) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "present.png").write_bytes(b"png")
    markdown = (
        "![present](assets/present.png)\n"
        "![missing](assets/missing.png)\n"
        f'<img src="{(assets / "absolute.png").resolve()}">\n'
        "![remote](https://example.test/chart.png)\n"
    )

    assert image_reference_metrics(markdown, tmp_path / "document.md") == (4, 1, 1)


def test_validation_rejects_repetition_and_placeholders(tmp_path) -> None:
    source = make_native_pdf(tmp_path / "source.pdf")
    markdown = tmp_path / "bad.md"
    markdown.write_text(
        "# Test\n\n<!-- image -->\n\n" + "\n\n".join(["2"] * 12),
        encoding="utf-8",
    )
    analysis = analysis_stub(source)
    settings = ValidationSettings(
        minimum_markdown_bytes=10,
        minimum_native_token_recall=0.1,
        maximum_repeated_short_line_count=5,
        fail_on_image_placeholders=True,
    )
    report = validate_markdown(
        source, markdown, EngineName.GRANITE_PURE, analysis, settings
    )
    assert report.status is QualityStatus.FAIL
    assert report.repeated_short_line_count == 12
    assert report.image_placeholder_count == 1
    assert len(report.errors) >= 2


def test_validation_reports_native_recall(tmp_path) -> None:
    source = make_native_pdf(tmp_path / "source.pdf", "alpha beta gamma " * 80)
    markdown = tmp_path / "good.md"
    markdown.write_text("# Title\n\n" + "alpha beta gamma " * 80, encoding="utf-8")
    analysis = replace(
        analysis_stub(source),
        native_text_characters=2000,
    )
    settings = ValidationSettings(
        minimum_markdown_bytes=10,
        minimum_native_token_recall=0.8,
        maximum_repeated_short_line_count=20,
        fail_on_image_placeholders=True,
    )
    report = validate_markdown(
        source, markdown, EngineName.PYMUPDF, analysis, settings
    )
    assert report.native_token_recall is not None
    assert report.native_token_recall > 0.95
    assert report.status is QualityStatus.PASS
