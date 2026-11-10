"""Reading order for detected text boxes, and Markdown escaping of OCR text.

RapidOCR returns one box per run of text with no reading order. Boxes are
levelled by their median angle, then cut recursively: first at a vertical
gutter with wide text on both sides (columns), otherwise at the widest
horizontal break (titles, figures, paragraphs). Each leaf is read row by row.
A side of a gutter counts as a column only when it is wide and its typical
line is long; short cells side by side are a table and stay in row order.
"""
from __future__ import annotations

import math
import re
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

COLUMN_LINES = 8.0   # a column must be at least this many line heights wide
GUTTER_LINES = 1.0   # a gutter must be at least this many line heights wide
BREAK_LINES = 0.5    # a horizontal break must be at least this many line heights tall
LINE_LENGTH_LINES = 4.0  # a column's median line must be at least this many line heights long

Box = Sequence[Sequence[float]]


@dataclass(frozen=True)
class _Item:
    x0: float
    x1: float
    y0: float
    y1: float
    text: str


def _level(boxes: Sequence[Box], texts: Sequence[str]) -> list[_Item]:
    angles = [math.atan2(b[1][1] - b[0][1], b[1][0] - b[0][0]) for b in boxes]
    angle = -statistics.median(angles)
    ca, sa = math.cos(angle), math.sin(angle)
    items = []
    for box, text in zip(boxes, texts, strict=True):
        points = [(x * ca - y * sa, x * sa + y * ca) for x, y in box]
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        items.append(_Item(min(xs), max(xs), min(ys), max(ys), text))
    return items


def _gaps(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Empty stretches between the union of the intervals."""
    spans = sorted(intervals)
    gaps, end = [], spans[0][1]
    for a, b in spans[1:]:
        if a > end:
            gaps.append((end, a))
        end = max(end, b)
    return gaps


def _rows(items: list[_Item]) -> list[str]:
    rows: list[list] = []
    for item in sorted(items, key=lambda i: (i.y0 + i.y1) / 2):
        if rows:
            top, bottom, cells = rows[-1]
            overlap = min(item.y1, bottom) - max(item.y0, top)
            if overlap > 0.5 * min(item.y1 - item.y0, bottom - top):
                cells.append(item)
                rows[-1] = [min(top, item.y0), max(bottom, item.y1), cells]
                continue
        rows.append([item.y0, item.y1, [item]])
    return [" ".join(c.text for c in sorted(cells, key=lambda c: c.x0)) for _, _, cells in rows]


def _width(items: list[_Item]) -> float:
    return max(i.x1 for i in items) - min(i.x0 for i in items)


def _is_column(items: list[_Item], min_column: float, min_line: float) -> bool:
    return (bool(items) and _width(items) >= min_column
            and statistics.median(i.x1 - i.x0 for i in items) >= min_line)


def _cut(items: list[_Item], limits: tuple[float, ...], out: list[list[str]]) -> None:
    min_column, min_gutter, min_break, min_line = limits
    if len(items) > 1:
        best = None
        for a, b in _gaps([(i.x0, i.x1) for i in items]):
            if b - a < min_gutter:
                continue
            left = [i for i in items if i.x1 <= a]
            right = [i for i in items if i.x0 >= b]
            if (_is_column(left, min_column, min_line)
                    and _is_column(right, min_column, min_line)
                    and (best is None or b - a > best[0])):
                best = (b - a, left, right)
        if best is not None:
            _cut(best[1], limits, out)
            _cut(best[2], limits, out)
            return
        breaks = [
            (b - a, a, b)
            for a, b in _gaps([(i.y0, i.y1) for i in items])
            if b - a >= min_break
        ]
        if breaks:
            _, a, b = max(breaks)
            _cut([i for i in items if i.y1 <= a], limits, out)
            _cut([i for i in items if i.y0 >= b], limits, out)
            return
    out.append(_rows(items))


def order_blocks(boxes: Sequence[Box], texts: Sequence[str]) -> list[list[str]]:
    """Blocks of text lines in reading order, from four-point boxes."""
    pairs = [(b, t) for b, t in zip(boxes, texts, strict=True) if t and t.strip()]
    if not pairs:
        return []
    items = _level([b for b, _ in pairs], [t for _, t in pairs])
    height = statistics.median(i.y1 - i.y0 for i in items)
    height = max(height, 1.0)
    out: list[list[str]] = []
    limits = (COLUMN_LINES * height, GUTTER_LINES * height, BREAK_LINES * height,
              LINE_LENGTH_LINES * height)
    _cut(items, limits, out)
    return [block for block in out if block]


_INLINE_SPECIAL = re.compile(r"([\\`*_\[\]<>#|!&~])")
_BLOCK_START = re.compile(r"^(\s*)([-+=]+|\d+[.)])(?=\s|$)")


def markdown_escape_line(line: str) -> str:
    """Make a line of OCR text read literally in CommonMark.

    Every character that can start inline markup is backslash-escaped, and a
    leading list, setext or ordered-list marker is neutralized. The escaped
    text normalizes to the same search tokens as the original.
    """
    escaped = _INLINE_SPECIAL.sub(r"\\\1", line.rstrip())
    match = _BLOCK_START.match(escaped)
    if match:
        marker = match.group(2)
        if marker[-1] in ".)":
            marker = marker[:-1] + "\\" + marker[-1]
        else:
            marker = "\\" + marker
        escaped = match.group(1) + marker + escaped[match.end():]
    return escaped.lstrip() if escaped.startswith("    ") else escaped
