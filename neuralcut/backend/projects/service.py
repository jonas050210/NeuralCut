"""Project service: create, open, save, close, recent-project tracking."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from neuralcut.backend.projects.model import Project
from neuralcut.backend.projects.store import ProjectStore
from neuralcut.errors import ConflictError, NotFoundError, ProjectError, ValidationError


class ProjectService:
    def __init__(
        self,
        recent: list[str] | None = None,
        on_recent_changed: Callable[[list[str]], None] | None = None,
    ) -> None:
        self._project: Project | None = None
        self._path: Path | None = None
        self.recent: list[str] = list(recent or [])[:50]
        self.on_recent_changed = on_recent_changed

    # ---- lifecycle --------------------------------------------------------

    def create(self, name: str, directory: str | Path) -> Project:
        import uuid

        if not name or not name.strip():
            raise ValidationError("project name must not be empty")
        if not str(directory).strip():
            raise ValidationError("project directory must not be empty")
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(c for c in name if c.isalnum() or c in (" ", "-", "_")).strip()
        if not safe_name:
            safe_name = "Untitled"
        path = directory / f"{safe_name}.neuralcut"
        if path.exists():
            raise ConflictError(
                f"project already exists: {path}",
                details={"path": str(path)},
            )
        project = Project(id=uuid.uuid4().hex, name=name.strip())
        saved_path = self.save(project, path)
        self._project = project
        self._path = saved_path
        self._add_recent(str(saved_path))
        return project

    def open(self, path: str | Path) -> Project:
        path = Path(path)
        project = ProjectStore.load(path)
        self._project = project
        self._path = path
        self._add_recent(str(path))
        return project

    def save(self, project: Project | None = None, path: str | Path | None = None) -> Path:
        target = Path(path) if path else self._path
        if target is None:
            raise ProjectError("no project path to save to")
        proj = project if project is not None else self._project
        if proj is None:
            raise NotFoundError("no project is open")
        return ProjectStore.save(proj, target)

    def get(self) -> Project:
        if self._project is None:
            raise NotFoundError("no project is open")
        return self._project

    def current_path(self) -> Path | None:
        return self._path

    def close(self) -> None:
        self._project = None
        self._path = None

    # ---- recent projects --------------------------------------------------

    def _add_recent(self, path: str) -> None:
        self.recent = [p for p in self.recent if p != path]
        self.recent.insert(0, path)
        self.recent = self.recent[:50]
        if self.on_recent_changed is not None:
            self.on_recent_changed(list(self.recent))

    def recent_projects(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for path in self.recent:
            p = Path(path)
            out.append({"path": str(p), "exists": p.exists(), "name": p.stem})
        return out
