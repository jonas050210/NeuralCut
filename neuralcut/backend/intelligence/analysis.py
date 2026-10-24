"""Asset analysis: shots, speech segments, retrieval index, object tracks.

Artifacts are *derived data*: versioned JSON documents stored under
``<data_dir>/analysis/`` keyed by a content fingerprint of the source file
(size + sampled chunk hashes + mtime). They are never written into the
project document, are reused when the fingerprint is unchanged, and are
invalidated automatically when the source file changes. Analysis never
mutates the timeline.

Everything here runs on CPU with ffmpeg + the standard library. Speech
*transcription* (words) needs an optional ASR engine: when
``faster-whisper`` is installed and models are enabled in settings, it is
used; otherwise the transcript artifact honestly reports ``unavailable``
while deterministic speech/silence segments are still produced.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from neuralcut.backend.intelligence.detection import detect_and_track
from neuralcut.errors import ValidationError

ANALYSIS_VERSION = 1
ANALYSIS_WIDTH = 96
ANALYSIS_HEIGHT = 54

ProgressFn = Callable[[float, str], None]


def file_fingerprint(path: Path) -> str:
    stat = path.stat()
    digest = hashlib.sha256()
    digest.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode())
    with path.open("rb") as fh:
        digest.update(fh.read(65536))
        if stat.st_size > 131072:
            fh.seek(max(0, stat.st_size - 65536))
            digest.update(fh.read(65536))
    return digest.hexdigest()[:32]


class AnalysisStore:
    """JSON artifact store keyed by (asset fingerprint)."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, fingerprint: str) -> Path:
        return self.directory / f"{fingerprint}.json"

    def load(self, fingerprint: str) -> dict[str, Any] | None:
        path = self._path(fingerprint)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if data.get("version") != ANALYSIS_VERSION:
            return None
        return data

    def save(self, artifact: dict[str, Any]) -> Path:
        path = self._path(artifact["fingerprint"])
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
        return path


