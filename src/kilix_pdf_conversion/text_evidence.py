"""Conservative rendering evidence, not independent transcription accuracy."""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

TEXT_EVIDENCE_POLICY_VERSION = 2


class TextTrust(StrEnum):
    TRUSTED = "trusted"
    SUSPECT = "suspect"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PageTextEvidence:
    page_number: int
    trust: TextTrust
    reference_text: str = ""
    rendered_characters: int = 0
    hidden_characters: int = 0
    reasons: tuple[str, ...] = ()
    image_content_unchecked: bool = False
    width: float = 0.0
    height: float = 0.0

    def summary(self) -> dict:
        return {
            "page_number": self.page_number, "trust": self.trust.value,
            "rendered_characters": self.rendered_characters,
            "hidden_characters": self.hidden_characters,
            "reasons": list(self.reasons),
            "image_content_unchecked": self.image_content_unchecked,
        }


@dataclass(frozen=True)
class SourceTextEvidence:
    pages: tuple[PageTextEvidence, ...]

    @property
    def trust(self) -> TextTrust:
        if any(page.trust is TextTrust.SUSPECT for page in self.pages):
            return TextTrust.SUSPECT
        if not self.pages or any(page.trust is TextTrust.UNKNOWN for page in self.pages):
            return TextTrust.UNKNOWN
        return TextTrust.TRUSTED

    @property
    def reference_pages(self) -> tuple[int, ...]:
        return tuple(p.page_number for p in self.pages if p.trust is TextTrust.TRUSTED)

    @property
    def reference_text(self) -> str:
        return "\n".join(p.reference_text for p in self.pages if p.trust is TextTrust.TRUSTED)

    @property
    def complete_reference(self) -> bool:
        return self.trust is TextTrust.TRUSTED and not any(
            p.image_content_unchecked for p in self.pages
        )

    def summary(self) -> dict:
        return {
            "policy_version": TEXT_EVIDENCE_POLICY_VERSION,
            "trust": self.trust.value,
            "reference_pages": list(self.reference_pages),
            "complete_reference": self.complete_reference,
            "content_accuracy": "unverified",
            "pages": [p.summary() for p in self.pages],
        }


def _finite_box(box) -> bool:
    return len(box) == 4 and all(math.isfinite(v) for v in box) and (
        box[0] < box[2] and box[1] < box[3]
    )


def _overlaps(a, b) -> bool:
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def _inside(box, page) -> bool:
    # Arithmetic tolerance in PDF points; not a visual coverage threshold.
    epsilon = 0.001
    return (box[0] >= page[0] - epsilon and box[1] >= page[1] - epsilon
            and box[2] <= page[2] + epsilon and box[3] <= page[3] + epsilon)


def _has_rendered_contrast(samples: bytes, width: int, height: int, box, rect) -> bool:
    scale_x, scale_y = width / (rect[2] - rect[0]), height / (rect[3] - rect[1])
    x0 = max(0, math.floor((box[0] - rect[0]) * scale_x))
    y0 = max(0, math.floor((box[1] - rect[1]) * scale_y))
    x1 = min(width, math.ceil((box[2] - rect[0]) * scale_x))
    y1 = min(height, math.ceil((box[3] - rect[1]) * scale_y))
    darkest, lightest = 255, 0
    for y in range(y0, y1):
        row = samples[y * width + x0:y * width + x1]
        if row:
            darkest, lightest = min(darkest, min(row)), max(lightest, max(row))
            if darkest < lightest:
                return True
    return False


