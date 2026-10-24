"""Media processing: ffprobe/ffmpeg-backed probing (Phase 2).

Resolves ffmpeg/ffprobe from settings, ``PATH``, or the optional
``imageio-ffmpeg`` package (ffmpeg binary only). Probing uses ffprobe JSON
when available and falls back to parsing ``ffmpeg -i`` output, so a lone
ffmpeg binary is enough. No GPU or model runtime is involved.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from neuralcut.backend.di import Container

from neuralcut.errors import UnavailableError, ValidationError

SUPPORTED_VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpg", ".mpeg", ".ts",
}
SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a"}
SUPPORTED_EXTENSIONS = SUPPORTED_VIDEO_EXTENSIONS | SUPPORTED_AUDIO_EXTENSIONS


@dataclass
class MediaInfo:
    path: str
    duration_seconds: float | None
    width: int | None
    height: int | None
    fps: float | None
    has_audio: bool
    has_video: bool
    codec: str | None
    format_name: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class MediaProcessorAdapter:
    """Probes local media files with ffprobe/ffmpeg."""

    def __init__(self, container: "Container") -> None:
        self.container = container
        self.ffmpeg_path = (
            container.settings.media.ffmpeg_path or shutil.which("ffmpeg") or self._imageio_ffmpeg()
        )
        self.ffprobe_path = container.settings.media.probe_path or shutil.which("ffprobe")

    @staticmethod
    def _imageio_ffmpeg() -> str | None:
        try:
            import imageio_ffmpeg

            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:  # noqa: BLE001 - optional dependency
            return None

    # ---- status -----------------------------------------------------------

    def status(self) -> dict:
        return {
            "available": self.ffmpeg_path is not None,
            "reason": None
            if self.ffmpeg_path
            else "ffmpeg not found (set media.ffmpeg_path or install ffmpeg)",
            "ffmpeg": self.ffmpeg_path,
            "ffprobe": self.ffprobe_path,
            "probe_mode": (
                "ffprobe" if self.ffprobe_path else ("ffmpeg" if self.ffmpeg_path else None)
            ),
            "supported_extensions": sorted(SUPPORTED_EXTENSIONS),
        }

    def require_ffmpeg(self) -> str:
        if not self.ffmpeg_path:
            raise UnavailableError(
                "ffmpeg is required for this operation but was not found. "
                "Install ffmpeg or set media.ffmpeg_path in the config.",
                details={"feature": "media.ffmpeg"},
            )
        return self.ffmpeg_path

    # ---- probing ----------------------------------------------------------

    def probe(self, path: str | Path) -> MediaInfo:
        path = Path(path)
        if not path.is_file():
            raise ValidationError(
                f"media file not found: {path}", details={"path": str(path)}, http_status=404
            )
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise ValidationError(
                f"unsupported media format: {suffix or '(no extension)'}",
                details={"path": str(path), "supported": sorted(SUPPORTED_EXTENSIONS)},
            )
        self.require_ffmpeg()
        if self.ffprobe_path:
            return self._probe_ffprobe(path)
        return self._probe_ffmpeg(path)

    def _probe_ffprobe(self, path: Path) -> MediaInfo:
        cmd = [
            self.ffprobe_path, "-v", "error", "-show_format", "-show_streams",
            "-of", "json", str(path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
        if proc.returncode != 0:
            raise ValidationError(
                f"ffprobe could not read media file: {path.name}: {proc.stderr.strip()[:300]}",
                details={"path": str(path)},
            )
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"ffprobe returned invalid output for {path.name}") from exc
        streams = data.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        fps = None
        if video:
            raw_fps = video.get("avg_frame_rate") or video.get("r_frame_rate") or ""
            if "/" in raw_fps:
                num, den = raw_fps.split("/", 1)
                try:
                    fps = float(num) / float(den) if float(den) else None
                except ValueError:
                    fps = None
        duration = None
        fmt = data.get("format", {})
        if fmt.get("duration"):
            duration = float(fmt["duration"])
        elif video and video.get("duration"):
            duration = float(video["duration"])
        return MediaInfo(
            path=str(path),
            duration_seconds=duration,
            width=int(video["width"]) if video and video.get("width") else None,
            height=int(video["height"]) if video and video.get("height") else None,
            fps=fps,
            has_audio=audio is not None,
            has_video=video is not None,
            codec=(video or audio or {}).get("codec_name"),
            format_name=fmt.get("format_name"),
        )

    def _probe_ffmpeg(self, path: Path) -> MediaInfo:
        # `ffmpeg -i` exits non-zero without an output target but prints stream
        # metadata to stderr; parse Duration / Stream lines.
        proc = subprocess.run(
            [self.ffmpeg_path, "-hide_banner", "-i", str(path)],
            capture_output=True, text=True, timeout=60, check=False,
        )
        text = proc.stderr or ""
        if "Invalid data" in text or "moov atom not found" in text:
            raise ValidationError(
                f"ffmpeg could not read media file: {path.name}",
                details={"path": str(path)},
            )
        duration = None
        match = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", text)
        if match:
            duration = int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))
        width = height = None
        fps = None
        codec = None
        res = re.search(r"Video:\s*(\w+).*?,\s*(\d+)x(\d+)", text)
        if res:
            codec = res.group(1)
            width, height = int(res.group(2)), int(res.group(3))
        fps_match = re.search(r"([\d.]+)\s*fps", text)
        if fps_match:
            fps = float(fps_match.group(1))
        if codec is None:
            audio_match = re.search(r"Audio:\s*(\w+)", text)
            if audio_match:
                codec = audio_match.group(1)
        return MediaInfo(
            path=str(path),
            duration_seconds=duration,
            width=width,
            height=height,
            fps=fps,
            has_audio="Audio:" in text,
            has_video="Video:" in text,
            codec=codec,
        )

    def import_asset(self, path: str | Path) -> MediaInfo:
        """Phase 2: probing is the import-time media operation."""
        return self.probe(path)


class MediaProcessorInterface:  # documentation alias
    """Contract: probe/import local media; rendering lives in
    ``neuralcut.backend.rendering``. Analysis is Phase 3."""
