from __future__ import annotations

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
