from __future__ import annotations

from dataclasses import replace

import pytest

from kilix_pdf_conversion.artifacts import (
    canonical_markdown,
    copy_source,
    visual_page_numbers,
)
from kilix_pdf_conversion.models import EngineName, PageSignal
from kilix_pdf_conversion.util import (
    atomic_write_json,
    exclusive_lock,
    safe_slug,
    sha256_file,
)

from .helpers import analysis_stub


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


def test_copy_source_verifies_expected_content_hash(tmp_path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"content")
    destination = tmp_path / "bundle" / "source.pdf"

    with pytest.raises(RuntimeError, match="changed after analysis"):
        copy_source(source, destination, expected_sha256="0" * 64)

    assert not destination.exists()
    assert not list(destination.parent.glob("*.part"))


def test_visual_page_cap_is_spread_across_document(tmp_path) -> None:
    pages = tuple(
        PageSignal(
            page_number=number,
            native_characters=0,
            nonspace_characters=0,
            image_count=1,
            drawing_count=0,
            table_count=0,
            max_table_columns=0,
            multi_column=False,
            reliable_text=False,
        )
        for number in range(1, 51)
    )
    analysis = replace(analysis_stub(tmp_path / "source.pdf"), pages=pages)

    selected = visual_page_numbers(analysis, maximum=5)

    assert len(selected) == 5
    assert selected[0] == 1
    assert selected[-1] == 50


def test_conversion_lock_is_reusable_without_removing_lockfile(tmp_path) -> None:
    path = tmp_path / "run.lock"
    with exclusive_lock(path):
        with pytest.raises(RuntimeError, match="already locked"):
            with exclusive_lock(path):
                pass
    with exclusive_lock(path):
        assert path.read_text(encoding="utf-8").strip().isdigit()
