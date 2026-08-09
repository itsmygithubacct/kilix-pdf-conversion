from __future__ import annotations

from kilix_pdf_conversion.artifacts import canonical_markdown
from kilix_pdf_conversion.models import EngineName
from kilix_pdf_conversion.util import atomic_write_json, safe_slug, sha256_file


def test_safe_slug_is_portable() -> None:
    assert safe_slug("A Report: Tables & Charts") == "a-report-tables-charts"


def test_atomic_json_and_sha256(tmp_path) -> None:
    path = tmp_path / "data.json"
    atomic_write_json(path, {"b": 2, "a": 1})
    assert path.read_text(encoding="utf-8").startswith('{\n  "a"')
    assert len(sha256_file(path)) == 64


def test_canonical_markdown_rewrites_relative_assets(tmp_path) -> None:
    candidate = tmp_path / "document.md"
    candidate.write_text("![chart](assets/chart.png)\n", encoding="utf-8")
    destination = tmp_path / "canonical.md"
    canonical_markdown(candidate, EngineName.GRANITE_HYBRID, destination)
    assert (
        "conversions/granite-hybrid/assets/chart.png"
        in destination.read_text(encoding="utf-8")
    )
