from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from neuralcut.backend.app import build_app
from neuralcut.backend.di import Container
from neuralcut.config import AppContext, load_settings


@pytest.fixture()
def app_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AppContext:
    # Keep test output readable while still exercising file logging.
    monkeypatch.setenv("NEURALCUT_LOGGING__STDOUT", "false")
    return load_settings(data_dir=tmp_path / "data")


@pytest.fixture()
def container(app_context: AppContext) -> Container:
    return Container(app_context)


@pytest.fixture()
async def client(container: Container):
    app = build_app(container)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as async_client:
        yield async_client
