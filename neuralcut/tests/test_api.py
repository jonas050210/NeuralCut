from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest


@pytest.mark.asyncio()
async def test_health_diagnostics_config(client: httpx.AsyncClient) -> None:
    health = await client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["service"] == "neuralcut"

    diagnostics = await client.get("/api/v1/diagnostics")
    assert diagnostics.status_code == 200
    body = diagnostics.json()
    assert body["phase"] == "1 — Foundation"
    assert body["media"]["available"] is False
    assert body["models"]["available"] is False
    assert body["models"]["enabled"] is False
    assert "does not require an NVIDIA GPU" in body["gpu"]["note"]
    assert body["jobs"]["active"] == 0

    config = await client.get("/api/v1/config")
    assert config.status_code == 200
    assert config.json()["models"]["enabled"] is False


@pytest.mark.asyncio()
async def test_project_lifecycle_via_api(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    project_dir = tmp_path / "projects"

    created = await client.post(
        "/api/v1/projects/create",
        json={"name": "API Project", "directory": str(project_dir)},
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]

    current = await client.get("/api/v1/projects/current")
    assert current.json()["id"] == project_id

    recent = await client.get("/api/v1/projects")
    assert len(recent.json()["recent"]) == 1
    assert recent.json()["recent"][0]["exists"] is True

    saved = await client.post("/api/v1/projects/save")
    assert saved.status_code == 200
    project_path = saved.json()["path"]
    assert Path(project_path).exists()

    closed = await client.post("/api/v1/projects/close")
    assert closed.json()["status"] == "closed"

    opened = await client.post(
        "/api/v1/projects/open", json={"path": project_path}
    )
    assert opened.status_code == 200
    assert opened.json()["id"] == project_id


@pytest.mark.asyncio()
async def test_project_api_validation_errors(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/projects/create", json={"name": "   ", "directory": "/tmp"}
    )
    assert response.status_code == 422

    missing = await client.post(
        "/api/v1/projects/open", json={"path": "/definitely/missing.neuralcut"}
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == "project_error"


@pytest.mark.asyncio()
async def test_demo_job_lifecycle_via_api(client: httpx.AsyncClient) -> None:
    submitted = await client.post(
        "/api/v1/jobs",
        json={
            "type": "demo",
            "name": "API demo",
            "payload": {"steps": 2, "delay": 0.01},
        },
    )
    assert submitted.status_code == 200, submitted.text
    job_id = submitted.json()["id"]

    completed = None
    for _ in range(50):
        response = await client.get(f"/api/v1/jobs/{job_id}")
        if response.json()["status"] == "completed":
            completed = response.json()
            break
        await asyncio.sleep(0.05)

    assert completed is not None
    assert completed["progress"] == 100.0
    assert completed["result"]["done"] is True

    conflict = await client.post(f"/api/v1/jobs/{job_id}/cancel")
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "job_error"


@pytest.mark.asyncio()
async def test_job_api_errors_and_logs_validation(
    client: httpx.AsyncClient,
) -> None:
    unknown = await client.post("/api/v1/jobs", json={"type": "missing"})
    assert unknown.status_code == 400
    assert unknown.json()["code"] == "job_error"

    missing_job = await client.get("/api/v1/jobs/nope")
    assert missing_job.status_code == 404

    bad_logs = await client.get("/api/v1/logs?lines=0")
    assert bad_logs.status_code == 422

    logs = await client.get("/api/v1/logs?lines=5")
    assert logs.status_code == 200
    assert isinstance(logs.json()["lines"], list)


@pytest.mark.asyncio()
async def test_frontend_and_unknown_api_route(client: httpx.AsyncClient) -> None:
    home = await client.get("/")
    assert home.status_code == 200
    assert "NeuralCut" in home.text

    js = await client.get("/assets/app.js")
    assert js.status_code == 200
    assert "apiJson" in js.text

    unknown = await client.get("/api/v1/unknown")
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "not_found"
