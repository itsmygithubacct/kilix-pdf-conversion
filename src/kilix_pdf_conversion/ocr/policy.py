"""Choose Tesseract or RapidOCR for one page from its measurements alone.

RapidOCR with PP-OCRv6 small is the default. With column-aware reading order it
read characters at least as well as Tesseract on nearly every page measured,
including blurred, skewed, small, dark, coloured and multi-column pages.
Tesseract is chosen only for a clean, upright, light, proportional-type page
that holds a figure-sized non-text block: there its page layout analysis keeps
figure contents out of the body text. docs/OCR.md records the measurements.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .features import PageFeatures

TESSERACT = "tesseract"
RAPIDOCR = "rapidocr"
ROUTER_POLICY_VERSION = 1


@dataclass(frozen=True)
class Thresholds:
    max_colour_fraction: float = 0.20      # above: coloured interface or photo
    max_ground_spread: float = 70.0        # above: photo, gradient or badly lit paper
    min_contrast: float = 70.0             # below: faint ink; block measures unreliable
    min_sharpness: float = 0.70            # below: blurred
    max_skew_degrees: float = 10.0         # above: outside what levelling was tested on
    min_line_height: float = 12.0          # below: text too small for Tesseract
    max_grid_strength: float = 0.38        # above: monospaced (terminal, code)
    min_line_count: int = 8                # below: not a page of text
    min_tall_block_fraction: float = 0.33  # at or above: a figure-sized block


@dataclass(frozen=True)
class RouteDecision:
    engine: str
    reasons: tuple[str, ...]
    features: PageFeatures = field(repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "reasons": list(self.reasons),
            "policy_version": ROUTER_POLICY_VERSION,
            "features": self.features.to_dict(),
        }


DEFAULT_THRESHOLDS = Thresholds()


def decide(f: PageFeatures, t: Thresholds = DEFAULT_THRESHOLDS) -> RouteDecision:
    """Return the engine for a page with these measurements, and why."""
    if f.line_count == 0:
        return RouteDecision(RAPIDOCR, ("no text lines found",), f)
    against = []
    if f.dark_background:
        against.append("dark background")
    if f.colour_fraction > t.max_colour_fraction:
        against.append(f"coloured ({f.colour_fraction:.0%} of pixels)")
    if f.ground_spread > t.max_ground_spread:
        against.append(f"uneven ground (spread {f.ground_spread:.0f})")
    if f.contrast < t.min_contrast:
        against.append(f"faint (contrast {f.contrast:.0f})")
    if f.sharpness < t.min_sharpness:
        against.append(f"blurred (sharpness {f.sharpness:.2f})")
    if abs(f.skew_degrees) > t.max_skew_degrees:
        against.append(f"skewed {f.skew_degrees:+.1f} degrees")
    if f.line_height < t.min_line_height:
        against.append(f"small text (lines {f.line_height:.0f} px tall)")
    if f.grid_strength > t.max_grid_strength:
        against.append(f"monospaced grid (strength {f.grid_strength:.2f})")
    if f.line_count < t.min_line_count:
        against.append(f"few text lines ({f.line_count})")
    if against:
        return RouteDecision(RAPIDOCR, tuple(against), f)
    if f.tall_block_fraction >= t.min_tall_block_fraction:
        return RouteDecision(
            TESSERACT,
            ("clean upright page",
             f"figure-sized block ({f.tall_block_fraction:.0%} of inked rows)"),
            f,
        )
    return RouteDecision(RAPIDOCR, ("clean page without a figure-sized block",), f)
