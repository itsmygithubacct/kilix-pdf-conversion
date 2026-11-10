from __future__ import annotations

import stat

import pytest

Image = pytest.importorskip("PIL.Image")
pytest.importorskip("numpy")

from kilix_pdf_conversion.engines.base import EngineUnavailable  # noqa: E402
from kilix_pdf_conversion.ocr import backends  # noqa: E402
from kilix_pdf_conversion.ocr.backends import (  # noqa: E402
    OcrFailed,
    RapidOcrBackend,
    TesseractBackend,
    _paragraphs,
)

FAKE_TESSERACT = """#!/bin/sh
case "$1" in
  --version) echo "tesseract 5.5.0"; echo " leptonica-1.84.1"; exit 0 ;;
  --list-langs) echo 'List of available languages in "/fake/" (2):'; echo eng; echo osd; exit 0 ;;
esac
cat > "$FAKE_DIR/input.png"
echo "$@" > "$FAKE_DIR/args"
echo "$OMP_THREAD_LIMIT" > "$FAKE_DIR/threads"
if [ -f "$FAKE_DIR/fail" ]; then echo "Error: page could not be read" >&2; exit 1; fi
if [ -f "$FAKE_DIR/slow" ]; then sleep 5; fi
printf 'first line\\nsecond line\\n\\n  \\nnext paragraph\\n\\f'
"""


@pytest.fixture
def fake_tesseract(tmp_path, monkeypatch):
    binary = tmp_path / "tesseract"
    binary.write_text(FAKE_TESSERACT)
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("FAKE_DIR", str(tmp_path))
    return binary


def test_paragraphs_split_on_blank_lines_and_form_feeds() -> None:
    assert _paragraphs("a\nb\n\n \n c\fd\n") == ("a\nb", " c", "d")
    assert _paragraphs("\f\n") == ()


def test_tesseract_check_reports_version_and_languages(fake_tesseract) -> None:
    backend = TesseractBackend(str(fake_tesseract), "eng", 3, 10)
    info = backend.check()
    assert info["version"] == "5.5.0"
    assert info["languages"] == ["eng", "osd"]


def test_tesseract_missing_language_names_the_debian_package(fake_tesseract) -> None:
    backend = TesseractBackend(str(fake_tesseract), "eng+deu", 1, 10)
    with pytest.raises(EngineUnavailable, match="tesseract-ocr-deu"):
        backend.check()


def test_tesseract_missing_binary_names_the_debian_package(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("KILIX_OCR_TESSERACT", raising=False)
    monkeypatch.setattr(backends.shutil, "which", lambda _name: None)
    with pytest.raises(EngineUnavailable, match=r"Debian: tesseract-ocr\)"):
        TesseractBackend(None, "eng", 1, 10).check()
    with pytest.raises(EngineUnavailable, match="not installed"):
        TesseractBackend(str(tmp_path / "absent"), "eng", 1, 10).check()


def test_tesseract_binary_can_come_from_the_environment(fake_tesseract, monkeypatch) -> None:
    monkeypatch.setenv("KILIX_OCR_TESSERACT", str(fake_tesseract))
    assert TesseractBackend(None, "eng", 1, 10).binary == str(fake_tesseract)


def test_tesseract_rejects_unsafe_language_codes() -> None:
    with pytest.raises(ValueError, match="language"):
        TesseractBackend("tesseract", "eng --psm 0", 1, 10)


def test_tesseract_read_passes_page_and_settings(fake_tesseract, tmp_path) -> None:
    backend = TesseractBackend(str(fake_tesseract), "eng", 3, 10)
    page = Image.new("RGB", (200, 100), "white")
    assert backend.read(page, 0.0, 300) == ("first line\nsecond line", "next paragraph")
    assert (tmp_path / "args").read_text().split() == [
        "stdin", "stdout", "--psm", "3", "-l", "eng", "--dpi", "300"
    ]
    assert (tmp_path / "threads").read_text().strip() == "3"
    with Image.open(tmp_path / "input.png") as sent:
        assert sent.size == (200, 100)
        assert round(sent.info["dpi"][0]) == 300


def test_tesseract_levels_a_skewed_page_before_reading(fake_tesseract, tmp_path) -> None:
    backend = TesseractBackend(str(fake_tesseract), "eng", 1, 10)
    backend.read(Image.new("RGB", (400, 200), "white"), 5.0, None)
    with Image.open(tmp_path / "input.png") as sent:
        assert sent.size != (400, 200)
    assert "--dpi" not in (tmp_path / "args").read_text()


def test_tesseract_failure_and_timeout_are_ocr_failures(fake_tesseract, tmp_path) -> None:
    page = Image.new("RGB", (50, 50), "white")
    (tmp_path / "fail").touch()
    with pytest.raises(OcrFailed, match="page could not be read"):
        TesseractBackend(str(fake_tesseract), "eng", 1, 10).read(page, 0.0, None)
    (tmp_path / "fail").unlink()
    (tmp_path / "slow").touch()
    with pytest.raises(OcrFailed, match="exceeded 0.5 s"):
        TesseractBackend(str(fake_tesseract), "eng", 1, 0.5).read(page, 0.0, None)


def test_rapidocr_without_models_is_unavailable(tmp_path) -> None:
    pytest.importorskip("rapidocr")
    pytest.importorskip("onnxruntime")
    with pytest.raises(EngineUnavailable, match="not installed: pp-ocrv6-small"):
        RapidOcrBackend(tmp_path, 1).check()


def test_rapidocr_version_is_pinned(tmp_path, monkeypatch) -> None:
    pytest.importorskip("rapidocr")
    pytest.importorskip("onnxruntime")
    monkeypatch.setattr(backends, "version", lambda name: "9.9.9")
    with pytest.raises(EngineUnavailable, match="requires rapidocr==3.10.0, found 9.9.9"):
        RapidOcrBackend(tmp_path, 1).check()


def test_download_attempts_are_refused() -> None:
    with pytest.raises(OcrFailed, match="attempted a download"):
        backends._refuse_download("https://example.invalid/model.onnx")
