from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_python_module_entry_point_help() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [sys.executable, "-m", "neuralcut", "--help"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "--no-browser" in completed.stdout
    assert "--data-dir" in completed.stdout
