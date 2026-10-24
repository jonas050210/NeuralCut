"""Helpers to generate short synthetic test videos with ffmpeg (no personal media)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def ffmpeg_exe() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return None


def require_ffmpeg() -> str:
    exe = ffmpeg_exe()
    if not exe:
        pytest.skip("ffmpeg not available in this environment")
    return exe


def make_video(
    path: Path,
    *,
    duration: float = 3.0,
    color: str = "red",
    with_audio: bool = True,
    size: str = "320x240",
) -> Path:
    exe = require_ffmpeg()
    cmd = [
        exe, "-y",
        "-f", "lavfi", "-i", f"color=c={color}:s={size}:r=10:d={duration}",
    ]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:d={duration}"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if with_audio:
        cmd += ["-c:a", "aac", "-shortest"]
    cmd += [str(path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert path.is_file() and path.stat().st_size > 0
    return path
