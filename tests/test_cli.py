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
