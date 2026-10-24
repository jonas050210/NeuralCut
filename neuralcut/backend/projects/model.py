"""Project data model and versioning (schema v2 — Phase 2 editing core).

Project files are JSON with an explicit schema version. Loading validates the
version, migrates older raw documents, and only then validates with Pydantic;
writing is atomic (temp file + replace).

Schema history:
- v1 (Phase 1): asset/clip references only (``start_seconds``/``end_seconds``).
- v2 (Phase 2): timeline clips with ``timeline_start_seconds``,
  ``source_start_seconds``/``source_end_seconds``, names, and probed asset
  metadata (dimensions, fps, audio presence, codec).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: Current on-disk schema version.
PROJECT_SCHEMA_VERSION = 2

_VALID_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


def _validate_id(value: str) -> str:
    if not _VALID_ID.match(value):
        raise ValueError(f"invalid id: {value!r}")
    return value


class ProjectAsset(BaseModel):
    """A reference to a local source media file plus probed metadata."""

    model_config = ConfigDict(validate_assignment=True)

    id: str
    name: str = Field(min_length=1)
    path: str = Field(min_length=1)
    kind: str = Field(default="video", pattern=r"^(video|audio|image)$")
    duration_seconds: float | None = Field(default=None, ge=0)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    fps: float | None = Field(default=None, gt=0)
    has_audio: bool = False
    codec: str | None = None
    added_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return _validate_id(value)


class ProjectClip(BaseModel):
    """A clip placed on the timeline.

    ``timeline_start_seconds`` is where the clip begins in the edited output;
    ``source_start_seconds``/``source_end_seconds`` select the range inside
    the source asset. Duration is always ``source_end - source_start`` — the
    editing core does not support speed changes yet.
    """

    model_config = ConfigDict(validate_assignment=True)

    id: str
    asset_id: str = Field(min_length=1)
    name: str = Field(default="", max_length=200)
    track: int = Field(default=0, ge=0)
    timeline_start_seconds: float = Field(default=0.0, ge=0)
    source_start_seconds: float = Field(default=0.0, ge=0)
    source_end_seconds: float = Field(gt=0)

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return _validate_id(value)

    @model_validator(mode="after")
    def _validate_range(self) -> "ProjectClip":
        if self.source_end_seconds <= self.source_start_seconds:
            raise ValueError("source_end_seconds must be > source_start_seconds")
        return self

    @property
    def duration_seconds(self) -> float:
        return self.source_end_seconds - self.source_start_seconds

    @property
    def timeline_end_seconds(self) -> float:
        return self.timeline_start_seconds + self.duration_seconds


class ExportSettings(BaseModel):
    """Default/last-used export settings stored with the project."""

    model_config = ConfigDict(validate_assignment=True)

    width: int = Field(default=1280, ge=16, le=7680)
    height: int = Field(default=720, ge=16, le=4320)
    fps: float = Field(default=30.0, gt=0, le=240)
    crf: int = Field(default=23, ge=0, le=51)
    preset: str = Field(
        default="veryfast",
        pattern=r"^(ultrafast|superfast|veryfast|faster|fast|medium|slow|slower|veryslow)$",
    )


class Project(BaseModel):
    """Top-level project document (schema v2)."""

    model_config = ConfigDict(validate_assignment=True)

    version: int = Field(default=PROJECT_SCHEMA_VERSION, ge=1)
    id: str
    name: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    modified_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    assets: list[ProjectAsset] = Field(default_factory=list)
    clips: list[ProjectClip] = Field(default_factory=list)
    export_settings: ExportSettings = Field(default_factory=ExportSettings)
    settings: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", "name")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("must not be empty")
        return value.strip()

    @model_validator(mode="after")
    def _validate_timeline(self) -> "Project":
        asset_ids = [a.id for a in self.assets]
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("duplicate asset ids")
        clip_ids = [c.id for c in self.clips]
        if len(clip_ids) != len(set(clip_ids)):
            raise ValueError("duplicate clip ids")
        known = set(asset_ids)
        for clip in self.clips:
            if clip.asset_id not in known:
                raise ValueError(f"clip {clip.id} references unknown asset {clip.asset_id}")
        # Clips on the same track must not overlap (gaps are allowed).
        by_track: dict[int, list[ProjectClip]] = {}
        for clip in self.clips:
            by_track.setdefault(clip.track, []).append(clip)
        for track, clips in by_track.items():
            ordered = sorted(clips, key=lambda c: (c.timeline_start_seconds, c.id))
            for prev, cur in zip(ordered, ordered[1:], strict=False):
                if cur.timeline_start_seconds < prev.timeline_end_seconds - 1e-9:
                    raise ValueError(
                        f"clips {prev.id} and {cur.id} overlap on track {track}"
                    )
        return self

    @property
    def timeline_duration_seconds(self) -> float:
        return max((c.timeline_end_seconds for c in self.clips), default=0.0)

    def touch(self) -> None:
        self.modified_at = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Migrations. Migrations operate on the *raw JSON dict* so old field names
# survive until they are translated; the store migrates before validation.
# ---------------------------------------------------------------------------

RAW_MIGRATIONS: dict[int, tuple[int, Any]] = {}


def register_migration(version_from: int, version_to: int):
    def decorator(func):
        RAW_MIGRATIONS[version_from] = (version_to, func)
        return func

    return decorator


@register_migration(1, 2)
def _migrate_v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    """v1 clips (source start/end only) are placed sequentially per track."""
    data = dict(data)
    assets = []
    for asset in data.get("assets", []):
        asset = dict(asset)
        asset.setdefault("kind", "video")
        assets.append(asset)
    data["assets"] = assets

    cursors: dict[int, float] = {}
    clips = []
    for index, raw_clip in enumerate(data.get("clips", [])):
        clip = dict(raw_clip)
        source_start = float(clip.pop("start_seconds", 0.0) or 0.0)
        source_end = float(clip.pop("end_seconds", source_start) or source_start)
        if source_end <= source_start:
            source_end = source_start + 1.0
        track = int(clip.get("track", 0))
        start = cursors.get(track, 0.0)
        clip.update(
            {
                "name": clip.get("name") or f"Clip {index + 1}",
                "track": track,
                "timeline_start_seconds": start,
                "source_start_seconds": source_start,
                "source_end_seconds": source_end,
            }
        )
        cursors[track] = start + (source_end - source_start)
        clips.append(clip)
    data["clips"] = clips
    data.setdefault("export_settings", {})
    data["version"] = 2
    return data


def migrate_data(
    data: dict[str, Any], target_version: int = PROJECT_SCHEMA_VERSION
) -> dict[str, Any]:
    """Apply raw-dict migrations until ``target_version`` is reached."""
    current = int(data.get("version", 1))
    visited: set[int] = set()
    while current < target_version:
        if current in visited:
            raise ValueError(f"migration cycle detected at version {current}")
        visited.add(current)
        if current not in RAW_MIGRATIONS:
            raise ValueError(
                f"no migration from schema version {current} to {target_version}"
            )
        to_version, func = RAW_MIGRATIONS[current]
        data = func(data)
        current = to_version
    return data


# Backwards-compatible alias (Phase 1 name).
def migrate(
    project_dict: dict[str, Any], target_version: int = PROJECT_SCHEMA_VERSION
) -> dict[str, Any]:
    return migrate_data(project_dict, target_version)
