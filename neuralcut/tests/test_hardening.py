"""Regression tests for the Phase 9 audit fixes."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import pytest

from neuralcut.errors import ValidationError
from neuralcut.jobs import JobManager
from neuralcut.tests.media_helpers import require_ffmpeg


def test_benchmark_run_preserves_live_logging(container, tmp_path: Path) -> None:  # noqa: ANN001
    """High-severity regression: an isolated benchmark container must not
    close/replace/redirect the live application's root logging handlers."""
    require_ffmpeg()
    root = logging.getLogger()
    before = list(root.handlers)
    container.improvement_service.run_baseline()
    after = list(root.handlers)
    assert after == before, "benchmark run replaced the live logging handlers"
    # The retained file handler still points at the real data dir.
    live = logging.getLogger("neuralcut")
    live.info("post-benchmark logging probe")
    for handler in after:
        handler.flush()
    log_file = tmp_path / "data" / "logs" / "neuralcut.log"
    assert "post-benchmark logging probe" in log_file.read_text(encoding="utf-8")


def test_held_out_sealed_for_routine_runs(container) -> None:  # noqa: ANN001
    service = container.improvement_service
    report = service.run_benchmark({"name": "routine"})
    assert report["held_out_accessed"] is False
    assert "held_out" not in report["splits_evaluated"]
    assert all(c["split"] != "held_out" for c in report["cases"])
    # Trajectories are recorded as scorer evidence.
    assert all("trajectory" in c for c in report["cases"])

    exp = service.create_experiment("tuning-candidate", {})
    evaluated = service.evaluate_experiment(exp["id"])
    assert evaluated["report"]["held_out_accessed"] is False
    # Promotion is refused until the explicit gate evaluation ran.
    with pytest.raises(ValidationError):
        service.promote_experiment(
            exp["id"], reviewer="jonas", spot_check_confirmed=True)
    gated = service.gate_evaluate_experiment(exp["id"])
    assert gated["report"]["held_out_accessed"] is True
    events = [e["event"] for e in service.registry.audit_tail()]
    assert "held_out_gate_evaluation" in events


def test_experiment_state_machine(container) -> None:  # noqa: ANN001
    registry = container.improvement_service.registry
    registry.set_baseline({
        "candidate": "incumbent-builtin", "overall": {"accuracy": 0.9},
        "per_split": {"train": {"total": 9, "accuracy": 0.9},
                      "held_out": {"total": 2, "accuracy": 1.0}},
        "dataset_fingerprint": "fp"})
    good = {
        "candidate": "c", "overall": {"accuracy": 0.9},
        "per_split": {"train": {"total": 9, "accuracy": 0.9},
                      "held_out": {"total": 2, "accuracy": 1.0}},
        "dataset_fingerprint": "fp", "held_out_accessed": True}
    exp = registry.create_experiment("sm", {})
    registry.record_gate_evaluation(exp["id"], good)
    registry.promote(exp["id"], reviewer="jonas", spot_check_confirmed=True)
    # Terminal-ish invariants: no demotion, no duplicate promotion.
    with pytest.raises(ValidationError):
        registry.record_evaluation(exp["id"], good)
    with pytest.raises(ValidationError):
        registry.record_gate_evaluation(exp["id"], good)
    with pytest.raises(ValidationError):
        registry.promote(exp["id"], reviewer="jonas", spot_check_confirmed=True)
    registry.rollback()
    with pytest.raises(ValidationError):
        registry.rollback()  # nothing left to roll back to


def test_registry_audit_failure_is_visible_not_fatal(container, tmp_path: Path) -> None:  # noqa: ANN001
    registry = container.improvement_service.registry
    registry._audit_file = tmp_path / "a-directory"
    tmp_path.joinpath("a-directory").mkdir(exist_ok=True)
    report = {
        "candidate": "incumbent-builtin", "overall": {"accuracy": 1.0},
        "per_split": {}, "dataset_fingerprint": "fp"}
    result = registry.set_baseline(report)  # must NOT raise
    assert result is report
    assert registry.baseline() is not None  # persisted despite audit failure
    assert registry.last_audit_error is not None
    status = container.improvement_service.status()
    assert status["audit_error"] == registry.last_audit_error


def test_feedback_rating_validation(container) -> None:  # noqa: ANN001
    container.settings.improvement.feedback_enabled = True
    store = container.improvement_service.feedback
    for bad in (0, 6, 2.5, "5", True):
        with pytest.raises(ValidationError):
            store.record({"kind": "rating", "rating": bad})
    assert store.count() == 0
    store.record({"kind": "rating", "rating": 5})
    assert store.count() == 1


def test_job_payload_redacted_in_public_dict() -> None:
    manager = JobManager(max_workers=1)
    manager.register_job_type("noop", lambda job, **_: {"ok": True})
    job = manager.submit("noop", payload={"project": {"clips": [1, 2, 3]}})
    deadline = time.time() + 10
    while job.status.value not in {"completed", "failed"} and time.time() < deadline:
        time.sleep(0.05)
    public = job.to_dict()
    assert public["details"]["payload"]["redacted"] is True
    assert "clips" not in str(public["details"])


def test_queued_job_waits_and_cancels_cleanly() -> None:
    manager = JobManager(max_workers=1)
    release = threading.Event()
    manager.register_job_type(
        "block", lambda job, **_: release.wait(timeout=10))
    manager.register_job_type("noop", lambda job, **_: {"ok": True})
    first = manager.submit("block")
    second = manager.submit("noop")
    time.sleep(0.5)  # second is queued behind the single worker
    manager.cancel(second.id)
    release.set()
    deadline = time.time() + 10
    while time.time() < deadline:
        if (first.status.value in {"completed", "failed", "cancelled"}
                and second.status.value in {"completed", "failed", "cancelled"}):
            break
        time.sleep(0.05)
    assert first.status.value == "completed"
    assert second.status.value == "cancelled"  # never "failed: timed out"
