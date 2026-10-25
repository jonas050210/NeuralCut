"""Isolated benchmark execution against synthetic fixture projects.

Isolation contract (tested): a run creates its own application container
with a temporary data directory, creates fixture projects inside a
temporary workspace, generates its own tiny media with ffmpeg lavfi, and
deletes everything afterwards. The calling application's container,
projects, and data directory are only used to *store the report*; user
project state is never opened, read, or modified.

Candidates are configurations (model route fields). They are applied to
the isolated container's settings before construction. Candidate code is
never executed -- there is no code path here that runs generated code.
"""

from __future__ import annotations

import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from neuralcut.backend.improvement.datasets import (
    DATASET_VERSION,
    build_cases,
    dataset_fingerprint,
)
from neuralcut.errors import ValidationError


class BenchmarkRunner:
    def __init__(self, container) -> None:  # noqa: ANN001
        self._container = container  # the real app container (report storage only)
        self._settings = container.settings

    # -- public -----------------------------------------------------------

    def run(self, candidate: dict[str, Any] | None = None,
            splits: list[str] | None = None, *,
            include_held_out: bool = False) -> dict[str, Any]:
        """Run benchmark cases in a fully isolated throwaway application.

        Held-out cases are sealed: they are excluded unless
        ``include_held_out=True`` is passed explicitly (baseline recording
        and the audited promotion gate evaluation only).
        """
        from neuralcut.config import load_settings

        candidate = candidate or {"name": "incumbent", "planner": "builtin"}
        cases = build_cases()
        if not include_held_out:
            cases = [c for c in cases if c["split"] != "held_out"]
        if splits:
            cases = [c for c in cases if c["split"] in splits]
        limit = self._settings.improvement.max_benchmark_cases
        cases = cases[:limit]
        budget = self._settings.improvement.case_budget_seconds

        results: list[dict[str, Any]] = []
        started = time.monotonic()
        # ignore_cleanup_errors: on Windows the isolated container's log
        # file handle can still be open at cleanup time (locked file);
        # leaving a temp dir behind beats failing the whole run.
        with tempfile.TemporaryDirectory(
                prefix="neuralcut-bench-", ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            context = load_settings(data_dir=root / "data")
            # Candidate = configuration only (model route). Applied to the
            # isolated settings copy, never to the real application.
            self._apply_candidate(context.settings, candidate)
            from neuralcut.backend.di import Container

            isolated = Container(context, configure_logging=False)
            workspace = root / "projects"
            workspace.mkdir()
            for case in cases:
                results.append(self._run_case(isolated, workspace, case, budget))
        return self._report(candidate, results, time.monotonic() - started)

    # -- candidate / setup --------------------------------------------------

    @staticmethod
    def _apply_candidate(settings, candidate: dict[str, Any]) -> None:  # noqa: ANN001
        models = candidate.get("models") or {}
        allowed = {"enabled", "provider", "endpoint", "model", "allow_cloud"}
        for key, value in models.items():
            if key not in allowed:
                raise ValidationError(
                    f"candidate may not set models.{key}; candidates are "
                    "model-route configurations, not code",
                    details={"candidate": candidate.get("name")})
            setattr(settings.models, key, value)

    def _setup_project(self, isolated, workspace: Path, case: dict[str, Any]):  # noqa: ANN001
        project_dir = workspace / case["id"]
        isolated.project_service.create(f"bench-{case['id']}", project_dir)
        service = isolated.timeline_service
        ffmpeg = isolated.media.require_ffmpeg()
        setup = case["setup"]
        if setup == "empty":
            return
        hero = self._make_media(ffmpeg, project_dir / "hero.mp4", "red")
        hero_asset = service.import_media(hero)
        if setup in {"single", "single_plus_asset"}:
            service.add_clip(hero_asset.id, source_start_seconds=0,
                             source_end_seconds=3, name="hero.mp4")
        if setup == "single_plus_asset":
            broll = self._make_media(ffmpeg, project_dir / "broll.mp4", "blue")
            service.import_media(broll)
        if setup == "two":
            service.add_clip(hero_asset.id, source_start_seconds=0,
                             source_end_seconds=3, name="hero.mp4")
            broll = self._make_media(ffmpeg, project_dir / "broll.mp4", "blue")
            broll_asset = service.import_media(broll)
            service.add_clip(broll_asset.id, source_start_seconds=0,
                             source_end_seconds=3, name="broll.mp4")
        if setup == "ambiguous":
            service.add_clip(hero_asset.id, source_start_seconds=0,
                             source_end_seconds=3, name="hero-a.mp4")
            broll = self._make_media(ffmpeg, project_dir / "broll.mp4", "blue")
            broll_asset = service.import_media(broll)
            service.add_clip(broll_asset.id, source_start_seconds=0,
                             source_end_seconds=3, name="hero-b.mp4")

    @staticmethod
    def _make_media(ffmpeg: str, path: Path, color: str) -> Path:
        cmd = [ffmpeg, "-y", "-f", "lavfi", "-i",
               f"color=c={color}:s=160x120:r=10:d=4",
               "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
               "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
               "-c:a", "aac", str(path)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            raise RuntimeError(f"fixture media generation failed: {proc.stderr[-300:]}")
        return path

    # -- per-case execution / grading ---------------------------------------

    def _run_case(self, isolated, workspace: Path, case: dict[str, Any],  # noqa: ANN001
                  budget: float) -> dict[str, Any]:
        started = time.monotonic()
        entry: dict[str, Any] = {
            "case_id": case["id"], "split": case["split"],
            "instruction": case["instruction"], "passed": False,
            "detail": "", "duration_seconds": 0.0,
            "failure_category": None,
        }
        try:
            self._setup_project(isolated, workspace, case)
            agent = isolated.agent_service
            plan = agent.chat(case["instruction"])
            if plan["status"] == "draft":
                plan = agent.approve(plan["id"])
            entry["plan_status"] = plan["status"]
            # Trajectory: the validated tool-call sequence the agent
            # produced (scorer evidence for failure analysis).
            entry["trajectory"] = [
                {"tool": s["tool"], "args": s["args"]} for s in plan["steps"]]
            entry["passed"], entry["detail"] = self._grade(
                isolated.timeline_service, case, plan)
        except Exception as exc:  # noqa: BLE001 - a failing case is data, not a crash
            entry["detail"] = f"{type(exc).__name__}: {exc}"
            entry["failure_category"] = "harness_error"
        entry["duration_seconds"] = round(time.monotonic() - started, 3)
        if entry["duration_seconds"] > budget:
            entry["passed"] = False
            entry["detail"] += f" [exceeded case budget {budget}s]"
        if not entry["passed"] and entry["failure_category"] is None:
            entry["failure_category"] = self._categorize(case, entry)
        return entry

    @staticmethod
    def _categorize(case: dict[str, Any], entry: dict[str, Any]) -> str:
        """Failure taxonomy for failure mining (eval-harness practice):
        separates planner mistakes from execution and harness problems so
        fixes land in the right layer instead of 'the model is bad'."""
        status = entry.get("plan_status")
        if case["expect"]["kind"] == "clarification" and status != "needs_clarification":
            return "clarification_miss"  # should have asked, acted instead
        if status in {"failed", "partially_executed"}:
            return "execution_failure"
        if status == "needs_clarification":
            return "wrong_plan"  # asked when it should have acted
        return "expectation_mismatch"

    @staticmethod
    def _grade(service, case: dict[str, Any], plan: dict[str, Any]):  # noqa: ANN001
        expect = case["expect"]
        kind = expect["kind"]
        if kind == "clarification":
            ok = plan["status"] == "needs_clarification" and not plan["steps"]
            return ok, f"expected clarification, got {plan['status']}"
        if kind == "answer":
            ok = plan["status"] == "executed" and plan["risk"] == "read"
            return ok, f"expected executed read plan, got {plan['status']}/{plan['risk']}"
        timeline = service.timeline()
        if kind == "clips":
            ok = len(timeline["clips"]) == expect["count"]
            return ok, f"clips={len(timeline['clips'])} expected={expect['count']}"
        if kind == "effect":
            found = [e["type"] for clip in timeline["clips"] for e in clip.get("effects", [])]
            ok = expect["type"] in found
            return ok, f"effects={found} expected~{expect['type']}"
        if kind == "clip_start":
            match = next((c for c in timeline["clips"]
                          if expect["name"] in c["name"]), None)
            ok = match is not None and abs(
                match["timeline_start_seconds"] - expect["start"]) < 0.01
            return ok, f"clip_start={match and match['timeline_start_seconds']}"
        return False, f"unknown expectation kind {kind}"  # pragma: no cover

    # -- report --------------------------------------------------------------

    @staticmethod
    def _report(candidate: dict[str, Any], results: list[dict[str, Any]],
                elapsed: float) -> dict[str, Any]:
        per_split: dict[str, dict[str, Any]] = {}
        for result in results:
            bucket = per_split.setdefault(
                result["split"], {"total": 0, "passed": 0, "accuracy": 0.0})
            bucket["total"] += 1
            bucket["passed"] += int(result["passed"])
        for bucket in per_split.values():
            bucket["accuracy"] = round(
                bucket["passed"] / bucket["total"], 4) if bucket["total"] else 0.0
        total = len(results)
        passed = sum(int(r["passed"]) for r in results)
        failure_categories: dict[str, int] = {}
        for result in results:
            if not result["passed"] and result.get("failure_category"):
                category = result["failure_category"]
                failure_categories[category] = failure_categories.get(category, 0) + 1
        return {
            "run_id": uuid.uuid4().hex,
            "candidate": candidate.get("name", "incumbent"),
            "dataset_version": DATASET_VERSION,
            "dataset_fingerprint": dataset_fingerprint(),
            "cases": results,
            "per_split": per_split,
            "overall": {
                "total": total, "passed": passed,
                "accuracy": round(passed / total, 4) if total else 0.0,
            },
            "duration_seconds": round(elapsed, 3),
            "held_out_accessed": any(c["split"] == "held_out" for c in results),
            "splits_evaluated": sorted({c["split"] for c in results}),
            "failure_categories": failure_categories,
            "isolation": "temporary data dir + fixture projects; user projects untouched",
        }
