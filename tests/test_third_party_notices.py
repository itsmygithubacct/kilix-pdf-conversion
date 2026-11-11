from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Packages the notices name by their project name rather than the PyPI one.
NOTICE_NAMES = {
    "onnxruntime": "ONNX Runtime",
    "protobuf": "Protocol Buffers",
}


def test_every_locked_runtime_package_is_in_the_notices() -> None:
    lock = tomllib.loads((ROOT / "runtime" / "uv.lock").read_text())
    notices = (ROOT / "THIRD-PARTY-NOTICES.md").read_text().lower()
    missing = sorted(
        package["name"]
        for package in lock["package"]
        if "registry" in package.get("source", {})
        and NOTICE_NAMES.get(package["name"], package["name"]).lower() not in notices
    )
    assert missing == []


def test_colorama_is_named_as_windows_only() -> None:
    lock = tomllib.loads((ROOT / "runtime" / "uv.lock").read_text())
    markers = {
        dependency.get("marker")
        for package in lock["package"]
        for dependency in package.get("dependencies", [])
        if dependency["name"] == "colorama"
    }
    assert markers == {"sys_platform == 'win32'"}
    notices = (ROOT / "THIRD-PARTY-NOTICES.md").read_text()
    assert "| Colorama (Windows only) | BSD-3-Clause |" in notices
