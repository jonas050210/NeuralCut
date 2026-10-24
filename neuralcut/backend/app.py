"""FastAPI application factory.

Builds the API app, wires exception handlers, mounts the frontend static
files, and stores the shared container on ``app.state.container``.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from neuralcut.backend.api.v1.router import router as v1_router
from neuralcut.backend.demo_job import register_demo_jobs
from neuralcut.backend.di import Container
from neuralcut.errors import (
    NeuralCutError,
    neuralcut_error_handler,
    unhandled_exception_handler,
)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def build_app(container: Container | None = None) -> FastAPI:
    from neuralcut.config import load_settings

    if container is None:
        container = Container(load_settings())

    app = FastAPI(
        title="NeuralCut",
        description="Local-first AI video editor — Phase 1 foundation",
        version=container.settings.version,
    )

    app.state.container = container

    # Exception handlers -> consistent RFC 7807-style JSON problem responses.
    app.add_exception_handler(NeuralCutError, neuralcut_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    app.include_router(v1_router)

    # Built-in job types (Phase 1 has one demo job; Phase 2+ adds real ones).
    register_demo_jobs(container.job_manager)

    # Frontend: serve static files; every client route falls back to index.html
    # so the SPA can use hash-based routing without server configuration.
    if FRONTEND_DIR.exists():
        app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="assets")

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            if full_path.startswith("api/"):
                return JSONResponse(
                    status_code=404,
                    content={
                        "type": "about:blank",
                        "title": "API route not found",
                        "code": "not_found",
                        "status": 404,
                        "instance": f"/{full_path}",
                    },
                )
            return FileResponse(str(FRONTEND_DIR / "index.html"))

    return app


def get_app(container: Container | None = None) -> FastAPI:
    """Build (or reuse) the default app — used by uvicorn and tests.

    Passing an explicit container always builds a fresh app for that container;
    this is how CLI-selected config/data directories take effect.
    """
    if container is not None:
        get_app._app = build_app(container)  # type: ignore[attr-defined]
        return get_app._app  # type: ignore[return-value]
    if not hasattr(get_app, "_app"):
        get_app._app = build_app()  # type: ignore[attr-defined]
    return get_app._app  # type: ignore[return-value]
