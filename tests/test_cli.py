from __future__ import annotations

import json

from kilix_pdf_conversion.cli import main

from .helpers import make_native_pdf


def test_doctor_json(capsys) -> None:
    assert main(["doctor", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["base"]["pymupdf"]["available"]


def test_plan_json(tmp_path, capsys) -> None:
    source = make_native_pdf(tmp_path / "source.pdf")
    assert main(["plan", str(source), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["analysis"]["document_kind"] == "native"
    assert payload["route"]["initial_engines"] == ["pymupdf4llm"]


def test_recommend_json_names_best_program(tmp_path, capsys) -> None:
    source = make_native_pdf(tmp_path / "source.pdf")
    assert main(["recommend", str(source), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    recommendation = payload["recommendation"]
    assert recommendation["recommended_engine"] == "pymupdf4llm"
    assert recommendation["best_available_engine"] == "pymupdf4llm"
    assert recommendation["confidence"] == "high"


def test_interactive_session_can_exit_at_path_prompt(monkeypatch, capsys) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt: "")

    assert main(["interactive"]) == 0
    assert "Kilix PDF Conversion" in capsys.readouterr().out


def test_convert_json_is_not_polluted_by_engine_output(tmp_path, capsys) -> None:
    source = make_native_pdf(tmp_path / "source.pdf")

    assert (
        main(
            [
                "convert",
                str(source),
                "--profile",
                "fast",
                "--output-root",
                str(tmp_path / "output"),
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["canonical_engine"] == "pymupdf4llm"
    assert payload["validation_scope"] == "heuristic_checks"
    assert payload["content_accuracy"] == "unverified"


def test_bare_pdf_path_is_a_desktop_friendly_convert_alias(tmp_path, capsys) -> None:
    source = make_native_pdf(tmp_path / "source.pdf")

    assert (
        main(
            [
                str(source),
                "--profile",
                "fast",
                "--output-root",
                str(tmp_path / "output"),
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] in {"pass", "review"}
    assert payload["canonical_engine"] == "pymupdf4llm"


def test_doctor_reports_both_ocr_engines(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("KILIX_OCR_TESSERACT", str(tmp_path / "no-tesseract"))
    monkeypatch.setenv("KILIX_OCR_MODEL_DIR", str(tmp_path))
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "Tesseract: tesseract is not installed (Debian: tesseract-ocr)" in out
    assert "RapidOCR: " in out


def test_ocr_refuses_pdfs(tmp_path, capsys) -> None:
    import pytest

    pytest.importorskip("PIL")
    source = make_native_pdf(tmp_path / "source.pdf")
    assert main(["ocr", str(source)]) == 2
    assert "use 'kilix-pdf convert'" in capsys.readouterr().err


def test_ocr_route_only_explains_the_choice(tmp_path, capsys) -> None:
    import pytest

    image_module = pytest.importorskip("PIL.Image")
    pytest.importorskip("numpy")
    path = tmp_path / "blank.png"
    image_module.new("RGB", (400, 300), "white").save(path)
    assert main(["ocr", str(path), "--route-only", "--json"]) == 0
    record = json.loads(capsys.readouterr().out)
    assert record["engine"] == "rapidocr"
    assert record["reasons"] == ["no text lines found"]
    assert record["features"]["line_count"] == 0


def test_ocr_reports_an_unreadable_image(tmp_path, capsys) -> None:
    import pytest

    pytest.importorskip("PIL")
    path = tmp_path / "notes.png"
    path.write_text("not an image")
    assert main(["ocr", str(path)]) == 2
    assert "not a readable image" in capsys.readouterr().err


def test_ocr_reads_with_the_named_engine(tmp_path, monkeypatch, capsys) -> None:
    import pytest

    image_module = pytest.importorskip("PIL.Image")
    pytest.importorskip("numpy")
    from kilix_pdf_conversion.ocr import reader as reader_module

    from .test_page_ocr_engine import FakeReader

    seen = []

    class Recording(FakeReader):
        def __init__(self, settings) -> None:
            super().__init__(settings)
            seen.append(settings.engine)

    monkeypatch.setattr(reader_module, "OcrReader", Recording)
    path = tmp_path / "page.png"
    image_module.new("RGB", (400, 300), "white").save(path, dpi=(300, 300))
    assert main(["ocr", str(path), "--engine", "tesseract", "--json"]) == 0
    record = json.loads(capsys.readouterr().out)
    assert seen == ["tesseract"]
    assert record["dpi"] == 300
    assert record["text"].startswith("A deterministic source paragraph")
