from __future__ import annotations

import hashlib
import json

import pytest

from kilix_pdf_conversion.engines import granite_support as support
from kilix_pdf_conversion.engines.base import EngineUnavailable


@pytest.mark.parametrize("text", [
    "", "next", "<doctag><text>next", "<doctag></doctag>",
    "<text>text</text>", "<otsl><fcel>text<nl></otsl>",
    "<caption>next</caption>", "<section_header_level_1>next</section_header_level_1>",
    "literal <|end_of_text|> in the middle", "trailing whitespace \n",
])
@pytest.mark.parametrize("pads", [0, 1, 3])
def test_cleanup_preserves_every_nonpad_character(text, pads):
    pad = "<|end_of_text|>"
    assert support.remove_trailing_pad_tokens(text + pad * pads, pad) == text


def test_character_set_regression_and_empty_pad():
    truncated = "<doctag><text>next"
    assert truncated.rstrip("<|end_of_text|>") == "<doctag"  # noqa: B005 - prior defect
    assert support.remove_trailing_pad_tokens(truncated, "<|end_of_text|>") == truncated
    assert support.remove_trailing_pad_tokens(truncated, "") == truncated
    assert support.remove_trailing_pad_tokens(truncated, None) == truncated


@pytest.mark.parametrize("ids,matched,expected,truncated", [
    ([4, 5], False, "length", True),
    ([4, 9], True, "end_of_sequence", False),
    ([4, 5], True, "stop_sequence", False),
    ([4], False, "unspecified", False),
])
def test_stop_precedence_including_stop_on_last_budget_token(ids, matched, expected, truncated):
    result = support.generation_summary(
        ids, raw_text="<doctag></doctag><|end_of_text|>", pad_token="<|end_of_text|>",
        eos_ids={9}, stop_matched=matched, effective_limit=2,
    )
    assert result["num_tokens"] == len(ids)
    assert result["stop_reason"] == expected
    assert result["truncated"] is truncated
    assert result["complete_doctags"]
    assert result["text"] == "<doctag></doctag>"


def test_missing_location_fails_without_importing_model_stack(monkeypatch):
    monkeypatch.delenv("KILIX_CONTENT_ROOT", raising=False)
    monkeypatch.delenv("KILIX_GRANITE_MODEL_DIR", raising=False)
    with pytest.raises(EngineUnavailable, match="location missing"):
        support.verify_asset()


def test_asset_hash_and_folder_bridge(tmp_path, monkeypatch):
    payload = b"pinned asset bytes"
    root = tmp_path / "content"
    directory = root / "assets" / "granite-docling-258m"
    directory.mkdir(parents=True)
    asset = directory / "config.json"
    asset.write_bytes(payload)
    manifest = tmp_path / "package" / "data" / "granite-docling-258m.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({
        "repository": support.REPOSITORY, "revision": support.REVISION,
        "files": {"config.json": {
            "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
        }},
    }))
    monkeypatch.setattr(support, "files", lambda _: tmp_path / "package")
    monkeypatch.setenv("KILIX_CONTENT_ROOT", str(root))
    monkeypatch.delenv("KILIX_GRANITE_MODEL_DIR", raising=False)
    assert support.verify_asset()[0] == directory.resolve()
    asset.write_bytes(b"x" * len(payload))
    with pytest.raises(EngineUnavailable, match="hash mismatch"):
        support.verify_asset()
    asset.unlink()
    with pytest.raises(EngineUnavailable, match="unavailable"):
        support.verify_asset()


def test_runtime_version_drift_fails_closed(monkeypatch):
    monkeypatch.setattr(support, "version", lambda name: "999.0")
    with pytest.raises(EngineUnavailable, match="requires docling==2.118.0"):
        support.check_runtime()
