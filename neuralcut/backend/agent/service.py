"""Agent service: plan lifecycle, controlled execution, audit log.

Flow: chat -> plan (built-in planner, or a routed model with built-in
fallback) -> read-only plans execute immediately; consequential plans
(edit/external risk) wait as ``draft`` until the user approves them in the
UI -> execution applies steps one by one through the deterministic
services, re-validating each ToolCall against current state at execution
time. A failure stops execution, records the failing step, and leaves
already-applied edits in place *and undoable* (each is a normal
TimelineService operation; "undo plan" reverses the applied edit steps).

Plans persist to ``<data_dir>/agent/plans.json``; every plan event is
appended to ``<data_dir>/agent/audit.jsonl``. Neither file is part of the
project document.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from neuralcut.backend.agent.model_client import ModelRouter
from neuralcut.backend.agent.planner import builtin_plan
from neuralcut.backend.agent.tools import (
    RISK_READ,
    ToolCall,
    plan_risk,
)
from neuralcut.errors import NotFoundError, ValidationError

logger = logging.getLogger("neuralcut.agent")

MAX_PLANS = 200          # retained plans (oldest terminal plans pruned first)
MAX_AUDIT_BYTES = 2_000_000  # audit.jsonl rotates to audit.jsonl.1 past this


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentService:
    def __init__(self, container) -> None:  # noqa: ANN001
        self._container = container
        self.router = ModelRouter(container.settings)
        self._dir = Path(container.context.data_dir) / "agent"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._plans_file = self._dir / "plans.json"
        self._audit_file = self._dir / "audit.jsonl"
        self._lock = threading.Lock()
        self._plans: dict[str, dict[str, Any]] = {}
        if self._plans_file.is_file():
            try:
                for plan in json.loads(self._plans_file.read_text(encoding="utf-8")):
                    self._plans[plan["id"]] = plan
            except (OSError, json.JSONDecodeError, KeyError):
                self._plans = {}

    # ---- context -----------------------------------------------------------

    def context(self) -> dict[str, Any]:
        timeline = self._container.timeline_service.timeline()
        analysis_bits = []
        for asset_info in timeline["assets"]:
            status = self._container.analysis_service.status(
                _AssetShim(asset_info))
            if status.get("status") == "ready":
                analysis_bits.append(
                    f"{asset_info['name']}: {status['shots']} shot(s), "
                    f"{status['tracks']} tracked moving object(s), "
                    f"transcript {status['transcript_status']}")
        return {
            "project_id": timeline["project_id"],
            "duration_seconds": timeline["duration_seconds"],
            "assets": timeline["assets"],
            "clips": timeline["clips"],
            "analysis_summary": "; ".join(analysis_bits) if analysis_bits else None,
        }

    # ---- chat / planning ------------------------------------------------------

    def chat(self, message: str) -> dict[str, Any]:
        if not message or not message.strip():
            raise ValidationError("message must not be empty")
        with self._lock:  # snapshot a consistent context (no mid-chat switches)
            context = self.context()
        source = "builtin"
        model_note = None
        result: dict[str, Any] | None = None
        route = self.router.route()
        if route["mode"] != "builtin":
            try:
                calls, explanation = self.router.generate_plan(message, context)
                result = {"steps": calls, "explanation": explanation}
                source = route["mode"]
            except Exception as exc:  # noqa: BLE001 - fall back, never fail chat
                model_note = f"model route failed ({exc}); used built-in planner"
        if result is None:
            result = builtin_plan(message, context)

        steps = result["steps"]
        risk = plan_risk(steps) if steps else RISK_READ
        plan: dict[str, Any] = {
            "id": uuid.uuid4().hex,
            "message": message,
            "source": source,
            "model_note": model_note,
            "route": route,
            "explanation": result.get("explanation", ""),
            "answer": result.get("answer"),
            "clarification": result.get("clarification"),
            "steps": [s.model_dump() for s in steps],
            "risk": risk,
            "status": "draft" if steps else "needs_clarification",
            "results": [],
            "error": None,
            "applied_edit_steps": 0,
            "created_at": _now(),
            "updated_at": _now(),
        }
        with self._lock:
            self._plans[plan["id"]] = plan
            self._audit("plan_created", plan)
            if steps and risk == RISK_READ:
                self._execute_locked(plan)
            self._save_locked()
        return plan

    # ---- plan actions -----------------------------------------------------------

    def get_plan(self, plan_id: str) -> dict[str, Any]:
        plan = self._plans.get(plan_id)
        if plan is None:
            raise NotFoundError(f"plan not found: {plan_id}")
        return plan

    def list_plans(self) -> list[dict[str, Any]]:
        return sorted(self._plans.values(), key=lambda p: p["created_at"], reverse=True)

    def approve(self, plan_id: str) -> dict[str, Any]:
        with self._lock:
            plan = self.get_plan(plan_id)
            if plan["status"] != "draft":
                raise ValidationError(
                    f"plan is {plan['status']}, not draft", details={"plan_id": plan_id})
            self._audit("plan_approved", plan)
            self._execute_locked(plan)
            self._save_locked()
            return plan

    def reject(self, plan_id: str) -> dict[str, Any]:
        with self._lock:
            plan = self.get_plan(plan_id)
            if plan["status"] not in {"draft", "needs_clarification"}:
                raise ValidationError(
                    f"plan is {plan['status']} and cannot be rejected")
            plan["status"] = "rejected"
            plan["updated_at"] = _now()
            self._audit("plan_rejected", plan)
            self._save_locked()
            return plan

    def undo_plan(self, plan_id: str) -> dict[str, Any]:
        """Reverse exactly this plan's edits via its pre-execution snapshot.

        The restore only happens when the timeline is still in the state
        this plan left behind. If the user (or another plan) edited since,
        restoring the snapshot would silently revert *their* work, so we
        refuse and tell them to use manual undo instead. The restore itself
        is one undoable TimelineService operation.
        """
        with self._lock:
            plan = self.get_plan(plan_id)
            count = plan.get("applied_edit_steps", 0)
            if plan["status"] not in {"executed", "partially_executed"} or count == 0:
                raise ValidationError("plan has no applied edit steps to undo")
            pre_state = plan.get("pre_state")
            post_state = plan.get("post_state")
            if pre_state is None or post_state is None:
                raise ValidationError(
                    "plan predates snapshot-based undo; use manual undo instead")
            service = self._container.timeline_service
            if service.current_snapshot() != post_state:
                raise ValidationError(
                    "timeline changed since this plan executed; undo manually "
                    "so later edits are not reverted",
                    details={"plan_id": plan_id})
            service.restore_snapshot(pre_state)
            plan["status"] = "undone"
            plan["applied_edit_steps"] = 0
            plan["updated_at"] = _now()
            self._audit("plan_undone", plan, {"steps_undone": count})
            self._save_locked()
            return plan

    # ---- execution ---------------------------------------------------------------

    def _execute_locked(self, plan: dict[str, Any]) -> None:
        plan["status"] = "executing"
        plan["results"] = []
        applied_edits = 0
        service = self._container.timeline_service
        # Snapshot before the first step so undo_plan can restore exactly
        # this plan's starting point (see undo_plan for the safety check).
        plan["pre_state"] = service.current_snapshot()
        plan["post_state"] = None
        try:
            for raw_step in plan["steps"]:
                # Re-validate against the registry AND current state: the
                # world may have changed since the plan was drafted.
                call = ToolCall.model_validate(raw_step)
                result = self._execute_step(call, plan)
                plan["results"].append({"tool": call.tool, "result": result})
                from neuralcut.backend.agent.tools import TOOL_REGISTRY

                # undo/redo tools move through history; they are not new
                # edits owned by this plan and must not inflate the count
                # undo_plan relies on.
                if TOOL_REGISTRY[call.tool]["risk"] == "edit" and call.tool not in {
                        "undo", "redo"}:
                    applied_edits += 1
                self._audit("step_executed", plan, {"tool": call.tool})
            plan["status"] = "executed"
            plan["applied_edit_steps"] = applied_edits
        except Exception as exc:  # noqa: BLE001 - record and stop; prior steps stay undoable
            plan["status"] = "failed"
            plan["error"] = f"{type(exc).__name__}: {exc}"
            plan["applied_edit_steps"] = applied_edits
            if applied_edits:
                plan["status"] = "partially_executed"
            self._audit("step_failed", plan, {"error": plan["error"]})
        try:
            plan["post_state"] = service.current_snapshot()
        except Exception as exc:  # noqa: BLE001 - project may have been closed mid-plan
            plan["post_state"] = None
            plan["undo_error"] = (
                f"could not snapshot post-plan state ({type(exc).__name__}); "
                "plan undo is unavailable, use manual undo")
        plan["updated_at"] = _now()

    def _execute_step(self, call: ToolCall, plan: dict[str, Any]) -> Any:
        container = self._container
        service = container.timeline_service
        args = call.args
        tool = call.tool
        if tool == "answer_question":
            return {"answer": plan.get("answer") or "No answer computed."}
        if tool == "get_project_state":
            return self.context()
        if tool == "import_media":
            asset = service.import_media(args["path"])
            return {"asset_id": asset.id, "name": asset.name}
        if tool == "add_clip":
            clip = service.add_clip(
                args["asset_id"],
                track=args.get("track", 0),
                timeline_start_seconds=args.get("timeline_start_seconds"),
                source_start_seconds=args.get("source_start_seconds", 0.0),
                source_end_seconds=args.get("source_end_seconds"),
            )
            return {"clip_id": clip.id}
        if tool == "move_clip":
            clip = service.move_clip(
                args["clip_id"],
                timeline_start_seconds=args["timeline_start_seconds"],
                track=args.get("track"))
            return {"clip_id": clip.id}
        if tool == "trim_clip":
            clip = service.trim_clip(
                args["clip_id"],
                source_start_seconds=args.get("source_start_seconds"),
                source_end_seconds=args.get("source_end_seconds"))
            return {"clip_id": clip.id}
        if tool == "split_clip":
            clips = service.split_clip(
                args["clip_id"], at_timeline_seconds=args["at_timeline_seconds"])
            return {"clip_ids": [c.id for c in clips]}
        if tool == "remove_clip":
            service.remove_clip(args["clip_id"])
            return {"removed": args["clip_id"]}
        if tool == "add_effect":
            effect = service.add_effect(
                args["clip_id"], type=args.get("type") or "",
                params=args.get("params") or {}, preset=args.get("preset"))
            return {"effect_id": effect.id, "type": effect.type}
        if tool == "update_effect":
            effect = service.update_effect(
                args["clip_id"], args["effect_id"],
                params=args.get("params"), enabled=args.get("enabled"))
            return {"effect_id": effect.id}
        if tool == "remove_effect":
            service.remove_effect(args["clip_id"], args["effect_id"])
            return {"removed": args["effect_id"]}
        if tool == "set_keyframes":
            effect = service.set_keyframes(
                args["clip_id"], args["effect_id"], property=args["property"],
                keyframes=args["keyframes"])
            return {"effect_id": effect.id}
        if tool == "undo":
            service.undo()
            return {"undone": True}
        if tool == "redo":
            service.redo()
            return {"redone": True}
        if tool == "analyze_asset":
            timeline = service.timeline()
            asset = next((a for a in timeline["assets"] if a["id"] == args["asset_id"]), None)
            if asset is None:
                raise NotFoundError(f"asset not found: {args['asset_id']}")
            job = container.job_manager.submit(
                "analysis", name=f"Analyze {asset['name']}",
                payload={"asset": asset, "force": bool(args.get("force", False))})
            return {"job_id": job.id, "note": "analysis runs as a background job"}
        if tool == "start_render":
            project = container.project_service.get()
            from neuralcut.backend.projects.model import ExportSettings

            settings = project.export_settings.model_copy(update={
                k: v for k, v in {
                    "width": args.get("width"), "height": args.get("height"),
                    "fps": args.get("fps")}.items() if v is not None})
            settings = ExportSettings.model_validate(settings.model_dump())
            job = container.job_manager.submit(
                "render", name="Agent export",
                payload={"project": project.model_dump(mode="json"),
                         "output_path": args["output_path"],
                         "settings": settings.model_dump(mode="json")})
            return {"job_id": job.id, "note": "render runs as a background job"}
        raise ValidationError(f"tool has no executor: {tool}")  # pragma: no cover

    # ---- audit / persistence -------------------------------------------------------

    def _audit(self, event: str, plan: dict[str, Any],
               details: dict[str, Any] | None = None) -> None:
        record = {
            "ts": _now(), "event": event, "plan_id": plan["id"],
            "status": plan.get("status"), "details": details or {},
        }
        try:
            if (self._audit_file.is_file()
                    and self._audit_file.stat().st_size > MAX_AUDIT_BYTES):
                backup = self._audit_file.with_suffix(".jsonl.1")
                try:
                    backup.unlink(missing_ok=True)
                    self._audit_file.replace(backup)
                except OSError:
                    pass  # rotation is best-effort; appending still works
            with self._audit_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, sort_keys=True) + "\n")
        except OSError as exc:
            # Never break editing over an audit write, but never fail
            # silently either: the gap must be visible in the app log.
            logger.warning("agent audit write failed (%s): %s", event, exc)

    def audit_tail(self, limit: int = 100) -> list[dict[str, Any]]:
        if not self._audit_file.is_file():
            return []
        lines = self._audit_file.read_text(encoding="utf-8").splitlines()[-limit:]
        out = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def _save_locked(self) -> None:
        # Retention: keep at most MAX_PLANS plans, pruning the oldest
        # terminal ones first (drafts awaiting approval are never pruned).
        if len(self._plans) > MAX_PLANS:
            terminal = {"executed", "partially_executed", "failed",
                        "rejected", "undone", "needs_clarification"}
            ordered = sorted(self._plans.values(), key=lambda p: p["created_at"])
            for old in ordered:
                if len(self._plans) <= MAX_PLANS:
                    break
                if old["status"] in terminal:
                    del self._plans[old["id"]]
        try:
            tmp = self._plans_file.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self.list_plans(), indent=2, sort_keys=True), encoding="utf-8")
            tmp.replace(self._plans_file)
        except OSError as exc:
            logger.warning("agent plan persistence failed: %s", exc)
            for plan in self._plans.values():
                plan["persistence_error"] = str(exc)


class _AssetShim:
    """Minimal asset view for AnalysisService.status (needs .id/.path)."""

    def __init__(self, info: dict[str, Any]) -> None:
        self.id = info["id"]
        self.path = info["path"]
