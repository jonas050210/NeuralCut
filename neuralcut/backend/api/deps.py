"""API dependencies: provides the shared :class:`Container` to route handlers."""

from __future__ import annotations

from fastapi import Request

from neuralcut.backend.di import Container


def get_container(request: Request) -> Container:
    container = request.app.state.container
    if container is None:  # pragma: no cover - defensive
        raise RuntimeError("backend container not initialized")
    return container
