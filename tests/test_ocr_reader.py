from __future__ import annotations

from dataclasses import replace

import pytest

Image = pytest.importorskip("PIL.Image")
pytest.importorskip("numpy")

from kilix_pdf_conversion.config import OCRSettings  # noqa: E402
from kilix_pdf_conversion.engines.base import EngineUnavailable  # noqa: E402
from kilix_pdf_conversion.ocr.backends import OcrFailed  # noqa: E402
from kilix_pdf_conversion.ocr.policy import RAPIDOCR, TESSERACT, RouteDecision  # noqa: E402
from kilix_pdf_conversion.ocr.reader import OcrReader  # noqa: E402

from .test_ocr_policy import CLEAN  # noqa: E402


class FakeBackend:
    def __init__(self, name: str, *, available: bool = True, fails: bool = False) -> None:
        self.name = name
        self.available = available
        self.fails = fails
        self.calls: list[tuple] = []

    def check(self) -> dict:
        if not self.available:
            raise EngineUnavailable(f"{self.name} is not installed")
        return {"version": "1.0"}

    def read(self, image, *args) -> tuple[str, ...]:
        self.calls.append(args)
        if self.fails:
            raise OcrFailed(f"{self.name} failed")
        return (f"text from {self.name}",)

    def close(self) -> None:
        pass


def reader(chosen: str = RAPIDOCR, engine: str = "auto", **backends) -> OcrReader:
    instance = OcrReader(OCRSettings(engine=engine))
    instance.backends = {
        TESSERACT: backends.get(TESSERACT, FakeBackend(TESSERACT)),
        RAPIDOCR: backends.get(RAPIDOCR, FakeBackend(RAPIDOCR)),
    }
    features = replace(CLEAN, skew_degrees=1.5)
    instance.route = lambda _image: RouteDecision(chosen, ("because",), features)
    return instance


PAGE = Image.new("RGB", (10, 10), "white")


def test_auto_uses_the_routed_engine() -> None:
    tesseract = FakeBackend(TESSERACT)
    reading = reader(TESSERACT, **{TESSERACT: tesseract}).read(PAGE, dpi=300)
    assert reading.engine == TESSERACT
    assert reading.paragraphs == ("text from tesseract",)
    assert reading.text == "text from tesseract\n"
    assert not reading.fallback
    assert tesseract.calls == [(1.5, 300)]


def test_auto_falls_back_when_the_choice_is_not_installed() -> None:
    reading = reader(TESSERACT, **{TESSERACT: FakeBackend(TESSERACT, available=False)}).read(PAGE)
    assert reading.engine == RAPIDOCR
    assert reading.decision.engine == TESSERACT
    assert "tesseract unavailable: tesseract is not installed" in reading.fallback


def test_auto_falls_back_when_the_choice_fails() -> None:
    reading = reader(RAPIDOCR, **{RAPIDOCR: FakeBackend(RAPIDOCR, fails=True)}).read(PAGE)
    assert reading.engine == TESSERACT
    assert reading.fallback == "rapidocr failed"
    record = reading.to_dict()
    assert record["chosen"] == RAPIDOCR and record["engine"] == TESSERACT
    assert record["reasons"] == ["because"]


def test_auto_fails_when_both_engines_fail() -> None:
    broken = reader(**{TESSERACT: FakeBackend(TESSERACT, fails=True),
                       RAPIDOCR: FakeBackend(RAPIDOCR, fails=True)})
    with pytest.raises(OcrFailed, match="rapidocr failed; tesseract failed"):
        broken.read(PAGE)


def test_nothing_installed_is_unavailable() -> None:
    empty = reader(**{TESSERACT: FakeBackend(TESSERACT, available=False),
                      RAPIDOCR: FakeBackend(RAPIDOCR, available=False)})
    assert empty.available() == ()
    with pytest.raises(EngineUnavailable, match="no OCR engine is available"):
        empty.read(PAGE)


def test_a_named_engine_never_falls_back() -> None:
    named = reader(RAPIDOCR, engine=TESSERACT,
                   **{TESSERACT: FakeBackend(TESSERACT, fails=True)})
    with pytest.raises(OcrFailed, match="tesseract failed"):
        named.read(PAGE)
    missing = reader(RAPIDOCR, **{TESSERACT: FakeBackend(TESSERACT, available=False)})
    with pytest.raises(EngineUnavailable, match="tesseract is not installed"):
        missing.read(PAGE, engine=TESSERACT)
    assert reader(TESSERACT).read(PAGE, engine=RAPIDOCR).engine == RAPIDOCR


def test_unknown_engine_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown OCR engine"):
        reader().read(PAGE, engine="paddle")


def test_availability_is_checked_once() -> None:
    instance = reader()
    calls = []
    original = instance.backends[TESSERACT].check
    instance.backends[TESSERACT].check = lambda: calls.append(1) or original()
    instance.availability()
    instance.availability()
    assert calls == [1]
