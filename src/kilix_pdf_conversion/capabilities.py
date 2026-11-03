from __future__ import annotations

import importlib.util
import platform
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from .engines.base import EngineUnavailable
from .engines.granite_support import REVISION, check_runtime, verify_asset
from .models import EngineName


def _package(name: str, module: str | None = None) -> dict[str, Any]:
    module_name = module or name.replace("-", "_")
    available = importlib.util.find_spec(module_name) is not None
    try:
        package_version = version(name)
    except PackageNotFoundError:
        package_version = None
    return {"available": available, "version": package_version}


def detect_capabilities(model_directory: Path | None = None) -> dict[str, Any]:
    capabilities: dict[str, Any] = {
        "python": platform.python_version(),
        "base": {
            "pymupdf": _package("pymupdf"),
            "pymupdf4llm": _package("pymupdf4llm"),
        },
        "optional": {
            "docling": _package("docling"),
            "marker": _package("marker-pdf", "marker"),
        },
        "accelerator": {
            "torch": _package("torch"),
            "cuda_available": False,
            "cuda_device_count": 0,
            "cuda_devices": [],
        },
    }
    try:
        runtime = check_runtime()
        directory, _ = verify_asset(model_directory)
        capabilities["granite"] = {
            "available": True, "revision": REVISION, "model_directory": str(directory),
            "runtime": runtime, "device": "cpu",
            "note": "Dependencies and asset verified; model loading is checked at conversion.",
        }
    except EngineUnavailable as error:
        capabilities["granite"] = {"available": False, "error": str(error)}
    if capabilities["accelerator"]["torch"]["available"]:
        try:
            import torch

            capabilities["accelerator"]["cuda_available"] = torch.cuda.is_available()
            capabilities["accelerator"]["cuda_device_count"] = torch.cuda.device_count()
            capabilities["accelerator"]["cuda_devices"] = [
                torch.cuda.get_device_name(index)
                for index in range(torch.cuda.device_count())
            ]
        except Exception as error:
            capabilities["accelerator"]["error"] = f"{type(error).__name__}: {error}"
    return capabilities


def base_is_ready(capabilities: dict[str, Any]) -> bool:
    return all(
        item["available"] for item in capabilities["base"].values()
    )


def available_engine_names(capabilities: dict[str, Any]) -> frozenset[EngineName]:
    engines: set[EngineName] = set()
    if base_is_ready(capabilities):
        engines.add(EngineName.PYMUPDF)
    if capabilities.get("granite", {}).get("available", False):
        engines.update({EngineName.GRANITE_HYBRID, EngineName.GRANITE_PURE})
    if capabilities["optional"]["marker"]["available"]:
        engines.add(EngineName.MARKER)
    return frozenset(engines)
