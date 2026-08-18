from __future__ import annotations

import json

import pytest

from kilix_pdf_conversion.cli import _batch_sources, main

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


def test_batch_pattern_cannot_escape_the_input_directory(tmp_path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    make_native_pdf(tmp_path / "outside.pdf")

    with pytest.raises(ValueError, match="escapes the input directory"):
        _batch_sources(input_dir, "../*.pdf")


def test_batch_refuses_a_symlinked_pdf(tmp_path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    outside = make_native_pdf(tmp_path / "outside.pdf")
    (input_dir / "linked.pdf").symlink_to(outside)

    with pytest.raises(ValueError, match="symlinked batch input"):
        _batch_sources(input_dir, "*.pdf")


def test_batch_returns_only_regular_contained_files(tmp_path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    first = make_native_pdf(input_dir / "first.pdf")
    second = make_native_pdf(input_dir / "second.pdf")
    (input_dir / "not-a-file.pdf").mkdir()

    assert _batch_sources(input_dir, "*.pdf") == (first.resolve(), second.resolve())
