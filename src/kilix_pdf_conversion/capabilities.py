from __future__ import annotations

import importlib.util
import platform
from importlib.metadata import PackageNotFoundError, version
from typing import Any


def _package(name: str, module: str | None = None) -> dict[str, Any]:
    module_name = module or name.replace("-", "_")
    available = importlib.util.find_spec(module_name) is not None
    try:
        package_version = version(name)
    except PackageNotFoundError:
        package_version = None
    return {"available": available, "version": package_version}


def detect_capabilities() -> dict[str, Any]:
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
