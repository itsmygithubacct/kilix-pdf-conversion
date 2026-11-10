from __future__ import annotations

from dataclasses import replace

import pytest

pytest.importorskip("numpy")
pytest.importorskip("PIL")

from kilix_pdf_conversion.ocr.features import PageFeatures  # noqa: E402
from kilix_pdf_conversion.ocr.policy import (  # noqa: E402
    RAPIDOCR,
    ROUTER_POLICY_VERSION,
    TESSERACT,
    decide,
)

CLEAN = PageFeatures(
    width=1700,
    height=2200,
    dark_background=False,
    colour_fraction=0.0,
    contrast=200.0,
    ground_spread=5.0,
    ink_fraction=0.06,
    skew_degrees=0.0,
    line_count=40,
    line_height=30.0,
    sharpness=1.1,
    grid_strength=0.1,
    column_count=1,
    tall_block_fraction=0.0,
)


def test_clean_page_without_a_figure_goes_to_rapidocr() -> None:
    decision = decide(CLEAN)
    assert decision.engine == RAPIDOCR
    assert decision.reasons == ("clean page without a figure-sized block",)


def test_clean_page_with_a_figure_goes_to_tesseract() -> None:
    decision = decide(replace(CLEAN, tall_block_fraction=0.4))
    assert decision.engine == TESSERACT
    assert decision.reasons[0] == "clean upright page"
    assert "40% of inked rows" in decision.reasons[1]


@pytest.mark.parametrize(
    "change, reason",
    [
        ({"dark_background": True}, "dark background"),
        ({"colour_fraction": 0.5}, "coloured"),
        ({"ground_spread": 120.0}, "uneven ground"),
        ({"contrast": 40.0}, "faint"),
        ({"sharpness": 0.4}, "blurred"),
        ({"skew_degrees": -11.0}, "skewed -11.0 degrees"),
        ({"line_height": 9.0}, "small text"),
        ({"grid_strength": 0.6}, "monospaced grid"),
        ({"line_count": 3}, "few text lines"),
    ],
)
def test_any_reason_against_tesseract_keeps_rapidocr_even_with_a_figure(change, reason) -> None:
    decision = decide(replace(CLEAN, tall_block_fraction=0.5, **change))
    assert decision.engine == RAPIDOCR
    assert any(reason in item for item in decision.reasons)


def test_a_page_without_text_lines_says_so() -> None:
    assert decide(replace(CLEAN, line_count=0, contrast=0.0)).reasons == ("no text lines found",)


def test_every_reason_against_is_reported() -> None:
    decision = decide(replace(CLEAN, dark_background=True, sharpness=0.2, line_count=2))
    assert len(decision.reasons) == 3


def test_decision_record_names_the_policy_version() -> None:
    record = decide(CLEAN).to_dict()
    assert record["policy_version"] == ROUTER_POLICY_VERSION
    assert record["features"]["line_count"] == 40


def test_workflow_fingerprint_uses_the_current_router_policy_version() -> None:
    from kilix_pdf_conversion.workflow import OCR_ROUTER_POLICY_VERSION

    assert OCR_ROUTER_POLICY_VERSION == ROUTER_POLICY_VERSION
