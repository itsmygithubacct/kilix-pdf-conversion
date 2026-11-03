"""Offline Granite identity checks and lossless generation accounting."""
from __future__ import annotations

import hashlib
import json
import os
from importlib.metadata import PackageNotFoundError, version
from importlib.resources import files
from pathlib import Path

from .base import EngineUnavailable

REPOSITORY = "ibm-granite/granite-docling-258M"
REVISION = "982fe3b40f2fa73c365bdb1bcacf6c81b7184bfe"
RUNTIME_PINS = {
    "docling": "2.118.0",
    "docling-slim": "2.118.0",
    "docling-core": "2.90.0",
    "transformers": "4.57.3",
    "torch": "2.6.0+cpu",
    "torchvision": "0.21.0+cpu",
    "pypdfium2": "5.12.1",
}


def check_runtime() -> dict[str, str]:
    actual = {}
    for package, expected in RUNTIME_PINS.items():
        try:
            actual[package] = version(package)
        except PackageNotFoundError as error:
            raise EngineUnavailable(
                f"Granite runtime missing {package}; run make runtime-granite and "
                "select KILIX_PDF_RUNTIME=granite"
            ) from error
        if actual[package] != expected:
            raise EngineUnavailable(
                f"Granite requires {package}=={expected}, found {actual[package]}; "
                "rebuild the frozen optional runtime"
            )
    return actual


def verify_asset(directory: Path | None = None) -> tuple[Path, dict]:
    """Verify the pinned local asset; never download or create an agreement."""
    if directory is None:
        explicit = os.environ.get("KILIX_GRANITE_MODEL_DIR")
        content_root = os.environ.get("KILIX_CONTENT_ROOT")
        if explicit:
            directory = Path(explicit)
        elif content_root:
            directory = Path(content_root) / "assets" / "granite-docling-258m"
        else:
            raise EngineUnavailable(
                "Granite asset location missing; use the host's KILIX_CONTENT_ROOT "
                "or set KILIX_GRANITE_MODEL_DIR to the accepted local asset"
            )
    directory = directory.expanduser().resolve()
    manifest = json.loads(
        files("kilix_pdf_conversion").joinpath("data/granite-docling-258m.json").read_text()
    )
    if manifest["repository"] != REPOSITORY or manifest["revision"] != REVISION:
        raise EngineUnavailable("Granite asset manifest identity mismatch")
    for relative, expected in manifest["files"].items():
        path = directory / relative
        try:
            if path.stat().st_size != expected["bytes"]:
                raise EngineUnavailable(f"Granite asset size mismatch: {relative}")
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
        except OSError as error:
            raise EngineUnavailable(f"Granite asset file unavailable: {relative}") from error
        if digest != expected["sha256"]:
            raise EngineUnavailable(f"Granite asset hash mismatch: {relative}")
    return directory, manifest


def remove_trailing_pad_tokens(text: str, pad_token: str | None) -> str:
    """Remove whole pad strings only, preserving whitespace and literal text."""
    if pad_token:
        while text.endswith(pad_token):
            text = text[:-len(pad_token)]
    return text


def generation_summary(
    generated_ids: list[int], *, raw_text: str, pad_token: str | None,
    eos_ids: set[int], stop_matched: bool, effective_limit: int,
) -> dict:
    # Single-sequence generation has no batch-added trailing pads. An EOS that
    # shares its ID with pad is a generated token and remains in the count.
    if generated_ids and generated_ids[-1] in eos_ids:
        reason = "end_of_sequence"
    elif stop_matched:
        reason = "stop_sequence"
    elif len(generated_ids) >= effective_limit:
        reason = "length"
    else:
        reason = "unspecified"
    text = remove_trailing_pad_tokens(raw_text, pad_token)
    return {
        "text": text,
        "raw_text": raw_text,
        "num_tokens": len(generated_ids),
        "stop_reason": reason,
        "truncated": reason == "length",
        "complete_doctags": text.rstrip().endswith("</doctag>"),
        "terminal_token_id": generated_ids[-1] if generated_ids else None,
    }
