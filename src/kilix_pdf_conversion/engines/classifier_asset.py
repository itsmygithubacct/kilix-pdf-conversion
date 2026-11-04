"""Verify and prepare the local classifier without loading model weights."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType

from .base import EngineUnavailable
from .classifier_binding import (
    REPOSITORY,
    REVISION,
    pinned_classifier_options,
)

ASSET_ID = "documentfigureclassifier-v2.5"
RECORD_DIGEST = "c28bcfb205ea79b6eada2936bc4d78f84028176dda115de6437d9333b3829183"
MANIFEST_DIGEST = "4efc9577a746d150f2c9d472390330307f2dcce8f9052b4c736f25c466d7ab62"
LICENSE_SHA256 = "b05785f9f18e6716bab63424b11454513b9943a222595b70411009202fc592b5"
ASSET_FILE_SHA256 = "29e20a748723844646b5aae84b355c951305d4286c8f599209ae2e8456562a6c"


def _manifest() -> dict:
    data = files("kilix_pdf_conversion").joinpath(
        "data/documentfigureclassifier-v2.5.json"
    ).read_bytes()
    if hashlib.sha256(data).hexdigest() != ASSET_FILE_SHA256:
        raise EngineUnavailable("Classifier asset manifest hash mismatch")
    manifest = json.loads(data)
    expected = {
        "schema": "kilix.pdf.classifier-asset/v1", "asset_id": ASSET_ID,
        "repository": REPOSITORY, "revision": REVISION,
        "record_id": ASSET_ID, "record_digest": RECORD_DIGEST,
        "asset_manifest_digest": MANIFEST_DIGEST, "license_text_sha256": LICENSE_SHA256,
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise EngineUnavailable("Classifier asset manifest identity mismatch")
    return manifest


def _require_classifier_receipt() -> None:
    """Read the standard shared receipt; do not create a store or receipt."""
    try:
        import kilix_license as license_api
        from kilix_license.coverage import covers
        from kilix_license.paths import receipt_store_root
        from kilix_license.receipts import parse_receipt_bytes
        from kilix_license.store import read_receipt_file
    except ImportError as error:
        raise EngineUnavailable("Classifier licence authority is unavailable") from error
    try:
        record = license_api.load_determined_records().by_digest(RECORD_DIGEST)
        if record.id != ASSET_ID or record.text_sha256 != LICENSE_SHA256:
            raise EngineUnavailable("Classifier licence record identity mismatch")
        path = receipt_store_root() / f"{RECORD_DIGEST}-{MANIFEST_DIGEST}.json"
        data = read_receipt_file(path)
        if data is None:
            raise EngineUnavailable("Classifier first-use receipt is missing")
        covers(record, parse_receipt_bytes(data), manifest_digest=MANIFEST_DIGEST)
    except EngineUnavailable:
        raise
    except (KeyError, ValueError, OSError, license_api.LicenseError) as error:
        raise EngineUnavailable("Classifier first-use receipt is invalid") from error


@dataclass(frozen=True, slots=True)
class VerifiedClassifierAsset:
    """An immutable in-memory copy; consumers must recheck its pinned manifest."""

    _files: Mapping[str, bytes]

    def read(self, name: str) -> bytes:
        return self._files[name]

    def _verified_copy(self) -> dict[str, bytes]:
        expected = _manifest()["files"]
        copied = dict(self._files)
        if set(copied) != set(expected):
            raise EngineUnavailable("Classifier snapshot file set mismatch")
        for name, item in expected.items():
            data = copied[name]
            if (type(data) is not bytes or len(data) != item["bytes"]
                    or hashlib.sha256(data).hexdigest() != item["sha256"]):
                raise EngineUnavailable(f"Classifier snapshot hash mismatch: {name}")
        return copied

    def assert_integrity(self) -> None:
        self._verified_copy()


def verify_classifier_asset() -> VerifiedClassifierAsset:
    """Copy and verify every selected classifier file after checking the receipt."""
    manifest = _manifest()
    _require_classifier_receipt()
    root = os.environ.get("KILIX_CONTENT_ROOT")
    if not root:
        raise EngineUnavailable("Classifier content root is missing")
    directory = (Path(root).expanduser() / "assets" / ASSET_ID).resolve()
    if not directory.is_dir():
        raise EngineUnavailable("Classifier asset directory is missing")
    verified = {}
    for relative, expected in manifest["files"].items():
        path = directory / relative
        try:
            if path.is_symlink() or not path.resolve(strict=True).is_relative_to(directory):
                raise EngineUnavailable(f"Classifier asset path is unsafe: {relative}")
            if not stat.S_ISREG(path.stat().st_mode):
                raise EngineUnavailable(f"Classifier asset is not a regular file: {relative}")
            # Nonblocking and no controlling terminal keep a file swapped
            # after stat from hanging the request or attaching a terminal.
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK | os.O_NOCTTY
            fd = os.open(path, flags)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size != expected["bytes"]:
                    raise EngineUnavailable(f"Classifier asset size mismatch: {relative}")
                data = stream.read(expected["bytes"] + 1)
                digest = hashlib.sha256(data).hexdigest()
        except OSError as error:
            raise EngineUnavailable(f"Classifier asset unavailable: {relative}") from error
        if len(data) != expected["bytes"] or digest != expected["sha256"]:
            raise EngineUnavailable(f"Classifier asset hash mismatch: {relative}")
        verified[relative] = data
    return VerifiedClassifierAsset(MappingProxyType(verified))


def prepare_classifier_stage():
    """Bind verified metadata and pinned options; never initialize an engine."""
    snapshot = verify_classifier_asset()
    snapshot.assert_integrity()
    try:
        from docling.datamodel.picture_classification_options import (
            DocumentPictureClassifierOptions,
        )
    except ImportError as error:
        raise EngineUnavailable("Classifier Docling runtime is unavailable") from error
    options = DocumentPictureClassifierOptions.from_preset(
        "document_figure_classifier_v2"
    ).model_copy(deep=True)
    options.engine_options.compile_model = False
    return snapshot, pinned_classifier_options(options)
