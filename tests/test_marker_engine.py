from __future__ import annotations

import pytest

from kilix_pdf_conversion.engines.marker_engine import _asset_destination


def test_marker_asset_destination_accepts_confined_nested_path(tmp_path) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()

    assert _asset_destination(assets, "figures/page-1.png") == (
        assets / "figures" / "page-1.png"
    )


@pytest.mark.parametrize(
    "name",
    ["../outside.png", "/tmp/outside.png", "nested/../../outside.png", "a\\b.png"],
)
def test_marker_asset_destination_rejects_escape_paths(tmp_path, name) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()

    with pytest.raises(ValueError, match="unsafe|escapes"):
        _asset_destination(assets, name)
