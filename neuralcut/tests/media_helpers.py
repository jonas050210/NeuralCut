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


def make_moving_car_video(path: Path, *, duration: float = 3.0) -> Path:
    """Synthetic 'car': a red box driving left→right across a static grey road."""
    exe = require_ffmpeg()
    cmd = [
        exe, "-y",
        "-f", "lavfi", "-i", f"color=c=0x808080:s=320x240:r=10:d={duration}",
        "-f", "lavfi", "-i", f"color=c=red:s=60x35:r=10:d={duration}",
        "-filter_complex",
        "[0:v][1:v]overlay=x='20+t*80':y=140,"
        "drawbox=x=0:y=175:w=320:h=3:color=white:t=fill[v]",
        "-map", "[v]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    assert proc.returncode == 0, proc.stderr[-2000:]
    return path


def make_scene_change_video(path: Path) -> Path:
    """Two hard-cut scenes: 1.5s red, then 1.5s blue (with audio tone)."""
    exe = require_ffmpeg()
    cmd = [
        exe, "-y",
        "-f", "lavfi", "-i", "color=c=red:s=320x240:r=10:d=1.5",
        "-f", "lavfi", "-i", "color=c=blue:s=320x240:r=10:d=1.5",
        "-f", "lavfi", "-i", "sine=frequency=440:d=3",
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
        "-map", "[v]", "-map", "2:a",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    assert proc.returncode == 0, proc.stderr[-2000:]
    return path


def frame_mean_gray(path: Path, *, at_seconds: float = 0.5) -> float:
    """Mean grayscale value of one rendered frame (deterministic pixel check)."""
    exe = require_ffmpeg()
    proc = subprocess.run(
        [exe, "-v", "error", "-ss", str(at_seconds), "-i", str(path),
         "-frames:v", "1", "-vf", "scale=64:48", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True, timeout=120, check=False,
    )
    assert proc.returncode == 0 and proc.stdout
    return sum(proc.stdout) / len(proc.stdout)


def pixel_rgb(path: Path, *, at_seconds: float, x_fraction: float, y_fraction: float,
              width: int = 320, height: int = 240) -> tuple[int, int, int]:
    exe = require_ffmpeg()
    proc = subprocess.run(
        [exe, "-v", "error", "-ss", str(at_seconds), "-i", str(path),
         "-frames:v", "1", "-vf", f"scale={width}:{height}",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, timeout=120, check=False,
    )
    frame = proc.stdout
    assert proc.returncode == 0 and len(frame) >= width * height * 3
    x = min(width - 1, max(0, int(x_fraction * width)))
    y = min(height - 1, max(0, int(y_fraction * height)))
    idx = (y * width + x) * 3
    return frame[idx], frame[idx + 1], frame[idx + 2]
