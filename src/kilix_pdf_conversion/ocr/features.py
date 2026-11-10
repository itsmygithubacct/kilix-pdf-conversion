"""Cheap image measurements that decide which OCR engine suits a page.

Only numpy and Pillow are used and no model runs. Measuring takes about a
tenth to half a second on a page; either OCR engine takes one to three seconds.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from PIL import Image

WORK_LONG_SIDE = 1600   # measure on at most this many pixels along the long side
SKEW_LONG_SIDE = 700    # the skew search runs on a smaller copy still
MAX_SKEW_SEARCH = 12.0  # degrees either way


@dataclass(frozen=True)
class PageFeatures:
    width: int                   # source size, pixels
    height: int
    dark_background: bool        # light text on a dark ground
    colour_fraction: float       # share of pixels that are clearly coloured, 0..1
    contrast: float              # ink level to ground level, 0..255
    ground_spread: float         # 5th-to-95th percentile range of the ground, 0..255
    ink_fraction: float          # share of pixels that are ink, 0..1
    skew_degrees: float          # text line angle; positive is anticlockwise
    line_count: int              # text lines found
    line_height: float           # median text line height, source pixels
    sharpness: float             # strongest edges relative to contrast, about 0..1.5
    grid_strength: float         # depth of the character-pitch repeat; high for monospace
    column_count: int            # columns of running text; tables do not count
    tall_block_fraction: float   # share of inked rows in blocks far taller than a line

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _otsu(gray: np.ndarray) -> int:
    hist = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
    total = hist.sum()
    levels = np.arange(256)
    w0 = np.cumsum(hist)
    w1 = total - w0
    m0 = np.cumsum(hist * levels)
    mean0 = m0 / np.maximum(w0, 1)
    mean1 = (m0[-1] - m0) / np.maximum(w1, 1)
    return int(np.argmax(w0 * w1 * (mean0 - mean1) ** 2))


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Start and end (exclusive) of each run of True in a 1-D mask."""
    padded = np.concatenate(([False], mask, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return list(zip(edges[0::2].tolist(), edges[1::2].tolist(), strict=True))


def _row_profile_score(ink_img: Image.Image, angle: float) -> float:
    rotated = ink_img.rotate(angle, resample=Image.BILINEAR, fillcolor=0)
    rows = np.asarray(rotated, dtype=np.float32).sum(axis=1)
    return float(np.square(np.diff(rows)).sum())


def _skew(ink: np.ndarray) -> float:
    """Text line angle: the rotation that makes the row ink profile sharpest."""
    img = Image.fromarray((ink * 255).astype(np.uint8))
    scale = SKEW_LONG_SIDE / max(img.size)
    if scale < 1:
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))),
                         Image.BILINEAR)
    coarse = np.arange(-MAX_SKEW_SEARCH, MAX_SKEW_SEARCH + 0.01, 1.0)
    scores = [_row_profile_score(img, a) for a in coarse]
    best = float(coarse[int(np.argmax(scores))])
    for step in (0.25, 0.05):
        fine = np.arange(best - 4 * step, best + 4 * step + 1e-9, step)
        scores = [_row_profile_score(img, a) for a in fine]
        best = float(fine[int(np.argmax(scores))])
    # A page without line structure scores flat; do not report noise as skew.
    if max(scores) < 1.15 * _row_profile_score(img, 0.0):
        return 0.0
    return round(-best, 2)


def _grid_strength(ink: np.ndarray, line_height: float) -> float:
    """Depth of the repeat at character pitch in the column ink profile, 0..1.

    Monospaced text puts every glyph on one column grid, so the ink summed down
    each pixel column rises and falls at the character pitch. Proportional text
    averages out across lines. A spectrum is used rather than autocorrelation
    so a pitch that is not a whole number of pixels still shows.
    """
    cols = ink.sum(axis=0).astype(np.float64)
    nonzero = np.flatnonzero(cols)
    if nonzero.size < 64 or line_height <= 0:
        return 0.0
    cols = cols[nonzero[0]:nonzero[-1] + 1]
    n = cols.size
    window = np.hanning(n)
    spectrum = np.abs(np.fft.rfft((cols - cols.mean()) * window))
    # Character pitch lies between about 0.3 and 1.2 line heights.
    lo = max(2, int(n / (1.2 * line_height)))
    hi = min(spectrum.size - 2, int(n / (0.3 * line_height)))
    if hi - lo < 8:
        return 0.0
    amplitude = 2.0 * float(spectrum[lo:hi + 1].max()) / float(window.sum())
    return round(min(1.0, amplitude / float(cols.mean())), 3)