def inspect_page_text(page) -> PageTextEvidence:
    """Use PDF observations only. Unresolved visibility never becomes trust."""
    import pymupdf

    number = page.number + 1
    reasons: set[str] = set()
    suspect = False
    rendered = hidden = 0
    try:
        rect = tuple(page.rect)
        traces = page.get_texttrace()
        painting = page.get_bboxlog()
        if len(traces) * len(painting) > 1_000_000 or page.rect.width * page.rect.height > 4_000_000:
            return PageTextEvidence(
                number, TextTrust.UNKNOWN, reasons=("visibility_inspection_budget",),
                image_content_unchecked=True, width=page.rect.width, height=page.rect.height,
            )
        images = [box for kind, box, *_ in painting if kind == "fill-image"]
        unsupported_geometry = bool(page.rotation or tuple(page.cropbox_position) != (0, 0))
        if unsupported_geometry:
            reasons.add("unsupported_page_geometry")
        pixmap = None
        samples = b""
        for span in traces:
            text = "".join(chr(char[0]) for char in span["chars"])
            count = sum(not char.isspace() for char in text)
            if not count:
                continue
            box = span["bbox"]
            if "\ufffd" in text or "\x00" in text:
                reasons.add("unmapped_characters")
                suspect = True
            if not _finite_box(box):
                reasons.add("unresolved_text_geometry")
                continue
            # Trace coordinates are unrotated. The rendered page rectangle
            # need not share that coordinate system for rotated/cropped pages.
            if unsupported_geometry:
                reasons.add("unsupported_text_geometry")
                continue
            if not _inside(box, rect):
                reasons.add("invalid_or_offpage_text_geometry")
                suspect = True
                continue
            if span.get("type") == 3 or span.get("opacity") == 0:
                hidden += count
                reasons.add("invisible_text_unverified")
                continue
            if span.get("type") not in {0, 1} or span.get("opacity") != 1:
                reasons.add("unsupported_or_translucent_text")
                continue
            if (tuple(span.get("dir", ())) != (1, 0)
                    or span.get("bidi_lvl", 0)):
                reasons.add("unsupported_text_geometry")
                continue
            if any(_overlaps(box, image) for image in images):
                reasons.add("text_over_image_unverified")
                continue
            # Contrast in a span's rectangle may belong entirely to earlier
            # graphics, including marks in interword spaces. It cannot prove
            # that this text painted visible glyphs on that background.
            if any(
                index < span.get("seqno", -1)
                and item[0] in {"fill-path", "stroke-path", "fill-shade"}
                and _overlaps(box, item[1])
                for index, item in enumerate(painting)
            ):
                reasons.add("background_paint_unverified")
                continue
            # A later drawing may be transparent. Overlap is uncertainty,
            # not a claim that the visible source is corrupt.
            if any(
                index > span.get("seqno", -1)
                and item[0] in {
                    "fill-path", "stroke-path", "fill-image", "fill-shade",
                    "fill-text", "stroke-text",
                }
                and _overlaps(box, item[1])
                for index, item in enumerate(painting)
            ):
                reasons.add("possible_later_occlusion")
                continue
            if pixmap is None:
                pixmap = page.get_pixmap(colorspace=pymupdf.csGRAY, alpha=False)
                samples = pixmap.samples
            if not _has_rendered_contrast(samples, pixmap.width, pixmap.height, box, rect):
                reasons.add("no_rendered_ink_in_text_box")
                suspect = True
                continue
            rendered += count
        if not rendered and not hidden and not reasons:
            reasons.add("no_extracted_text_reference")
        trust = TextTrust.SUSPECT if suspect else TextTrust.UNKNOWN if reasons else TextTrust.TRUSTED
        reference = page.get_text("text", sort=True) if trust is TextTrust.TRUSTED else ""
        if trust is TextTrust.TRUSTED and not reference.strip():
            trust = TextTrust.UNKNOWN
            reasons.add("no_extracted_text_reference")
        return PageTextEvidence(
            number, trust, reference, rendered, hidden, tuple(sorted(reasons)),
            bool(images), page.rect.width, page.rect.height,
        )
    except Exception:
        return PageTextEvidence(number, TextTrust.UNKNOWN, reasons=("visibility_inspection_unavailable",))


def inspect_source_text(source: Path) -> SourceTextEvidence:
    import pymupdf

    try:
        with pymupdf.open(source) as document:
            return SourceTextEvidence(tuple(inspect_page_text(page) for page in document))
    except Exception:
        return SourceTextEvidence(())


@dataclass(frozen=True)
class HybridTextDecision:
    text: str
    action: str
    reason: str
    conflicting_text: bool


def choose_hybrid_text(
    model_text: str, backend_text: str, trust: TextTrust | str, *, geometry_valid: bool = True,
) -> HybridTextDecision:
    """Only equivalent whole items may be replaced; never repair by deletion."""
    original = " ".join(model_text.split())
    proposed = " ".join(backend_text.split())
    conflict = bool(original and proposed and original != proposed)
    if not geometry_valid:
        reason = "invalid_region_geometry"
    elif trust != TextTrust.TRUSTED:
        reason = "source_text_not_trusted"
    elif not proposed or not original:
        reason = "empty_crop_or_model_item"
    elif original != proposed:
        reason = "incomplete_crop" if proposed in original else "conflicting_text"
    else:
        return HybridTextDecision(backend_text, "replace", "supported_equivalent_text", False)
    return HybridTextDecision(model_text, "retain", reason, conflict)
