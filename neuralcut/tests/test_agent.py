from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from neuralcut.backend.agent.model_client import ModelRouter
from neuralcut.backend.agent.tools import ToolCall, validate_args
from neuralcut.backend.di import Container
from neuralcut.config import load_settings
from neuralcut.errors import ValidationError
from neuralcut.tests.media_helpers import make_video, require_ffmpeg


@pytest.fixture()
def agent_project(container: Container, tmp_path: Path):
    require_ffmpeg()
    container.project_service.create("Agent", tmp_path / "proj")
    video = make_video(tmp_path / "clip.mp4", duration=4.0, color="red")
    asset = container.timeline_service.import_media(video)
    clip = container.timeline_service.add_clip(
        asset.id, source_start_seconds=0, source_end_seconds=3, name="hero.mp4")
    return container, asset, clip


def test_tool_schema_validation() -> None:
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError
        ToolCall(tool="run_shell", args={"cmd": "rm -rf /"})
    with pytest.raises(ValidationError):
        validate_args("split_clip", {"clip_id": "x"})  # missing time
    with pytest.raises(ValidationError):
        validate_args("move_clip", {"clip_id": "x", "timeline_start_seconds": -1})
    with pytest.raises(ValidationError):
        validate_args("add_clip", {"asset_id": "a", "evil": True})
    ok = ToolCall(tool="split_clip", args={"clip_id": "x", "at_timeline_seconds": 1.0})
    assert ok.tool == "split_clip"


def test_readonly_question_autoexecutes(agent_project) -> None:  # noqa: ANN001
    container, _asset, _clip = agent_project
    plan = container.agent_service.chat("how long is my timeline?")
    assert plan["status"] == "executed"
    assert plan["risk"] == "read"
    assert "3.0" in plan["results"][0]["result"]["answer"]


def test_edit_plan_requires_approval_and_is_undoable(agent_project) -> None:  # noqa: ANN001
    container, _asset, clip = agent_project
    service = container.timeline_service
    before = service.timeline()

    plan = container.agent_service.chat("split clip hero at 1s")
    assert plan["status"] == "draft"
    assert plan["risk"] == "edit"
    assert service.timeline()["clips"] == before["clips"]  # nothing executed yet

    executed = container.agent_service.approve(plan["id"])
    assert executed["status"] == "executed"
    assert len(service.timeline()["clips"]) == 2

    container.agent_service.undo_plan(plan["id"])
    assert service.timeline()["clips"] == before["clips"]

    events = container.agent_service.audit_tail()
    kinds = [e["event"] for e in events]
    assert "plan_created" in kinds and "plan_approved" in kinds and "plan_undone" in kinds


def test_ambiguous_and_unknown_requests_clarify(agent_project) -> None:  # noqa: ANN001
    container, _asset, _clip = agent_project
    plan = container.agent_service.chat("split clip nosuchthing at 1s")
    assert plan["status"] == "needs_clarification"
    assert plan["steps"] == []
    plan2 = container.agent_service.chat("please juggle the footage nicely")
    assert plan2["status"] == "needs_clarification"


def test_reject_and_invalid_model_output_fallback(container: Container, tmp_path: Path) -> None:
    require_ffmpeg()
    container.project_service.create("FB", tmp_path / "proj")
    video = make_video(tmp_path / "v.mp4", duration=2.0)
    asset = container.timeline_service.import_media(video)
    container.timeline_service.add_clip(asset.id, name="main.mp4")

    plan = container.agent_service.chat("remove clip main")
    rejected = container.agent_service.reject(plan["id"])
    assert rejected["status"] == "rejected"
    assert len(container.timeline_service.timeline()["clips"]) == 1

    # A model route that returns garbage must fall back, never execute.
    context = load_settings(data_dir=tmp_path / "data2")
    context.settings.models.enabled = True
    context.settings.models.provider = "local"
    context.settings.models.endpoint = "http://127.0.0.1:9/v1"
    context.settings.models.model = "fake"
    router = ModelRouter(context.settings, transport=lambda *_a: {"choices": [
        {"message": {"content": "definitely not json"}}]})
    with pytest.raises(Exception):  # noqa: B017 - router raises Unavailable/Validation
        router.generate_plan("hi", {})


