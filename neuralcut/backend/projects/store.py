"""Project persistence: atomic JSON save, validated load, versioning.

Projects are single JSON files (human readable, diff-friendly). Write uses a
temporary file in the same directory followed by an atomic replace, so a crash
mid-write never leaves a half-written project.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from neuralcut.backend.projects.model import (
    PROJECT_SCHEMA_VERSION,
    Project,
    migrate_data,
)
from neuralcut.errors import ProjectError, ValidationError


class ProjectStore:
    """Reads and writes :class:`Project` documents to JSON files."""

    @staticmethod
    def save(project: Project, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        project.touch()
        data = project.model_dump(mode="json", exclude_none=False)

        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, sort_keys=True)
                fh.write("\n")
            os.replace(tmp_name, path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        return path

    @staticmethod
    def load(path: str | Path) -> Project:
        path = Path(path)
        if not path.is_file():
            raise ProjectError(f"project file not found: {path}", http_status=404)
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ProjectError(f"could not read project file: {exc}") from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValidationError(
                f"project file is not valid JSON: {exc}",
                details={"file": str(path)},
            ) from exc

        if not isinstance(data, dict):
            raise ValidationError(
                "project document must be a JSON object",
                details={"file": str(path)},
            )

        raw_version = data.get("version", PROJECT_SCHEMA_VERSION)
        if not isinstance(raw_version, int) or isinstance(raw_version, bool):
            raise ValidationError(
                "project schema version must be an integer",
                details={"file": str(path), "version": raw_version},
            )
        if raw_version > PROJECT_SCHEMA_VERSION:
            raise ProjectError(
                f"project schema version {raw_version} is newer than supported "
                f"({PROJECT_SCHEMA_VERSION}) — update NeuralCut",
                details={"file": str(path), "version": raw_version},
            )

        if raw_version < PROJECT_SCHEMA_VERSION:
            try:
                data = migrate_data(data, PROJECT_SCHEMA_VERSION)
            except ValueError as exc:
                raise ProjectError(
                    str(exc),
                    details={"file": str(path), "version": raw_version},
                ) from exc

        try:
            project = Project.model_validate(data)
        except Exception as exc:  # pydantic.ValidationError
            raise ValidationError(
                f"project data validation failed: {exc}",
                details={"file": str(path)},
            ) from exc

        return project
