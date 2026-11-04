"""Public synthetic fixtures verify byte binding without model execution."""

import builtins
import hashlib
import json
import os
import sys
from types import MappingProxyType, ModuleType, SimpleNamespace

import pytest

from kilix_pdf_conversion.engines import classifier_asset
from kilix_pdf_conversion.engines.base import EngineUnavailable
from kilix_pdf_conversion.engines.classifier_snapshot_loader import load_classifier_for_parity


def fixture_snapshot(tmp_path, monkeypatch):
    asset = tmp_path / "assets" / classifier_asset.ASSET_ID
    asset.mkdir(parents=True)
    content = {
        "config.json": json.dumps({"model_type": "efficientnet",
            "architectures": ["EfficientNetForImageClassification"],
            "id2label": {str(i): f"class-{i}" for i in range(26)}}).encode(),
        "preprocessor_config.json": b'{"image_processor_type":"ViTImageProcessor"}',
        "model.safetensors": b"public synthetic transformer weights",
        "model.onnx": b"public synthetic onnx weights",
    }
    manifest = {"files": {name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                for name, data in content.items()}}
    for name, data in content.items():
        (asset / name).write_bytes(data)
    monkeypatch.setenv("KILIX_CONTENT_ROOT", str(tmp_path))
    monkeypatch.setattr(classifier_asset, "_manifest", lambda: manifest)
    # This fake receipt verifier is a unit seam, not a claimed consent or receipt.
    monkeypatch.setattr(classifier_asset, "_require_classifier_receipt", lambda: None)
    return asset, content


def fake_engines(monkeypatch):
    observed = {}
    ort = ModuleType("onnxruntime")
    class SessionOptions:
        pass
    def session(data, *, sess_options, providers):
        observed["onnx"] = data
        observed["providers"] = providers
        observed["threads"] = (sess_options.intra_op_num_threads, sess_options.inter_op_num_threads)
        return "fake-session"
    ort.SessionOptions = SessionOptions
    ort.InferenceSession = session
    safe = ModuleType("safetensors")
    safe.__path__ = []
    safe_torch = ModuleType("safetensors.torch")
    def load(data):
        observed["safetensors"] = data
        return {"fake": "state"}
    safe_torch.load = load
    transform = ModuleType("transformers")
    class Config:
        @classmethod
        def from_dict(cls, data):
            observed["config"] = data
            return "fake-config"
    class Processor:
        @classmethod
        def from_dict(cls, data):
            observed["processor"] = data
            return "fake-processor"
    class Model:
        def __init__(self, config):
            assert config == "fake-config"
        def load_state_dict(self, state, *, strict):
            observed["state"] = (state, strict)
        def eval(self):
            observed["eval"] = True
    transform.EfficientNetConfig = Config
    transform.EfficientNetForImageClassification = Model
    transform.ViTImageProcessor = Processor
    for name, module in {"onnxruntime": ort, "safetensors": safe,
                         "safetensors.torch": safe_torch, "transformers": transform}.items():
        monkeypatch.setitem(sys.modules, name, module)
    return observed


def test_replacement_after_verification_loads_only_original_bytes(tmp_path, monkeypatch):
    asset, content = fixture_snapshot(tmp_path, monkeypatch)
    snapshot = classifier_asset.verify_classifier_asset()
    for path in asset.iterdir():
        path.unlink()
        path.write_bytes(b"attacker replacement")
    observed = fake_engines(monkeypatch)
    monkeypatch.setattr(builtins, "open", lambda *_a, **_k: pytest.fail("asset reopened"))
    processor, _, session, labels = load_classifier_for_parity(snapshot)
    assert processor == "fake-processor" and session == "fake-session"
    assert observed["safetensors"] == content["model.safetensors"]
    assert observed["onnx"] == content["model.onnx"]
    assert observed["config"]["model_type"] == "efficientnet"
    assert observed["processor"]["image_processor_type"] == "ViTImageProcessor"
    assert observed["state"][1] is True and observed["providers"] == ["CPUExecutionProvider"]
    assert observed["threads"] == (2, 1) and len(labels) == 26


def test_mutated_snapshot_is_refused_before_engine_import(tmp_path, monkeypatch):
    _, content = fixture_snapshot(tmp_path, monkeypatch)
    content["model.onnx"] = b"public synthetic onnx weightz"
    snapshot = classifier_asset.VerifiedClassifierAsset(MappingProxyType(content))
    fake_engines(monkeypatch)
    with pytest.raises(EngineUnavailable, match="snapshot hash mismatch"):
        load_classifier_for_parity(snapshot)


def test_replacing_source_after_open_does_not_replace_verified_bytes(tmp_path, monkeypatch):
    asset, content = fixture_snapshot(tmp_path, monkeypatch)
    original_open = os.open
    def replace_after_open(path, flags, *args, **kwargs):
        fd = original_open(path, flags, *args, **kwargs)
        if os.fspath(path) == os.fspath(asset / "model.onnx"):
            replacement = asset / "replacement"
            replacement.write_bytes(b"x" * len(content["model.onnx"]))
            os.replace(replacement, path)
        return fd
    monkeypatch.setattr(classifier_asset.os, "open", replace_after_open)
    snapshot = classifier_asset.verify_classifier_asset()
    assert snapshot.read("model.onnx") == content["model.onnx"]
    assert (asset / "model.onnx").read_bytes() != snapshot.read("model.onnx")


def test_snapshot_storage_is_immutable(tmp_path, monkeypatch):
    fixture_snapshot(tmp_path, monkeypatch)
    snapshot = classifier_asset.verify_classifier_asset()
    with pytest.raises(TypeError):
        snapshot._files["model.onnx"] = b"replacement"
    with pytest.raises((AttributeError, TypeError)):
        snapshot._files = SimpleNamespace()


def test_loader_copies_then_checks_against_mutable_mapping(tmp_path, monkeypatch):
    from collections.abc import Mapping

    _, content = fixture_snapshot(tmp_path, monkeypatch)
    class SwitchAfterRead(Mapping):
        def __init__(self):
            self.count = {}
        def __iter__(self):
            return iter(content)
        def __len__(self):
            return len(content)
        def __getitem__(self, key):
            self.count[key] = self.count.get(key, 0) + 1
            if self.count[key] > 1:
                return b"changed after admission"
            return content[key]
    snapshot = classifier_asset.VerifiedClassifierAsset(SwitchAfterRead())
    observed = fake_engines(monkeypatch)
    load_classifier_for_parity(snapshot)
    assert observed["onnx"] == content["model.onnx"]
    assert observed["safetensors"] == content["model.safetensors"]


def test_loader_refuses_missing_receipt_before_engine_construction(tmp_path, monkeypatch):
    fixture_snapshot(tmp_path, monkeypatch)
    snapshot = classifier_asset.verify_classifier_asset()
    observed = fake_engines(monkeypatch)
    def refuse():
        raise EngineUnavailable("Classifier first-use receipt is missing")
    monkeypatch.setattr(classifier_asset, "_require_classifier_receipt", refuse)
    with pytest.raises(EngineUnavailable, match="receipt is missing"):
        load_classifier_for_parity(snapshot)
    assert observed == {}
