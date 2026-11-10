from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("numpy")
Image = pytest.importorskip("PIL.Image")
ImageDraw = pytest.importorskip("PIL.ImageDraw")
ImageFont = pytest.importorskip("PIL.ImageFont")

from kilix_pdf_conversion.ocr.features import measure  # noqa: E402

WORDS = (
    "the quick brown fox jumps over a lazy dog while seven bright yellow "
    "kites drift above the harbour and nobody counts them twice"
).split()
FONTS = Path("/usr/share/fonts/truetype/dejavu")


def _font(size: int, mono: bool = False):
    path = FONTS / ("DejaVuSansMono.ttf" if mono else "DejaVuSans.ttf")
    if path.is_file():
        return ImageFont.truetype(str(path), size)
    if mono:
        pytest.skip("DejaVu Sans Mono is not installed")
    return ImageFont.load_default(size=size)


def _line(index: int, count: int) -> str:
    return " ".join(WORDS[(index * 3 + k) % len(WORDS)] for k in range(count))


def page(
    *,
    size=(1700, 2200),
    columns: int = 1,
    lines: int = 40,
    font_size: int = 26,
    mono: bool = False,
    ink=(0, 0, 0),
    ground=(255, 255, 255),
    figure: bool = False,
):
    image = Image.new("RGB", size, ground)
    draw = ImageDraw.Draw(image)
    font = _font(font_size, mono)
    margin = 120
    gutter = 90
    width = (size[0] - 2 * margin - (columns - 1) * gutter) // columns
    words_per_line = max(2, width // (font_size * 3))
    step = int(font_size * 1.5)
    y0 = margin
    if figure:
        draw.rectangle((margin, margin, size[0] - margin, margin + 900), outline=ink, width=6)
        for k in range(12):
            draw.line((margin + 40, margin + 60 + 60 * k, size[0] - margin - 40,
                       margin + 820 - 50 * k), fill=ink, width=5)
        y0 = margin + 960
    for column in range(columns):
        x = margin + column * (width + gutter)
        for index in range(lines):
            y = y0 + index * step
            if y + step > size[1] - margin:
                break
            draw.text((x, y), _line(index + 7 * column, words_per_line), font=font, fill=ink)
    return image


def test_blank_and_uniform_pages_do_not_raise() -> None:
    for colour in ((255, 255, 255), (0, 0, 0), (128, 40, 200)):
        features = measure(Image.new("RGB", (800, 600), colour))
        assert features.line_count == 0
        assert features.column_count == 1


def test_clean_text_page() -> None:
    features = measure(page())
    assert not features.dark_background
    assert features.colour_fraction < 0.01
    assert features.line_count >= 30
    assert 15 <= features.line_height <= 45
    assert features.contrast > 150
    assert abs(features.skew_degrees) < 0.3
    assert features.column_count == 1
    assert features.tall_block_fraction < 0.1


def test_dark_and_coloured_pages_are_recognised() -> None:
    assert measure(page(ink=(230, 230, 230), ground=(20, 20, 30))).dark_background
    coloured = measure(page(ground=(40, 120, 220), ink=(255, 255, 0)))
    assert coloured.colour_fraction > 0.5


@pytest.mark.parametrize("angle", [-6.0, 3.0])
def test_skew_is_measured(angle) -> None:
    rotated = page().rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=(255,) * 3)
    measured = measure(rotated).skew_degrees
    assert abs(abs(measured) - abs(angle)) < 0.5


@pytest.mark.parametrize("columns", [2, 3])
def test_columns_are_counted(columns) -> None:
    assert measure(page(columns=columns, font_size=22)).column_count == columns


def test_figure_sized_block_is_measured() -> None:
    assert measure(page(figure=True, lines=25)).tall_block_fraction >= 0.33


def test_monospaced_text_shows_a_character_grid() -> None:
    proportional = measure(page()).grid_strength
    monospaced = measure(page(mono=True)).grid_strength
    assert monospaced > 0.38 > proportional


def test_large_pages_are_measured_at_reduced_size_but_reported_at_full_size() -> None:
    features = measure(page(size=(3400, 4400), font_size=52))
    assert (features.width, features.height) == (3400, 4400)
    assert 30 <= features.line_height <= 90