class AnalysisService:
    def __init__(self, store: AnalysisStore, media, settings=None) -> None:  # noqa: ANN001
        self.store = store
        self.media = media
        self.settings = settings

    # ---- cache ---------------------------------------------------------------

    def cached(self, asset) -> dict[str, Any] | None:  # noqa: ANN001
        path = Path(asset.path)
        if not path.is_file():
            return None
        artifact = self.store.load(file_fingerprint(path))
        if artifact and artifact.get("asset_id") == asset.id:
            return artifact
        return None

    def status(self, asset) -> dict[str, Any]:  # noqa: ANN001
        artifact = self.cached(asset)
        if artifact is None:
            return {"status": "none", "asset_id": asset.id}
        return {
            "status": "ready",
            "asset_id": asset.id,
            "analyzed_at": artifact["analyzed_at"],
            "version": artifact["version"],
            "shots": len(artifact["shots"]),
            "tracks": len(artifact["tracks"]),
            "transcript_status": artifact["transcript"]["status"],
        }

    # ---- main entry ------------------------------------------------------------

    def analyze(self, asset, *, force: bool = False,  # noqa: ANN001
                progress: ProgressFn | None = None,
                cancel_event: threading.Event | None = None) -> dict[str, Any]:
        progress = progress or (lambda _v, _m: None)
        cancel_event = cancel_event or threading.Event()
        path = Path(asset.path)
        if not path.is_file():
            raise ValidationError(
                f"source media is missing: {asset.path}", details={"asset_id": asset.id}
            )
        fingerprint = file_fingerprint(path)
        if not force:
            existing = self.store.load(fingerprint)
            if existing and existing.get("asset_id") == asset.id:
                existing = dict(existing)
                existing["from_cache"] = True
                return existing

        info = self.media.probe(path)
        duration = info.duration_seconds or 0.0
        progress(5, "probing media")

        self._check_cancel(cancel_event)
        shots = self._detect_shots(path, duration)
        progress(20, f"detected {len(shots)} shot(s)")

        frames, times = self._extract_gray_frames(path, duration)
        self._check_cancel(cancel_event)
        motion = self._shot_motion(frames, times, shots, duration)
        for shot, level in zip(shots, motion, strict=False):
            shot["motion_level"] = level
        progress(40, "computed shot motion")

        tracks = []
        if frames:
            tracks = detect_and_track(
                frames,
                width=ANALYSIS_WIDTH,
                height=ANALYSIS_HEIGHT,
                times=times,
                source_width=info.width or ANALYSIS_WIDTH,
                source_height=info.height or ANALYSIS_HEIGHT,
            )
        progress(65, f"tracked {len(tracks)} moving object(s)")

        for shot in shots:
            embedding, dominant = self._shot_embedding(path, shot)
            shot["embedding"] = embedding
            shot["dominant_color"] = dominant
            motion_word = (
                "high" if shot.get("motion_level", 0) > 12
                else "moderate" if shot.get("motion_level", 0) > 4 else "low"
            )
            shot["caption"] = (
                f"Shot {shot['index'] + 1}: predominantly {dominant}, {motion_word} motion "
                f"({shot['start_seconds']:.1f}s-{shot['end_seconds']:.1f}s)"
            )
        progress(80, "built retrieval index")

        speech_segments = self._speech_segments(path) if info.has_audio else []
        transcript = self._transcribe(path, speech_segments)
        progress(95, "finished audio analysis")

        artifact = {
            "version": ANALYSIS_VERSION,
            "asset_id": asset.id,
            "asset_path": str(path),
            "fingerprint": fingerprint,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": duration,
            "shots": shots,
            "tracks": tracks,
            "speech_segments": speech_segments,
            "transcript": transcript,
            "from_cache": False,
        }
        self.store.save(artifact)
        progress(100, "analysis complete")
        return artifact

    # ---- steps -------------------------------------------------------------------

    @staticmethod
    def _check_cancel(cancel_event: threading.Event) -> None:
        if cancel_event.is_set():
            raise ValidationError("analysis cancelled")

    def _run_ffmpeg(self, cmd: list[str]) -> tuple[int, str, bytes]:
        with subprocess.Popen(  # noqa: S603 - fixed argv
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        ) as proc:
            out, err = proc.communicate(timeout=600)
        return proc.returncode, err.decode("utf-8", errors="replace"), out

    def _detect_shots(self, path: Path, duration: float) -> list[dict[str, Any]]:
        ffmpeg = self.media.require_ffmpeg()
        _rc, stderr, _out = self._run_ffmpeg([
            ffmpeg, "-hide_banner", "-i", str(path),
            "-filter:v", "select='gt(scene,0.4)',showinfo",
            "-f", "null", "-",
        ])
        cuts = [0.0]
        for match in re.finditer(r"pts_time:([0-9.]+)", stderr):
            t = float(match.group(1))
            if 0.05 < t < max(duration - 0.05, 0.05):
                cuts.append(round(t, 3))
        cuts = sorted(set(cuts))
        shots = []
        for index, start in enumerate(cuts):
            end = cuts[index + 1] if index + 1 < len(cuts) else duration
            shots.append({
                "index": index,
                "start_seconds": round(start, 3),
                "end_seconds": round(end, 3),
                "duration_seconds": round(end - start, 3),
            })
        return shots or [{
            "index": 0, "start_seconds": 0.0,
            "end_seconds": duration, "duration_seconds": duration,
        }]

    def _extract_gray_frames(self, path: Path, duration: float) -> tuple[list[bytes], list[float]]:
        if duration <= 0:
            return [], []
        ffmpeg = self.media.require_ffmpeg()
        sample_fps = 5.0
        frame_count = min(int(duration * sample_fps) + 1, 300)
        _rc, _err, out = self._run_ffmpeg([
            ffmpeg, "-hide_banner", "-v", "error", "-i", str(path),
            "-vf", f"fps={sample_fps},scale={ANALYSIS_WIDTH}:{ANALYSIS_HEIGHT}",
            "-frames:v", str(frame_count),
            "-f", "rawvideo", "-pix_fmt", "gray", "-",
        ])
        size = ANALYSIS_WIDTH * ANALYSIS_HEIGHT
        frames = [out[i:i + size] for i in range(0, len(out) - size + 1, size)]
        times = [round(i / sample_fps, 3) for i in range(len(frames))]
        return frames, times

    @staticmethod
    def _shot_motion(frames: list[bytes], times: list[float],
                     shots: list[dict[str, Any]], duration: float) -> list[float]:
        diffs: list[tuple[float, float]] = []
        for i in range(1, len(frames)):
            a, b = frames[i - 1], frames[i]
            step = min(len(a), len(b)) // 16 or 1
            total = sum(abs(a[j] - b[j]) for j in range(0, min(len(a), len(b)), step))
            count = len(range(0, min(len(a), len(b)), step)) or 1
            diffs.append((times[i], total / count))
        levels = []
        for shot in shots:
            values = [v for t, v in diffs if shot["start_seconds"] <= t < shot["end_seconds"]]
            levels.append(round(sum(values) / len(values), 3) if values else 0.0)
        return levels

    def _shot_embedding(self, path: Path, shot: dict[str, Any]) -> tuple[list[float], str]:
        ffmpeg = self.media.require_ffmpeg()
        mid = (shot["start_seconds"] + shot["end_seconds"]) / 2
        _rc, _err, out = self._run_ffmpeg([
            ffmpeg, "-hide_banner", "-v", "error", "-ss", f"{mid:.3f}", "-i", str(path),
            "-frames:v", "1", "-vf", "scale=32:32", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        ])
        bins = [0.0] * 12  # 4 red x 3 (green/blue folded by dominant channel counts)
        colors = {"red": 0, "green": 0, "blue": 0, "dark": 0, "bright": 0}
        pixels = max(len(out) // 3, 1)
        for i in range(0, len(out) - 2, 3):
            r, g, b = out[i], out[i + 1], out[i + 2]
            bins[(r // 64) * 3 + (0 if g >= b else 1)] += 1
            if r > g and r > b:
                colors["red"] += 1
            elif g > r and g > b:
                colors["green"] += 1
            elif b > r and b > g:
                colors["blue"] += 1
            if (r + g + b) / 3 < 40:
                colors["dark"] += 1
            if (r + g + b) / 3 > 210:
                colors["bright"] += 1
        embedding = [round(v / pixels, 5) for v in bins]
        norm = math.sqrt(sum(v * v for v in embedding)) or 1.0
        embedding = [round(v / norm, 5) for v in embedding]
        special = max(("dark", "bright"), key=lambda k: colors[k])
        dominant = special if colors[special] > pixels * 0.5 else max(
            ("red", "green", "blue"), key=lambda k: colors[k])
        return embedding, dominant

    def _speech_segments(self, path: Path) -> list[dict[str, Any]]:
        ffmpeg = self.media.require_ffmpeg()
        _rc, stderr, _out = self._run_ffmpeg([
            ffmpeg, "-hide_banner", "-i", str(path),
            "-af", "silencedetect=noise=-40dB:d=0.6", "-f", "null", "-",
        ])
        silences: list[tuple[float, float]] = []
        starts = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", stderr)]
        ends = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", stderr)]
        silences = list(zip(starts, ends, strict=False))
        info = self.media.probe(path)
        duration = info.duration_seconds or (ends[-1] if ends else 0.0)
        segments: list[dict[str, Any]] = []
        cursor = 0.0
        for s_start, s_end in silences:
            if s_start > cursor + 0.1:
                segments.append({
                    "start_seconds": round(cursor, 3), "end_seconds": round(s_start, 3),
                    "kind": "speech_or_sound",
                })
            cursor = max(cursor, s_end)
        if duration > cursor + 0.1:
            segments.append({
                "start_seconds": round(cursor, 3), "end_seconds": round(duration, 3),
                "kind": "speech_or_sound",
            })
        return segments

    def _transcribe(self, path: Path, speech_segments: list[dict[str, Any]]) -> dict[str, Any]:
        enabled = bool(getattr(self.settings, "models", None) and self.settings.models.enabled)
        if not enabled:
            return {
                "status": "unavailable",
                "reason": "AI models are disabled (models.enabled=false); "
                          "deterministic speech segments are available instead",
                "segments": [],
            }
        try:
            from faster_whisper import WhisperModel  # noqa: PLC0415 - optional dep
        except ImportError:
            return {
                "status": "unavailable",
                "reason": "optional dependency faster-whisper is not installed",
                "segments": [],
            }
        try:  # pragma: no cover - requires an optional model download
            model = WhisperModel("tiny", device="cpu", compute_type="int8")
            segments, _info = model.transcribe(str(path), word_timestamps=True)
            out = []
            for seg in segments:
                out.append({
                    "start_seconds": round(seg.start, 3),
                    "end_seconds": round(seg.end, 3),
                    "text": seg.text.strip(),
                    "words": [
                        {"word": w.word, "start_seconds": round(w.start, 3),
                         "end_seconds": round(w.end, 3)}
                        for w in (seg.words or [])
                    ],
                })
            return {"status": "ready", "engine": "faster-whisper(tiny/cpu)", "segments": out}
        except Exception as exc:  # noqa: BLE001 - report, don't crash analysis
            return {"status": "failed", "reason": f"{type(exc).__name__}: {exc}", "segments": []}


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=False))


def register_analysis_jobs(job_manager, container) -> None:  # noqa: ANN001
    """Register the ``analysis`` job type bound to a container."""

    def analysis_job(job, *, progress, cancel_event, asset, force=False, **_ignored):
        from neuralcut.backend.projects.model import ProjectAsset

        asset_model = ProjectAsset.model_validate(asset)
        return container.analysis_service.analyze(
            asset_model, force=bool(force), progress=progress, cancel_event=cancel_event
        )

    job_manager.register_job_type("analysis", analysis_job)
