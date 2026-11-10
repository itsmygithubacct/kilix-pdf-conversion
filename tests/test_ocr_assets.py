from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from pathlib import Path

import pytest

from kilix_pdf_conversion.engines.base import EngineUnavailable
from kilix_pdf_conversion.ocr import assets

APACHE_NOTICE_SHA256 = "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"


def test_packaged_manifest_pins_the_official_paddlepaddle_exports() -> None:
    pinned = assets.manifest()
    data = files("kilix_pdf_conversion").joinpath("data/pp-ocrv6-small.json").read_bytes()
    assert hashlib.sha256(data).hexdigest() == assets.MANIFEST_SHA256
    det = pinned["assets"][assets.DET_ASSET]
    rec = pinned["assets"][assets.REC_ASSET]
    assert det["repository"] == "PaddlePaddle/PP-OCRv6_small_det_onnx"
    assert rec["repository"] == "PaddlePaddle/PP-OCRv6_small_rec_onnx"
    assert det["revision"] == "28fe5895c24fd108c19eb3e8479f4ab385fbfc62"
    assert rec["revision"] == "b8f84f0b80c529de40b4fbb3544b84fa7233a513"
    assert det["files"]["inference.onnx"]["bytes"] == 9880512
    assert det["files"]["inference.onnx"]["sha256"].startswith("d73e0058")
    assert rec["files"]["inference.onnx"]["bytes"] == 21159378
    assert rec["files"]["inference.onnx"]["sha256"].startswith("5435fd74")
    assert rec["files"]["inference.yml"] == {
        "bytes": 150579,
        "sha256": "ab078671bb49f06228eadccd34f1bb501e157f7a047095ffb943ba81512c77d1",
    }
    for asset in (det, rec):
        assert asset["files"]["notices/LICENSE-apache-2.0.txt"]["sha256"] == APACHE_NOTICE_SHA256
    assert pinned["license"] == "Apache-2.0"


def _yaml(characters: list[str], name: str = assets.REC_MODEL_NAME) -> bytes:
    return json.dumps({
        "Global": {"model_name": name},
        "PostProcess": {"name": "CTCLabelDecode", "character_dict": characters},
    }).encode()


@pytest.fixture
def fake_assets(tmp_path, monkeypatch):
    """A complete, verifiable asset tree with small stand-in files."""
    pytest.importorskip("yaml")
    characters = ["a", "b", "c", "é", "中"]
    contents = {
        assets.DET_ASSET: {"inference.onnx": b"detector", "notices/LICENSE-apache-2.0.txt": b"n"},
        assets.REC_ASSET: {
            "inference.onnx": b"recogniser",
            "inference.yml": _yaml(characters),
            "notices/LICENSE-apache-2.0.txt": b"n",
        },
    }
    pinned = {"schema": "kilix.pdf.ocr-assets/v1", "license": "Apache-2.0", "assets": {}}
    for asset_id, items in contents.items():
        pinned["assets"][asset_id] = {
            "repository": f"PaddlePaddle/{asset_id}", "revision": "0" * 40,
            "files": {
                name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                for name, data in items.items()
            },
        }
        for name, data in items.items():
            path = tmp_path / asset_id / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    monkeypatch.setattr(assets, "manifest", lambda: pinned)
    monkeypatch.setattr(assets, "CHARACTER_COUNT", len(characters))
    monkeypatch.setattr(
        assets, "CHARACTERS_SHA256",
        hashlib.sha256("\n".join(characters).encode()).hexdigest(),
    )
    return tmp_path, characters


def test_verified_assets_return_the_bytes_and_dictionary(fake_assets) -> None:
    root, characters = fake_assets
    models = assets.verify_models(root)
    assert models.det_model == b"detector"
    assert models.rec_model == b"recogniser"
    assert models.characters == tuple(characters)
    assert models.revisions[assets.DET_ASSET].endswith("@" + "0" * 40)
    assert models.directory == root.resolve()


def test_model_directory_comes_from_settings_then_environment(fake_assets, monkeypatch) -> None:
    root, _ = fake_assets
    monkeypatch.delenv("KILIX_OCR_MODEL_DIR", raising=False)
    monkeypatch.delenv("KILIX_CONTENT_ROOT", raising=False)
    with pytest.raises(EngineUnavailable, match="model location missing"):
        assets.asset_root()
    monkeypatch.setenv("KILIX_CONTENT_ROOT", str(root.parent))
    assert assets.asset_root() == (root.parent / "assets").resolve()
    monkeypatch.setenv("KILIX_OCR_MODEL_DIR", str(root))
    assert assets.asset_root() == root.resolve()
    assert assets.asset_root(Path("/elsewhere")) == Path("/elsewhere")
    assert assets.verify_models().rec_model == b"recogniser"


def test_missing_asset_is_unavailable(fake_assets) -> None:
    root, _ = fake_assets
    (root / assets.DET_ASSET / "inference.onnx").unlink()
    (root / assets.DET_ASSET / "notices" / "LICENSE-apache-2.0.txt").unlink()
    (root / assets.DET_ASSET / "notices").rmdir()
    (root / assets.DET_ASSET).rmdir()
    with pytest.raises(EngineUnavailable, match="not installed: pp-ocrv6-small-det"):
        assets.verify_models(root)


def test_changed_model_bytes_are_refused(fake_assets) -> None:
    root, _ = fake_assets
    (root / assets.REC_ASSET / "inference.onnx").write_bytes(b"recogniseR")
    with pytest.raises(EngineUnavailable, match="hash mismatch"):
        assets.verify_models(root)
    (root / assets.REC_ASSET / "inference.onnx").write_bytes(b"longer recogniser")
    with pytest.raises(EngineUnavailable, match="size mismatch"):
        assets.verify_models(root)


def test_symlinked_model_is_refused(fake_assets, tmp_path_factory) -> None:
    root, _ = fake_assets
    outside = tmp_path_factory.mktemp("outside") / "inference.onnx"
    outside.write_bytes(b"detector")
    target = root / assets.DET_ASSET / "inference.onnx"
    target.unlink()
    target.symlink_to(outside)
    with pytest.raises(EngineUnavailable, match="unsafe"):
        assets.verify_models(root)


def test_recogniser_dictionary_is_checked(fake_assets, monkeypatch) -> None:
    pytest.importorskip("yaml")
    with pytest.raises(EngineUnavailable, match="identity mismatch"):
        assets._characters(_yaml(["a"], name="PP-OCRv5_server_rec"))
    with pytest.raises(EngineUnavailable, match="dictionary is invalid"):
        assets._characters(_yaml(["a", "bc", "d", "e", "f"]))
    with pytest.raises(EngineUnavailable, match="dictionary hash mismatch"):
        assets._characters(_yaml(["a", "b", "c", "d", "e"]))
    with pytest.raises(EngineUnavailable, match="configuration is invalid"):
        assets._characters(b"Global: {}\n")
