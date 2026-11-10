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

[ocr]
engine = "tesseract"
dpi = 300
language = "eng+deu"
threads = 2
page_timeout = 30
model_directory = "/srv/ocr-models"
""",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.workflow.profile is Profile.QUALITY
    assert config.granite.device == "cpu"
    assert config.granite.page_batch_size == 2
    assert config.marker.device == "cuda"
    assert config.ocr.engine == "tesseract"
    assert config.ocr.dpi == 300
    assert config.ocr.language == "eng+deu"
    assert config.ocr.threads == 2
    assert config.ocr.page_timeout == 30
    assert str(config.ocr.model_directory) == "/srv/ocr-models"
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
        ("[granite]\nmodel_directory = false\n", "filesystem path string"),
        ("[granite]\nmax_new_tokens = 0\n", "at least 1"),
        ("[workflow]\nunknown = true\n", "unknown option"),
        ("[mystery]\nvalue = true\n", "unknown configuration section"),
        ("[ocr]\nengine = \"paddle\"\n", "auto, tesseract, or rapidocr"),
        ("[ocr]\ndpi = 50\n", "at least 72"),
        ("[ocr]\nlanguage = \"eng; rm\"\n", "language codes joined by"),
        ("[ocr]\nthreads = 0\n", "at least 1"),
        ("[ocr]\npage_timeout = 0\n", "greater than 0"),
        ("[ocr]\nmodel_directory = 1\n", "filesystem path string"),
        ("[ocr]\nunknown = 1\n", "unknown option"),
    ],
)
def test_invalid_configuration_is_rejected(tmp_path, content, message) -> None:
    path = tmp_path / "invalid.toml"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_config(path)


def test_default_configuration_file_matches_ocr_defaults() -> None:
    from pathlib import Path

    from kilix_pdf_conversion.config import OCRSettings

    config = load_config(Path(__file__).parents[1] / "configs" / "default.toml")
    assert config.ocr == OCRSettings()
