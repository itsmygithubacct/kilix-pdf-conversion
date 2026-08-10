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
