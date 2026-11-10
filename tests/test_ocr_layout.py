from __future__ import annotations

import math

import pytest

from kilix_pdf_conversion.ocr.layout import markdown_escape_line, order_blocks

LINE = 30.0


def box(x: float, y: float, width: float, height: float = LINE * 0.8, angle: float = 0.0):
    """A four-point box: top-left, top-right, bottom-right, bottom-left."""
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    corners = [(0, 0), (width, 0), (width, height), (0, height)]
    return [[x + px * c - py * s, y + px * s + py * c] for px, py in corners]


def column(x: float, y: float, name: str, lines: int, width: float = 500.0):
    return [(box(x, y + LINE * k, width), f"{name}{k}") for k in range(lines)]


def flat(blocks):
    return [line for block in blocks for line in block]


def test_two_columns_are_read_left_column_first() -> None:
    items = column(100, 100, "L", 10) + column(700, 100, "R", 10)
    items.reverse()
    lines = flat(order_blocks([b for b, _ in items], [t for _, t in items]))
    assert lines == [f"L{k}" for k in range(10)] + [f"R{k}" for k in range(10)]


def test_title_above_columns_comes_first() -> None:
    items = [(box(100, 40, 1100), "Title")]
    items += column(100, 100, "L", 8) + column(700, 100, "R", 8)
    blocks = order_blocks([b for b, _ in items], [t for _, t in items])
    lines = flat(blocks)
    assert lines[0] == "Title"
    assert lines.index("L7") < lines.index("R0")


def test_boxes_on_one_row_are_joined_left_to_right() -> None:
    items = [(box(400, 100, 120), "world"), (box(100, 102, 250), "hello"),
             (box(100, 140, 250), "next")]
    lines = flat(order_blocks([b for b, _ in items], [t for _, t in items]))
    assert lines == ["hello world", "next"]


def test_narrow_table_cells_stay_in_row_order() -> None:
    items = []
    for row in range(6):
        for col in range(4):
            items.append((box(100 + col * 140, 100 + row * LINE, 80), f"r{row}c{col}"))
    lines = flat(order_blocks([b for b, _ in items], [t for _, t in items]))
    assert lines[0] == "r0c0 r0c1 r0c2 r0c3"
    assert lines[-1] == "r5c0 r5c1 r5c2 r5c3"


def test_a_tall_break_starts_a_new_block() -> None:
    items = column(100, 100, "A", 3) + column(100, 100 + LINE * 3 + 2 * LINE, "B", 3)
    blocks = order_blocks([b for b, _ in items], [t for _, t in items])
    assert blocks == [["A0", "A1", "A2"], ["B0", "B1", "B2"]]


def test_skewed_columns_are_levelled_before_ordering() -> None:
    angle = 4.0
    items = []
    for name, x0 in (("L", 100), ("R", 700)):
        for k in range(8):
            x, y = x0, 100 + LINE * k
            r = math.radians(angle)
            items.append((box(x * math.cos(r) - y * math.sin(r),
                              x * math.sin(r) + y * math.cos(r), 500, angle=angle),
                          f"{name}{k}"))
    lines = flat(order_blocks([b for b, _ in items], [t for _, t in items]))
    assert lines == [f"L{k}" for k in range(8)] + [f"R{k}" for k in range(8)]


def test_empty_texts_are_dropped_and_no_boxes_give_no_blocks() -> None:
    assert order_blocks([], []) == []
    assert order_blocks([box(0, 0, 10)], ["  "]) == []
    with pytest.raises(ValueError):
        order_blocks([box(0, 0, 10)], [])


@pytest.mark.parametrize(
    "line, expected",
    [
        ("plain words", "plain words"),
        ("a*b_c`d", "a\\*b\\_c\\`d"),
        ("# not a heading", "\\# not a heading"),
        ("- not a bullet", "\\- not a bullet"),
        ("+ nor this", "\\+ nor this"),
        ("===", "\\==="),
        ("3. not a list", "3\\. not a list"),
        ("12) nor this", "12\\) nor this"),
        ("<b>tag</b> & [link](x) | ~ !", "\\<b\\>tag\\</b\\> \\& \\[link\\](x) \\| \\~ \\!"),
        ("      indented code", "indented code"),
        ("trailing   ", "trailing"),
        ("3.14 is a number", "3.14 is a number"),
    ],
)
def test_markdown_escape_line(line, expected) -> None:
    assert markdown_escape_line(line) == expected
