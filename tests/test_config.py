from __future__ import annotations

import pytest

from kilix_pdf_conversion.config import load_config, with_overrides
from kilix_pdf_conversion.models import Profile


def test_load_config_and_overrides(tmp_path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
[workflow]
profile = "quality"
output_root = "./runs"

[granite]
device = "cpu"
page_batch_size = 2

[marker]
device = "cuda"
""",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.workflow.profile is Profile.QUALITY
    assert config.granite.device == "cpu"
    assert config.granite.page_batch_size == 2
    assert config.marker.device == "cuda"
    overridden = with_overrides(config, profile=Profile.FAST, device="cpu")
    assert overridden.workflow.profile is Profile.FAST
    assert overridden.granite.device == "cpu"
    assert overridden.marker.device == "cpu"


@pytest.mark.parametrize(
    "content, message",
    [
        ("[workflow]\ncopy_source = 1\n", "must be true or false"),
        ("[pymupdf]\ndpi = 12\n", "at least 36"),
        ("[analysis]\nscan_page_ratio = 0.9\n", "must be below"),
        ("[marker]\ndevice = 7\n", "must be auto, cpu, or cuda"),
        ("[workflow]\nunknown = true\n", "unknown option"),
        ("[mystery]\nvalue = true\n", "unknown configuration section"),
    ],
)
def test_invalid_configuration_is_rejected(tmp_path, content, message) -> None:
    path = tmp_path / "invalid.toml"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_config(path)
