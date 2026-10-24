"""FFmpeg render engine.

Strategy (deterministic and explainable):

1. Flatten the timeline: clips sorted by ``(timeline_start, track, id)``.
   Overlapping clips in the flattened sequence are an error (there is no
   compositing in Phase 2). Gaps become black/silent segments.
2. Render each segment with identical codec/size/fps/audio parameters.
3. Concatenate segments with the FFmpeg concat demuxer (stream copy).
4. Verify the output exists, is non-empty, and probes to the expected
   duration within tolerance.

Cancellation is cooperative at the engine level: the running ffmpeg
subprocess is terminated as soon as ``cancel_event`` is set.
"""

from __future__ import annotations

import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable

from neuralcut.backend.projects.model import ExportSettings, Project
from neuralcut.errors import NeuralCutError, ValidationError

ProgressFn = Callable[[float, str], None]


class RenderError(NeuralCutError):
    code = "render_error"
    http_status = 500


class RenderCancelled(RenderError):
    code = "render_cancelled"


def _fmt(value: float) -> str:
    return f"{value:.3f}"


class FFmpegRenderEngine:
    def __init__(self, media) -> None:  # noqa: ANN001 - MediaProcessorAdapter
        self._media = media

    # ---- public -------------------------------------------------------------

    def render(
        self,
        project: Project,
        output_path: str | Path,
        settings: ExportSettings | None = None,
        *,
        progress: ProgressFn | None = None,
        cancel_event: threading.Event | None = None,
        work_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        settings = settings or project.export_settings
        progress = progress or (lambda _v, _m: None)
        cancel_event = cancel_event or threading.Event()
        ffmpeg = self._media.require_ffmpeg()

        output_path = Path(output_path).expanduser()
        if output_path.suffix.lower() != ".mp4":
            raise ValidationError(
                "Phase 2 export supports .mp4 output only",
                details={"output_path": str(output_path)},
            )
        composite = self._needs_composite(project)
        segments_plan = self._plan_composite(project) if composite else self._plan(project)
        expected_duration = project.timeline_duration_seconds
        total_steps = len(segments_plan) + 1  # + concat

        output_path.parent.mkdir(parents=True, exist_ok=True)
        if work_dir:
            Path(work_dir).mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="neuralcut-render-", dir=str(work_dir) if work_dir else None
        ) as tmp:
            tmp_dir = Path(tmp)
            segment_files: list[Path] = []
            for index, segment in enumerate(segments_plan):
                self._check_cancel(cancel_event)
                segment_file = tmp_dir / f"segment-{index:04d}.mp4"
                if segment["kind"] == "gap":
                    cmd = self._gap_command(ffmpeg, segment_file, segment["duration"], settings)
                elif segment["kind"] == "composite":
                    cmd = self._composite_command(ffmpeg, segment_file, segment, settings)
                else:
                    cmd = self._clip_command(ffmpeg, segment_file, segment, settings)
                self._run(cmd, cancel_event, segment_desc(segment))
                segment_files.append(segment_file)
                progress(
                    (index + 1) / total_steps * 95.0,
                    f"rendered segment {index + 1} of {len(segments_plan)}",
                )

            self._check_cancel(cancel_event)
            list_file = tmp_dir / "concat.txt"
            list_file.write_text(
                "".join(f"file '{p.as_posix()}'\n" for p in segment_files), encoding="utf-8"
            )
            self._run(
                [
                    ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
                    "-c", "copy", "-movflags", "+faststart", str(output_path),
                ],
                cancel_event,
                "final concatenation",
            )
            progress(97.0, "verifying output")

        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise RenderError(f"export did not produce an output file: {output_path}")
        info = self._media.probe(output_path)
        actual = info.duration_seconds
        tolerance = max(1.0, expected_duration * 0.05)
        if actual is None or abs(actual - expected_duration) > tolerance:
            raise RenderError(
                f"exported duration {actual}s does not match expected timeline "
                f"duration {expected_duration:.3f}s (tolerance {tolerance:.2f}s)",
                details={"output_path": str(output_path), "actual_duration": actual},
            )
        progress(100.0, "export complete")
        return {
            "output_path": str(output_path),
            "expected_duration_seconds": round(expected_duration, 3),
            "actual_duration_seconds": actual,
            "segments": len(segments_plan),
            "width": settings.width,
            "height": settings.height,
            "fps": settings.fps,
            "composited": composite,
        }

    # ---- planning -----------------------------------------------------------

    def _plan(self, project: Project) -> list[dict[str, Any]]:
        if not project.clips:
            raise ValidationError("timeline is empty; add at least one clip before exporting")
        assets = {a.id: a for a in project.assets}
        ordered = sorted(
            project.clips, key=lambda c: (c.timeline_start_seconds, c.track, c.id)
        )
        plan: list[dict[str, Any]] = []
        cursor = 0.0
        for clip in ordered:
            asset = assets.get(clip.asset_id)
            if asset is None:  # model validation normally prevents this
                raise ValidationError(f"clip {clip.id} references unknown asset {clip.asset_id}")
            path = Path(asset.path)
            if not path.is_file():
                raise ValidationError(
                    f"source media is missing for clip {clip.name or clip.id}: {asset.path}",
                    details={"clip_id": clip.id, "asset_id": asset.id, "path": asset.path},
                )
            if clip.timeline_start_seconds < cursor - 1e-6:
                raise ValidationError(
                    "clips overlap in the export order (multiple tracks overlap in time); "
                    "Phase 2 export is a single flattened sequence — remove the overlap",
                    details={"clip_id": clip.id},
                )
            gap = clip.timeline_start_seconds - cursor
            if gap > 0.05:
                plan.append({"kind": "gap", "duration": gap})
            elif gap > 0:
                # Sub-frame gaps are absorbed into the previous segment timing.
                pass
            plan.append(
                {
                    "kind": "clip",
                    "clip_id": clip.id,
                    "path": str(path),
                    "source_start": clip.source_start_seconds,
                    "duration": clip.duration_seconds,
                    "has_audio": asset.has_audio,
                }
            )
            cursor = max(cursor, clip.timeline_end_seconds)
        return plan

    # ---- compositing / effects planning (Phase 4) ------------------------------

    @staticmethod
    def _needs_composite(project: Project) -> bool:
        if any(clip.effects for clip in project.clips):
            return True
        ordered = sorted(
            project.clips, key=lambda c: (c.timeline_start_seconds, c.track, c.id)
        )
        cursor = 0.0
        for clip in ordered:
            if clip.timeline_start_seconds < cursor - 1e-6:
                return True
            cursor = max(cursor, clip.timeline_end_seconds)
        return False

    def _plan_composite(self, project: Project) -> list[dict[str, Any]]:
        """Split the timeline into atomic intervals with a constant layer set.

        Layers are ordered by track (lowest first = bottom). Effects and
        keyframes are evaluated at each interval's midpoint.
        """
        if not project.clips:
            raise ValidationError("timeline is empty; add at least one clip before exporting")
        assets = {a.id: a for a in project.assets}
        for clip in project.clips:
            asset = assets.get(clip.asset_id)
            if asset is None:
                raise ValidationError(f"clip {clip.id} references unknown asset {clip.asset_id}")
            if not Path(asset.path).is_file():
                raise ValidationError(
                    f"source media is missing for clip {clip.name or clip.id}: {asset.path}",
                    details={"clip_id": clip.id, "asset_id": asset.id, "path": asset.path},
                )
        duration = project.timeline_duration_seconds
        boundaries = {0.0, duration}
        for clip in project.clips:
            boundaries.add(clip.timeline_start_seconds)
            boundaries.add(clip.timeline_end_seconds)
        ordered_bounds = sorted(boundaries)
        plan: list[dict[str, Any]] = []
        for start, end in zip(ordered_bounds, ordered_bounds[1:], strict=False):
            if end - start <= 0.01:
                continue
            mid = (start + end) / 2
            layers = []
            active = [
                c for c in project.clips
                if c.timeline_start_seconds - 1e-9 <= mid < c.timeline_end_seconds - 1e-9
                or (c.timeline_start_seconds <= mid and c.timeline_end_seconds > mid)
            ]
            for clip in sorted(active, key=lambda c: (c.track, c.timeline_start_seconds, c.id)):
                asset = assets[clip.asset_id]
                offset = start - clip.timeline_start_seconds
                layers.append({
                    "clip_id": clip.id,
                    "path": asset.path,
                    "source_start": clip.source_start_seconds + max(offset, 0.0),
                    "has_audio": asset.has_audio,
                    "effects": clip.effects,
                    "clip_local_t": (mid - clip.timeline_start_seconds),
                })
            plan.append({"kind": "composite", "duration": end - start, "layers": layers})
        return plan

    def _composite_command(self, ffmpeg: str, out: Path, segment: dict[str, Any],
                           settings: ExportSettings) -> list[str]:
        from neuralcut.backend.effects.engine import transform_params, video_filter_chain

        duration = _fmt(segment["duration"])
        width, height = settings.width, settings.height
        cmd = [ffmpeg, "-y", "-f", "lavfi", "-t", duration, "-i",
               f"color=c=black:s={width}x{height}:r={settings.fps}"]
        # inputs: 0 = black base; then per layer a video input (+ audio input
        # or a silence input). Track indices explicitly.
        layer_inputs: list[tuple[int, int]] = []  # (video_idx, audio_idx)
        next_index = 1
        for layer in segment["layers"]:
            video_idx = next_index
            cmd += ["-ss", _fmt(layer["source_start"]), "-i", layer["path"], "-t", duration]
            next_index += 1
            if layer["has_audio"]:
                audio_idx = video_idx
            else:
                audio_idx = next_index
                cmd += ["-f", "lavfi", "-t", duration, "-i", "anullsrc=r=48000:cl=stereo"]
                next_index += 1
            layer_inputs.append((video_idx, audio_idx))
        if not segment["layers"]:
            silence_idx = next_index
            cmd += ["-f", "lavfi", "-t", duration, "-i", "anullsrc=r=48000:cl=stereo"]
            layer_inputs = []
        else:
            silence_idx = -1

        filters: list[str] = ["[0:v]format=yuv420p,setsar=1[acc0]"]
        audio_labels: list[str] = []
        current = "[acc0]"
        for j, (layer, (video_idx, audio_idx)) in enumerate(
            zip(segment["layers"], layer_inputs, strict=True)
        ):
            chain, chained = video_filter_chain(
                layer["effects"], layer["clip_local_t"], f"[{video_idx}:v]", width, height
            )
            if chain:
                filters.append(chain)
            transform = transform_params(layer["effects"], layer["clip_local_t"])
            sw = max(2, int(width * transform["scale"]) // 2 * 2)
            sh = max(2, int(height * transform["scale"]) // 2 * 2)
            filters.append(
                f"{chained}scale={sw}:{sh},format=rgba,"
                f"colorchannelmixer=aa={transform['opacity']:.4f}[fg{j}]"
            )
            target = f"[acc{j + 1}]"
            filters.append(
                f"{current}[fg{j}]overlay="
                f"x='(main_w-overlay_w)/2+{transform['x']:.4f}*(main_w-overlay_w)/2'"
                f":y='(main_h-overlay_h)/2+{transform['y']:.4f}*(main_h-overlay_h)/2'"
                f"{target}"
            )
            current = target
            audio_labels.append(f"[a{j}]")
            filters.append(f"[{audio_idx}:a]aresample=48000{audio_labels[-1]}")
        # Bound the segment explicitly: some filter/ffmpeg-version
        # combinations (framesync filters on ffmpeg 8) otherwise emit
        # runaway video durations. trim/atrim + an output -t make every
        # segment exactly the planned length on every build.
        filters.append(
            f"{current}format=yuv420p,setsar=1,fps={settings.fps},"
            f"trim=duration={duration},setpts=PTS-STARTPTS[vout]"
        )
        if audio_labels:
            if len(audio_labels) == 1:
                filters.append(f"{audio_labels[0]}anull[apre]")
            else:
                filters.append(
                    f"{''.join(audio_labels)}amix=inputs={len(audio_labels)}"
                    f":duration=first:dropout_transition=0[apre]"
                )
        else:
            filters.append(f"[{silence_idx}:a]anull[apre]")
        filters.append(f"[apre]atrim=duration={duration},asetpts=PTS-STARTPTS[aout]")
        cmd += ["-filter_complex", ";".join(filters), "-map", "[vout]", "-map", "[aout]"]
        cmd += self._encode_args(settings)
        cmd += ["-t", duration, str(out)]
        return cmd

    # ---- ffmpeg commands ------------------------------------------------------

    @staticmethod
    def _video_filter(settings: ExportSettings) -> str:
        return (
            f"scale={settings.width}:{settings.height}:force_original_aspect_ratio=decrease,"
            f"pad={settings.width}:{settings.height}:(ow-iw)/2:(oh-ih)/2:black,"
            f"fps={settings.fps},format=yuv420p,setsar=1"
        )

    def _encode_args(self, settings: ExportSettings) -> list[str]:
        return [
            "-c:v", "libx264", "-preset", settings.preset, "-crf", str(settings.crf),
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
            "-video_track_timescale", "90000",
        ]

    def _clip_command(
        self, ffmpeg: str, out: Path, segment: dict[str, Any], settings: ExportSettings
    ) -> list[str]:
        duration = _fmt(segment["duration"])
        cmd = [
            ffmpeg, "-y",
            "-ss", _fmt(segment["source_start"]), "-i", segment["path"],
            "-t", duration,
        ]
        if not segment["has_audio"]:
            cmd += ["-f", "lavfi", "-t", duration, "-i", "anullsrc=r=48000:cl=stereo"]
        cmd += ["-map", "0:v:0"]
        if segment["has_audio"]:
            cmd += ["-map", "0:a:0"]
        else:
            cmd += ["-map", "1:a:0"]
        cmd += ["-vf", self._video_filter(settings)]
        if segment["has_audio"]:
            cmd += ["-af", "aresample=48000"]
        cmd += self._encode_args(settings)
        cmd += ["-shortest", str(out)]
        return cmd

    def _gap_command(
        self, ffmpeg: str, out: Path, duration: float, settings: ExportSettings
    ) -> list[str]:
        dur = _fmt(duration)
        return [
            ffmpeg, "-y",
            "-f", "lavfi", "-t", dur,
            "-i", f"color=c=black:s={settings.width}x{settings.height}:r={settings.fps}",
            "-f", "lavfi", "-t", dur, "-i", "anullsrc=r=48000:cl=stereo",
            "-map", "0:v:0", "-map", "1:a:0",
            "-vf", "format=yuv420p,setsar=1",
            *self._encode_args(settings),
            str(out),
        ]

    # ---- process handling -------------------------------------------------------

    @staticmethod
    def _check_cancel(cancel_event: threading.Event) -> None:
        if cancel_event.is_set():
            raise RenderCancelled("render cancelled")

    def _run(self, cmd: list[str], cancel_event: threading.Event, what: str) -> None:
        # stderr goes to a temp file, not a pipe: ffmpeg logs verbosely and
        # would deadlock on a full pipe buffer while we poll for cancellation
        # (observed as a hang on Windows runners).
        with tempfile.TemporaryFile(mode="w+") as stderr_file:
            proc = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
                cmd, stdout=subprocess.DEVNULL, stderr=stderr_file, text=True
            )
            while proc.poll() is None:
                if cancel_event.is_set():
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5)
                    raise RenderCancelled(f"render cancelled during {what}")
                cancel_event.wait(0.05)
            if proc.returncode != 0:
                stderr_file.seek(0)
                tail = stderr_file.read().strip().splitlines()[-8:]
                raise RenderError(
                    f"ffmpeg failed during {what}: {' | '.join(tail) or 'unknown error'}",
                    details={"step": what, "returncode": proc.returncode},
                )


def segment_desc(segment: dict[str, Any]) -> str:
    if segment["kind"] == "composite":
        return f"composite segment ({len(segment.get('layers', []))} layer(s))"
    if segment["kind"] == "gap":
        return f"gap segment ({segment['duration']:.2f}s)"
    return f"clip segment {segment.get('clip_id', '')}"


def register_render_jobs(job_manager, container) -> None:  # noqa: ANN001
    """Register the ``render`` job type bound to a container's services."""

    def render_job(job, *, progress, cancel_event, project, output_path, settings=None, **_ignored):
        project_model = Project.model_validate(project)
        export = (
            ExportSettings.model_validate(settings)
            if settings
            else project_model.export_settings
        )
        work_dir = container.context.data_dir / "render-tmp"
        work_dir.mkdir(parents=True, exist_ok=True)
        return container.render_engine.render(
            project_model,
            output_path,
            export,
            progress=progress,
            cancel_event=cancel_event,
            work_dir=work_dir,
        )

    job_manager.register_job_type("render", render_job)
