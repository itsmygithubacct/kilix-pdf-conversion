"""Synthetic integrity/receipt controls; never constructs a neural model."""

import hashlib
import os
import socket

import pytest

pytest.importorskip("kilix_license")
from kilix_pdf_conversion.config import AppConfig, GraniteSettings
from kilix_pdf_conversion.engines import classifier_asset, granite_engine
from kilix_pdf_conversion.engines.base import EngineUnavailable
from kilix_pdf_conversion.workflow import Workflow


def synthetic_asset(tmp_path, monkeypatch):
    directory = tmp_path / "content" / "assets" / classifier_asset.ASSET_ID
    directory.mkdir(parents=True)
    entries = {"config.json": b"synthetic metadata", "model.onnx": b"not real weights"}
    for name, payload in entries.items():
        (directory / name).write_bytes(payload)
    manifest = {"files": {
        name: {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        for name, payload in entries.items()
    }}
    monkeypatch.setattr(classifier_asset, "_manifest", lambda: manifest)
    # Explicit unit substitute: this does not mint or claim a covering receipt.
    monkeypatch.setattr(classifier_asset, "_require_classifier_receipt", lambda: None)
    monkeypatch.setenv("KILIX_CONTENT_ROOT", str(tmp_path / "content"))
    return directory


def test_missing_receipt_refuses_without_creating_store(tmp_path, monkeypatch):
    store = tmp_path / "missing-store"
    monkeypatch.setenv("KILIX_LICENSE_RECEIPTS", str(store))
    with pytest.raises(EngineUnavailable, match="receipt is missing"):
        classifier_asset._require_classifier_receipt()
    assert not store.exists()


def test_malformed_receipt_refused_and_not_modified(tmp_path, monkeypatch):
    store = tmp_path / "store"
    store.mkdir()
    receipt = store / f"{classifier_asset.RECORD_DIGEST}-{classifier_asset.MANIFEST_DIGEST}.json"
    receipt.write_bytes(b"{}")
    before = receipt.stat().st_mtime_ns
    monkeypatch.setenv("KILIX_LICENSE_RECEIPTS", str(store))
    with pytest.raises(EngineUnavailable, match="receipt is invalid"):
        classifier_asset._require_classifier_receipt()
    assert receipt.read_bytes() == b"{}" and receipt.stat().st_mtime_ns == before


def test_synthetic_asset_checks_every_file_and_refuses_corruption(tmp_path, monkeypatch):
    directory = synthetic_asset(tmp_path, monkeypatch)
    snapshot = classifier_asset.verify_classifier_asset()
    assert snapshot.read("model.onnx") == b"not real weights"
    (directory / "model.onnx").write_bytes(b"bad real weights")
    with pytest.raises(EngineUnavailable, match="hash mismatch"):
        classifier_asset.verify_classifier_asset()


def test_symlink_asset_is_refused(tmp_path, monkeypatch):
    directory = synthetic_asset(tmp_path, monkeypatch)
    path = directory / "model.onnx"
    target = tmp_path / "outside"
    target.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(target)
    with pytest.raises(EngineUnavailable, match="unsafe"):
        classifier_asset.verify_classifier_asset()


def test_fifo_asset_is_refused_without_a_writer(tmp_path, monkeypatch):
    directory = synthetic_asset(tmp_path, monkeypatch)
    path = directory / "model.onnx"
    path.unlink()
    os.mkfifo(path)
    with pytest.raises(EngineUnavailable, match="not a regular file"):
        classifier_asset.verify_classifier_asset()


def test_workflow_calls_preparation_but_still_refuses_decoder(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(granite_engine, "prepare_classifier_stage", lambda: calls.append("called"))
    config = AppConfig(granite=GraniteSettings(chart_extraction=True))
    with Workflow(config) as workflow:
        with pytest.raises(EngineUnavailable, match="decoder and routing are not qualified"):
            workflow.convert(tmp_path / "no-source.pdf")
    assert calls == ["called"]


def test_verification_does_not_open_network_for_synthetic_assets(tmp_path, monkeypatch):
    synthetic_asset(tmp_path, monkeypatch)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("unexpected network connection")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    assert classifier_asset.verify_classifier_asset().read("model.onnx") == b"not real weights"
