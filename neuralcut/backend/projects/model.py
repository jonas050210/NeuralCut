"""Project data model and versioning.

Project files are JSON with an explicit schema version. Loading validates the
version and runs registered migrations; writing is atomic (temp file + replace).

This is the deterministic backbone of the project — versionable, auditable, and
free of any AI or media processing logic.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: Current on-disk schema version. Bump when the model changes and add a
#: migration function to ``MIGRATIONS``.
PROJECT_SCHEMA_VERSION = 1

_VALID_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


class ProjectAsset(BaseModel):
    """A reference to a source media file (analysis-only metadata in Phase 1)."""

    model_config = ConfigDict(validate_assignment=True)

    id: str
    name: str = Field(min_length=1)
    path: str = Field(min_length=1)
    duration_seconds: float | None = Field(default=None, ge=0)
    added_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        if not _VALID_ID.match(value):
            raise ValueError(f"invalid asset id: {value!r}")
        return value


class ProjectClip(BaseModel):
    """A reference into an asset on a track (no timeline rendering yet)."""

    model_config = ConfigDict(validate_assignment=True)

    id: str
    asset_id: str = Field(min_length=1)
    track: int = Field(default=1, ge=0)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        if not _VALID_ID.match(value):
            raise ValueError(f"invalid clip id: {value!r}")
        return value

    @model_validator(mode="after")
    def _validate_range(self) -> "ProjectClip":
        if self.end_seconds < self.start_seconds:
            raise ValueError("end_seconds must be >= start_seconds")
        return self


class Project(BaseModel):
    """Top-level project document."""

    model_config = ConfigDict(validate_assignment=True)

    version: int = Field(default=PROJECT_SCHEMA_VERSION, ge=1)
    id: str
    name: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    modified_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    assets: list[ProjectAsset] = Field(default_factory=list)
    clips: list[ProjectClip] = Field(default_factory=list)
    settings: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", "name")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("must not be empty")
        return value.strip()

    def touch(self) -> None:
        self.modified_at = datetime.now(timezone.utc).isoformat()


# Migration registry: version_from -> (version_to, migration_func)
MIGRATIONS: dict[int, tuple[int, callable]] = {}  # type: ignore[assignment]


def register_migration(version_from: int, version_to: int) -> callable:
    def decorator(func: callable) -> callable:
        MIGRATIONS[version_from] = (version_to, func)
        return func

    return decorator


def migrate(project: Project, target_version: int = PROJECT_SCHEMA_VERSION) -> Project:
    """Apply migrations until ``target_version`` is reached."""
    current = project.version
    visited: set[int] = set()
    while current < target_version:
        if current in visited:
            raise ValueError(f"migration cycle detected at version {current}")
        visited.add(current)
        if current not in MIGRATIONS:
            raise ValueError(
                f"no migration from project schema version {current} to {target_version}"
            )
        to_version, func = MIGRATIONS[current]
        project = func(project)
        project.version = to_version
        current = to_version
    return project
