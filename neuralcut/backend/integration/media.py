"""Media processing extension point (Phase 2+).

Phase 1 does not implement import, analysis, or rendering. This adapter
declares the interface and reports availability (e.g. ffmpeg on PATH) without
touching any media files.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from neuralcut.backend.di import Container

import shutil

from neuralcut.errors import UnavailableError


class MediaProcessorAdapter:
    """No-op in Phase 1. Later phases: import, transcode, analyze, render."""

    def __init__(self, container: "Container") -> None:
        self.container = container
        self.ffmpeg_path = container.settings.media.ffmpeg_path or shutil.which("ffmpeg")
        self.ffprobe_path = container.settings.media.probe_path or shutil.which("ffprobe")

    def status(self) -> dict:
        return {
            "available": False,
            "reason": "media processing is a Phase 2 extension point",
            "ffmpeg": self.ffmpeg_path,
            "ffprobe": self.ffprobe_path,
        }

    def import_asset(self, *args, **kwargs):  # noqa: ARG002
        raise UnavailableError(
            "media import is not implemented in Phase 1",
            details={"feature": "media.import", "phase": 2},
        )


class MediaProcessorInterface:  # documentation alias
    """Contract for Phase 2+:

    - import_asset(path) -> asset_id
    - analyze_asset(asset_id) -> shot list, transcript, embeddings
    - render(project) -> output file
    """
