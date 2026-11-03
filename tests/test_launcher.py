from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def test_launcher_selects_profiles_and_rejects_missing_optional_runtime(tmp_path):
    launcher = tmp_path / "kilix-pdf"
    shutil.copy2(Path(__file__).parents[1] / "kilix-pdf", launcher)
    native = tmp_path / ".runtime" / "bin" / "python"
    native.parent.mkdir(parents=True)
    native.write_text("#!/bin/sh\nprintf 'selected-native\\n'\n")
    native.chmod(0o755)
    env = dict(os.environ, KILIX_PDF_RUNTIME="native")
    native_run = subprocess.run([str(launcher), "doctor"], env=env, capture_output=True, text=True)
    assert native_run.returncode == 0
    assert native_run.stdout == "selected-native\n"
    env["KILIX_PDF_RUNTIME"] = "granite"
    missing = subprocess.run([str(launcher), "doctor"], env=env, capture_output=True, text=True)
    assert missing.returncode == 1
    assert "runtime-granite" in missing.stderr
    optional = tmp_path / ".runtime-granite" / "bin" / "python"
    optional.parent.mkdir(parents=True)
    optional.write_text("#!/bin/sh\nprintf 'selected-granite\\n'\n")
    optional.chmod(0o755)
    selected = subprocess.run([str(launcher), "doctor"], env=env, capture_output=True, text=True)
    assert selected.returncode == 0
    assert selected.stdout == "selected-granite\n"
    env["KILIX_PDF_RUNTIME"] = "unknown"
    invalid = subprocess.run([str(launcher)], env=env, capture_output=True, text=True)
    assert invalid.returncode == 2