def _column_count(ink: np.ndarray, line_height: float, lines: list[tuple[int, int]]) -> int:
    """Columns of running text: one more than the gutters that split most bands.

    The page is cut into bands of six text lines. In each band a gutter is a
    blank vertical strip, wider than a word space, with text on both sides.
    Strips that leave a column narrower than eight line heights are table cells.
    """
    if len(lines) < 8 or line_height <= 0:
        return 1
    cols_any = np.flatnonzero(ink.any(axis=0))
    x0, x1 = int(cols_any[0]), int(cols_any[-1]) + 1
    span = x1 - x0
    min_gutter = max(6, int(line_height * 1.2))
    band_lines = 6
    counts = []
    for i in range(0, len(lines) - band_lines + 1, band_lines):
        band_runs = lines[i:i + band_lines]
        band = ink[band_runs[0][0]:band_runs[-1][1], x0:x1]
        per_line = np.stack([ink[a:b, x0:x1].any(axis=0) for a, b in band_runs])
        edges = [0]
        for a, b in _runs(band.sum(axis=0) == 0):
            if b - a < min_gutter or a < 0.12 * span or b > 0.88 * span:
                continue
            # At least half the text lines must carry ink on each side.
            if (per_line[:, :a].any(axis=1).mean() >= 0.5
                    and per_line[:, b:].any(axis=1).mean() >= 0.5):
                edges += [a, b]
        edges.append(span)
        widths = [edges[k + 1] - edges[k] for k in range(0, len(edges), 2)]
        counts.append(0 if min(widths) < 8 * line_height else len(widths) - 1)
    if len(counts) < 2:
        return 1
    split = [c for c in counts if c > 0]
    if len(split) / len(counts) < 0.6:
        return 1
    return 1 + int(np.median(split))


def measure(image: Image.Image) -> PageFeatures:
    """Measure one page image. Never raises on blank or uniform input."""
    src_w, src_h = image.size
    rgb = image.convert("RGB")
    scale = min(1.0, WORK_LONG_SIDE / max(src_w, src_h, 1))
    if scale < 1.0:
        rgb = rgb.resize((max(1, int(src_w * scale)), max(1, int(src_h * scale))),
                         Image.LANCZOS)
    arr = np.asarray(rgb).astype(np.int16)
    chroma = arr.max(axis=2) - arr.min(axis=2)
    colour_fraction = float((chroma > 48).mean())
    gray = np.asarray(rgb.convert("L"))

    dark = bool(np.median(gray) < 128)
    g = 255 - gray if dark else gray          # from here on: dark ink on a light ground

    ink = g < _otsu(g)
    ink_fraction = float(ink.mean())
    if ink_fraction in (0.0, 1.0):
        return PageFeatures(src_w, src_h, dark, round(colour_fraction, 4), 0.0, 0.0,
                            ink_fraction, 0.0, 0, 0.0, 0.0, 0.0, 1, 0.0)
    ground = g[~ink]
    contrast = float(np.median(ground)) - float(np.median(g[ink]))
    p5, p95 = np.percentile(ground, [5, 95])

    skew = _skew(ink)
    level = ink
    if abs(skew) >= 0.2:
        level = np.asarray(Image.fromarray((ink * 255).astype(np.uint8)).rotate(
            -skew, resample=Image.BILINEAR, fillcolor=0)) > 127

    rows = level.sum(axis=1)
    inked = rows > max(1, 0.002 * level.shape[1])
    runs = [(a, b) for a, b in _runs(inked) if b - a >= 3]
    heights = np.array([b - a for a, b in runs], dtype=np.float64)
    if heights.size:
        line_h = float(np.median(heights))
        text_runs = [(a, b) for a, b in runs if b - a <= 2.2 * line_h]
        tall = float(sum(b - a for a, b in runs if b - a > 3.5 * line_h) / heights.sum())
    else:
        line_h, text_runs, tall = 0.0, [], 0.0

    gx = np.abs(np.diff(g.astype(np.int16), axis=1))
    sharpness = float(np.percentile(gx, 99.5) / max(contrast, 1.0))

    return PageFeatures(
        width=src_w,
        height=src_h,
        dark_background=dark,
        colour_fraction=round(colour_fraction, 4),
        contrast=round(contrast, 1),
        ground_spread=round(float(p95 - p5), 1),
        ink_fraction=round(ink_fraction, 4),
        skew_degrees=skew,
        line_count=len(text_runs),
        line_height=round(line_h / scale, 1),
        sharpness=round(sharpness, 3),
        grid_strength=_grid_strength(level, line_h),
        column_count=_column_count(level, line_h, text_runs),
        tall_block_fraction=round(tall, 3),
    )