def test_model_plan_is_validated_before_any_execution(
    agent_project, monkeypatch: pytest.MonkeyPatch  # noqa: ANN001
) -> None:
    container, _asset, _clip = agent_project

    def fake_generate(message, context):  # noqa: ANN001, ANN202
        return [ToolCall(tool="remove_clip", args={"clip_id": "nonexistent"})], "bad plan"

    monkeypatch.setattr(container.agent_service.router, "route",
                        lambda: {"mode": "local", "model": "x", "detail": "test"})
    monkeypatch.setattr(container.agent_service.router, "generate_plan", fake_generate)
    plan = container.agent_service.chat("remove the thing")
    assert plan["source"] == "local"
    assert plan["status"] == "draft"  # execution still gated by approval
    executed = container.agent_service.approve(plan["id"])
    assert executed["status"] in {"failed", "partially_executed"}
    assert len(container.timeline_service.timeline()["clips"]) == 1  # nothing mutated


def test_cloud_requires_explicit_opt_in(tmp_path: Path) -> None:
    context = load_settings(data_dir=tmp_path / "d")
    context.settings.models.enabled = True
    context.settings.models.provider = "cloud"
    context.settings.models.endpoint = "https://example.invalid/v1"
    context.settings.models.model = "x"
    route = ModelRouter(context.settings).route()
    assert route["mode"] == "builtin"  # allow_cloud defaults to false
    context.settings.models.allow_cloud = True
    route = ModelRouter(context.settings).route()
    assert route["mode"] == "builtin"  # still no API key in env
    import os

    monkeypatch_env = "NEURALCUT_CLOUD_API_KEY"
    old = os.environ.get(monkeypatch_env)
    os.environ[monkeypatch_env] = "test-key"
    try:
        assert ModelRouter(context.settings).route()["mode"] == "cloud"
    finally:
        if old is None:
            del os.environ[monkeypatch_env]
        else:
            os.environ[monkeypatch_env] = old


@pytest.mark.asyncio()
async def test_agent_via_api(client: httpx.AsyncClient, tmp_path: Path) -> None:
    require_ffmpeg()
    await client.post("/api/v1/projects/create",
                      json={"name": "API Agent", "directory": str(tmp_path / "proj")})
    video = make_video(tmp_path / "v.mp4", duration=3.0)
    imported = await client.post("/api/v1/projects/current/assets/import",
                                 json={"path": str(video)})
    asset_id = imported.json()["asset"]["id"]
    added = await client.post("/api/v1/projects/current/clips",
                              json={"asset_id": asset_id})
    clip_id = added.json()["clip"]["id"]

    status = await client.get("/api/v1/agent/status")
    assert status.status_code == 200
    assert status.json()["router"]["route"]["mode"] == "builtin"
    assert "split_clip" in status.json()["tools"]
    assert "run_shell" not in status.json()["tools"]

    chat = await client.post("/api/v1/agent/chat",
                             json={"message": "What clips do I have?"})
    assert chat.json()["status"] == "executed"

    plan = await client.post("/api/v1/agent/chat",
                             json={"message": "add glow to clip v"})
    assert plan.status_code == 200, plan.text
    # 'v' may match the clip name 'v.mp4' uniquely
    if plan.json()["status"] == "draft":
        approved = await client.post(f"/api/v1/agent/plans/{plan.json()['id']}/approve")
        assert approved.json()["status"] == "executed"
        timeline = await client.get("/api/v1/projects/current/timeline")
        assert timeline.json()["clips"][0]["effects"][0]["type"] == "glow"

    audit = await client.get("/api/v1/agent/audit")
    assert audit.json()["events"]

    # Render via agent creates a background job (does not block the request).
    render_plan = await client.post(
        "/api/v1/agent/chat",
        json={"message": f'export to "{tmp_path}/agent-export.mp4"'})
    assert render_plan.json()["status"] == "draft"
    approved = await client.post(
        f"/api/v1/agent/plans/{render_plan.json()['id']}/approve")
    result = approved.json()["results"][0]["result"]
    job_id = result["job_id"]
    final = None
    for _ in range(200):
        resp = await client.get(f"/api/v1/jobs/{job_id}")
        if resp.json()["status"] in {"completed", "failed"}:
            final = resp.json()
            break
        await asyncio.sleep(0.1)
    assert final is not None and final["status"] == "completed"
    assert clip_id
