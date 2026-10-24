"""Experiment registry, promotion gates, rollback, audit (Phase 6).

Candidates are named *configurations* (model-route settings for the
agent). An experiment evaluates a candidate with the benchmark runner and
compares it with the stored baseline. Promotion is a separate, explicit,
human-gated action:

- deterministic gates: candidate overall accuracy may trail the baseline
  by at most ``improvement.promotion_tolerance`` (and each split by at
  most twice that);
- human gate: the promote call must include a reviewer name and an
  explicit ``spot_check_confirmed=true`` -- there is no automatic
  promotion path anywhere in this module;
- rollback restores the previous champion in one call.

Champion/rollback changes are registry decisions with an audit trail.
Applying a champion configuration to the live application remains a
deliberate user action via the normal config file; this module never
rewrites the running app's settings by itself.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from neuralcut.errors import NotFoundError, ValidationError

TERMINAL_EXPERIMENT = {"evaluated", "promoted", "rejected", "rolled_back"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ImprovementRegistry:
    def __init__(self, container) -> None:  # noqa: ANN001
        self._container = container
        self._dir = Path(container.context.data_dir) / "improvement"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._state_file = self._dir / "registry.json"
        self._audit_file = self._dir / "audit.jsonl"
        self._state: dict[str, Any] = {
            "baseline": None, "experiments": {}, "champion": None, "history": [],
        }
        if self._state_file.is_file():
            try:
                loaded = json.loads(self._state_file.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self._state.update(loaded)
            except (OSError, json.JSONDecodeError):
                pass

    # ---- persistence / audit ---------------------------------------------

    def _save(self) -> None:
        tmp = self._state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state, indent=2, sort_keys=True),
                       encoding="utf-8")
        tmp.replace(self._state_file)

    def _audit(self, event: str, details: dict[str, Any]) -> None:
        record = {"ts": _now(), "event": event, **details}
        try:
            with self._audit_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, sort_keys=True) + "\n")
        except OSError:
            # Registry mutations are already saved; an audit failure must be
            # visible in the response, not fail the operation silently.
            raise ValidationError("could not write improvement audit log") from None

    def audit_tail(self, limit: int = 100) -> list[dict[str, Any]]:
        if not self._audit_file.is_file():
            return []
        out = []
        for line in self._audit_file.read_text(encoding="utf-8").splitlines()[-limit:]:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    # ---- baseline -----------------------------------------------------------

    def set_baseline(self, report: dict[str, Any]) -> dict[str, Any]:
        self._state["baseline"] = report
        if self._state["champion"] is None:
            self._state["champion"] = {
                "name": report["candidate"], "experiment_id": None,
                "promoted_by": "baseline", "promoted_at": _now(),
            }
        self._save()
        self._audit("baseline_recorded", {
            "candidate": report["candidate"],
            "accuracy": report["overall"]["accuracy"],
            "dataset_fingerprint": report["dataset_fingerprint"]})
        return report

    def baseline(self) -> dict[str, Any] | None:
        return self._state["baseline"]

    # ---- experiments ----------------------------------------------------------

    def create_experiment(self, name: str,
                          candidate: dict[str, Any]) -> dict[str, Any]:
        if not name or not name.strip():
            raise ValidationError("experiment name must not be empty")
        exp = {
            "id": uuid.uuid4().hex, "name": name.strip(),
            "candidate": {"name": name.strip(), **candidate},
            "status": "created", "report": None, "gates": None,
            "created_at": _now(), "updated_at": _now(),
        }
        self._state["experiments"][exp["id"]] = exp
        self._save()
        self._audit("experiment_created", {"experiment_id": exp["id"], "name": name})
        return exp

    def get_experiment(self, experiment_id: str) -> dict[str, Any]:
        exp = self._state["experiments"].get(experiment_id)
        if exp is None:
            raise NotFoundError(f"experiment not found: {experiment_id}")
        return exp

    def list_experiments(self) -> list[dict[str, Any]]:
        return sorted(self._state["experiments"].values(),
                      key=lambda e: e["created_at"], reverse=True)

    def record_evaluation(self, experiment_id: str,
                          report: dict[str, Any]) -> dict[str, Any]:
        exp = self.get_experiment(experiment_id)
        exp["report"] = report
        exp["gates"] = self.evaluate_gates(report)
        exp["status"] = "evaluated"
        exp["updated_at"] = _now()
        self._save()
        self._audit("experiment_evaluated", {
            "experiment_id": experiment_id,
            "accuracy": report["overall"]["accuracy"],
            "gates_passed": exp["gates"]["passed"]})
        return exp

    # ---- gates ------------------------------------------------------------------

    def evaluate_gates(self, report: dict[str, Any]) -> dict[str, Any]:
        baseline = self._state["baseline"]
        tolerance = self._container.settings.improvement.promotion_tolerance
        checks: list[dict[str, Any]] = []
        if baseline is None:
            return {"passed": False, "reason": "no baseline recorded yet",
                    "checks": checks}
        if report["dataset_fingerprint"] != baseline["dataset_fingerprint"]:
            return {"passed": False,
                    "reason": "dataset fingerprint differs from baseline; "
                              "results are not comparable",
                    "checks": checks}
        base_acc = baseline["overall"]["accuracy"]
        cand_acc = report["overall"]["accuracy"]
        checks.append({
            "gate": "overall_accuracy",
            "baseline": base_acc, "candidate": cand_acc,
            "tolerance": tolerance,
            "passed": cand_acc >= base_acc - tolerance})
        for split, bucket in baseline["per_split"].items():
            cand_bucket = report["per_split"].get(split)
            if cand_bucket is None or bucket["total"] == 0:
                continue
            checks.append({
                "gate": f"split:{split}",
                "baseline": bucket["accuracy"],
                "candidate": cand_bucket["accuracy"],
                "tolerance": 2 * tolerance,
                "passed": cand_bucket["accuracy"] >= bucket["accuracy"] - 2 * tolerance})
        checks.append({
            "gate": "held_out_present",
            "passed": report["per_split"].get("held_out", {}).get("total", 0) > 0})
        return {"passed": all(c["passed"] for c in checks), "checks": checks}

    # ---- promotion / rollback ------------------------------------------------------

    def promote(self, experiment_id: str, *, reviewer: str,
                spot_check_confirmed: bool) -> dict[str, Any]:
        """Human-gated promotion. There is deliberately no auto-promotion."""
        exp = self.get_experiment(experiment_id)
        if not reviewer or not reviewer.strip():
            raise ValidationError(
                "promotion requires a named human reviewer (spot-check)")
        if spot_check_confirmed is not True:
            raise ValidationError(
                "promotion requires spot_check_confirmed=true: a human must "
                "have reviewed representative successes and failures")
        if exp["status"] != "evaluated" or exp["report"] is None:
            raise ValidationError("experiment must be evaluated before promotion")
        gates = self.evaluate_gates(exp["report"])
        if not gates["passed"]:
            raise ValidationError(
                "promotion gates failed; candidate cannot be promoted",
                details={"gates": gates})
        previous = self._state["champion"]
        if previous:
            self._state["history"].append(previous)
        self._state["champion"] = {
            "name": exp["candidate"]["name"], "experiment_id": exp["id"],
            "promoted_by": reviewer.strip(), "promoted_at": _now(),
            "accuracy": exp["report"]["overall"]["accuracy"],
        }
        exp["status"] = "promoted"
        exp["updated_at"] = _now()
        self._save()
        self._audit("candidate_promoted", {
            "experiment_id": exp["id"], "reviewer": reviewer.strip(),
            "spot_check_confirmed": True,
            "accuracy": exp["report"]["overall"]["accuracy"]})
        return self._state["champion"]

    def rollback(self) -> dict[str, Any]:
        history = self._state["history"]
        if not history:
            raise ValidationError("no previous champion to roll back to")
        current = self._state["champion"]
        restored = history.pop()
        if current:
            for exp in self._state["experiments"].values():
                if exp["id"] == current.get("experiment_id"):
                    exp["status"] = "rolled_back"
        self._state["champion"] = restored
        self._save()
        self._audit("champion_rolled_back", {
            "from": current and current.get("name"),
            "to": restored.get("name")})
        return restored

    def champion(self) -> dict[str, Any] | None:
        return self._state["champion"]
