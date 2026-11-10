"""Verify the local PP-OCRv6 small model files; never download them.

The two assets are PaddlePaddle's own ONNX exports, pinned by Hugging Face
revision, byte count and SHA-256 in data/pp-ocrv6-small.json. They are read
once into memory after verification, and the models are built from those
bytes, so a file swapped after the check cannot be loaded.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from ..engines.base import EngineUnavailable

MANIFEST_SHA256 = "f8e73517ae656091eb063f0201eac15bd0ca7070f6f21e171a3026e1aa4c8a50"
DET_ASSET = "pp-ocrv6-small-det"
REC_ASSET = "pp-ocrv6-small-rec"
REC_MODEL_NAME = "PP-OCRv6_small_rec"
CHARACTER_COUNT = 18708
CHARACTERS_SHA256 = "f7aa897ca828a4c7c9e2739c30f9161a33306d532f020bcdb91dcfb664a5507e"


@dataclass(frozen=True, slots=True)
class VerifiedOcrModels:
    """Verified in-memory model bytes and the recogniser's character table."""

    det_model: bytes
    rec_model: bytes
    characters: tuple[str, ...]
    revisions: dict[str, str]
    directory: Path


def manifest() -> dict:
    data = files("kilix_pdf_conversion").joinpath("data/pp-ocrv6-small.json").read_bytes()
    if hashlib.sha256(data).hexdigest() != MANIFEST_SHA256:
        raise EngineUnavailable("OCR model manifest hash mismatch")
    parsed = json.loads(data)
    if (parsed.get("schema") != "kilix.pdf.ocr-assets/v1"
            or set(parsed.get("assets", {})) != {DET_ASSET, REC_ASSET}):
        raise EngineUnavailable("OCR model manifest identity mismatch")
    return parsed


def asset_root(model_directory: Path | None = None) -> Path:
    """The directory holding the two asset directories."""
    if model_directory is not None:
        return model_directory.expanduser().resolve()
    explicit = os.environ.get("KILIX_OCR_MODEL_DIR")
    if explicit:
        return Path(explicit).expanduser().resolve()
    content_root = os.environ.get("KILIX_CONTENT_ROOT")
    if content_root:
        return (Path(content_root).expanduser() / "assets").resolve()
    raise EngineUnavailable(
        "PP-OCRv6 model location missing; use the host's KILIX_CONTENT_ROOT or set "
        "KILIX_OCR_MODEL_DIR to the directory holding the accepted assets"
    )


def _read_verified(directory: Path, relative: str, expected: dict) -> bytes:
    path = directory / relative
    try:
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(directory):
            raise EngineUnavailable(f"OCR model path is unsafe: {directory.name}/{relative}")
        if not stat.S_ISREG(path.stat().st_mode):
            raise EngineUnavailable(f"OCR model is not a regular file: {directory.name}/{relative}")
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK | os.O_NOCTTY
        with os.fdopen(os.open(path, flags), "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size != expected["bytes"]:
                raise EngineUnavailable(f"OCR model size mismatch: {directory.name}/{relative}")
            data = stream.read(expected["bytes"] + 1)
    except OSError as error:
        raise EngineUnavailable(
            f"OCR model file unavailable: {directory.name}/{relative}"
        ) from error
    if len(data) != expected["bytes"] or hashlib.sha256(data).hexdigest() != expected["sha256"]:
        raise EngineUnavailable(f"OCR model hash mismatch: {directory.name}/{relative}")
    return data


def _characters(config_bytes: bytes) -> tuple[str, ...]:
    try:
        import yaml

        config = yaml.safe_load(config_bytes.decode("utf-8"))
        name = config["Global"]["model_name"]
        post = config["PostProcess"]
        characters = post["character_dict"]
    except ImportError as error:
        raise EngineUnavailable("PyYAML is required to read the recogniser dictionary") from error
    except (KeyError, TypeError, ValueError, UnicodeError) as error:
        raise EngineUnavailable("OCR recogniser configuration is invalid") from error
    if name != REC_MODEL_NAME or post.get("name") != "CTCLabelDecode":
        raise EngineUnavailable("OCR recogniser configuration identity mismatch")
    if (not isinstance(characters, list) or len(characters) != CHARACTER_COUNT
            or any(type(c) is not str or len(c) != 1 or c in "\r\n" for c in characters)):
        raise EngineUnavailable("OCR recogniser dictionary is invalid")
    if hashlib.sha256("\n".join(characters).encode()).hexdigest() != CHARACTERS_SHA256:
        raise EngineUnavailable("OCR recogniser dictionary hash mismatch")
    return tuple(characters)


def verify_models(model_directory: Path | None = None) -> VerifiedOcrModels:
    """Verify every pinned file of both assets and return the bytes in use."""
    pinned = manifest()
    root = asset_root(model_directory)
    contents: dict[str, dict[str, bytes]] = {}
    for asset_id, asset in pinned["assets"].items():
        directory = root / asset_id
        if not directory.is_dir():
            raise EngineUnavailable(f"OCR model asset is not installed: {asset_id}")
        contents[asset_id] = {
            relative: _read_verified(directory, relative, expected)
            for relative, expected in asset["files"].items()
        }
    return VerifiedOcrModels(
        det_model=contents[DET_ASSET]["inference.onnx"],
        rec_model=contents[REC_ASSET]["inference.onnx"],
        characters=_characters(contents[REC_ASSET]["inference.yml"]),
        revisions={
            asset_id: f"{asset['repository']}@{asset['revision']}"
            for asset_id, asset in pinned["assets"].items()
        },
        directory=root,
    )
