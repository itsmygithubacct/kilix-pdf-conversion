"""Measure a page, choose an engine, read it, and say what happened."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from ..config import OCRSettings
from ..engines.base import EngineUnavailable
from .backends import OcrFailed, RapidOcrBackend, TesseractBackend
from .features import measure
from .policy import RAPIDOCR, TESSERACT, RouteDecision, decide

ENGINES = (TESSERACT, RAPIDOCR)


@dataclass(frozen=True)
class PageReading:
    paragraphs: tuple[str, ...]
    engine: str                 # the engine that produced the text
    decision: RouteDecision     # what the router chose and why
    fallback: str               # empty, or why the chosen engine was not used
    seconds: float

    @property
    def text(self) -> str:
        return "\n\n".join(self.paragraphs) + ("\n" if self.paragraphs else "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "chosen": self.decision.engine,
            "reasons": list(self.decision.reasons),
            "fallback": self.fallback or None,
            "seconds": round(self.seconds, 3),
            "characters": sum(len(p) for p in self.paragraphs),
            "features": self.decision.features.to_dict(),
        }


class OcrReader:
    """Holds both backends; each loads on first use."""

    def __init__(self, settings: OCRSettings) -> None:
        self.settings = settings
        self.backends = {
            TESSERACT: TesseractBackend(None, settings.language, settings.threads,
                                        settings.page_timeout),
            RAPIDOCR: RapidOcrBackend(settings.model_directory, settings.threads),
        }
        self._status: dict[str, dict] | None = None

    def availability(self) -> dict[str, dict]:
        """Per engine: available, plus version details or the reason it is not."""
        if self._status is None:
            status = {}
            for name, backend in self.backends.items():
                try:
                    status[name] = {"available": True, **backend.check()}
                except EngineUnavailable as error:
                    status[name] = {"available": False, "error": str(error)}
            self._status = status
        return self._status

    def available(self) -> tuple[str, ...]:
        return tuple(name for name, item in self.availability().items() if item["available"])

    def route(self, image) -> RouteDecision:
        return decide(measure(image))

    def read(self, image, *, dpi: int | None = None, engine: str | None = None) -> PageReading:
        """Read with the routed engine, or the one named by engine or settings.

        In auto mode an unavailable or failing first choice falls back to the
        other engine and the reading says so. A named engine never falls back.
        """
        started = time.monotonic()
        mode = engine or self.settings.engine
        if mode not in ("auto", *ENGINES):
            raise ValueError(f"unknown OCR engine {mode!r}")
        decision = self.route(image)
        available = self.available()
        if mode != "auto":
            if mode not in available:
                raise EngineUnavailable(self.availability()[mode]["error"])
            order = [mode]
        else:
            order = [decision.engine] + [e for e in ENGINES if e != decision.engine]
            order = [e for e in order if e in available]
            if not order:
                raise EngineUnavailable(
                    "no OCR engine is available: "
                    + "; ".join(item["error"] for item in self.availability().values())
                )
        notes = []
        if mode == "auto" and order[0] != decision.engine:
            notes.append(f"{decision.engine} unavailable: "
                         f"{self.availability()[decision.engine]['error']}")
        for name in order:
            try:
                if name == TESSERACT:
                    paragraphs = self.backends[name].read(
                        image, decision.features.skew_degrees, dpi)
                else:
                    paragraphs = self.backends[name].read(image)
            except OcrFailed as error:
                if mode != "auto":
                    raise
                notes.append(str(error))
                continue
            return PageReading(paragraphs, name, decision, "; ".join(notes),
                               time.monotonic() - started)
        raise OcrFailed("; ".join(notes))

    def close(self) -> None:
        self.backends[RAPIDOCR].close()
