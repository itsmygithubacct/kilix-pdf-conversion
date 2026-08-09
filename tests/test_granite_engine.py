from __future__ import annotations

from kilix_pdf_conversion.engines.granite_engine import _relative_asset_references


def test_relative_asset_references_rewrites_path_and_uri(tmp_path) -> None:
    assets = tmp_path / "output with spaces" / "assets"
    raw_path = assets.resolve().as_posix()
    file_uri = assets.resolve().as_uri()
    markdown = (
        f"![first]({raw_path}/chart.png)\n"
        f"![second]({file_uri}/figure.png)\n"
    )

    portable = _relative_asset_references(markdown, assets)

    assert portable == "![first](assets/chart.png)\n![second](assets/figure.png)\n"
