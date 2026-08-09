"""Both runtime entry points must actually launch: python -m strix and strix."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def test_python_dash_m_strix_launches() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "strix", "--version"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0
    assert completed.stdout.strip().startswith("strix ")


def test_console_script_launches() -> None:
    script = shutil.which("strix") or str(Path(sys.executable).parent / "strix")
    assert Path(script).exists(), "console script 'strix' is not installed"
    completed = subprocess.run([script, "--version"], capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0
    assert completed.stdout.strip().startswith("strix ")
