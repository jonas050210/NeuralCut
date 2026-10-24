"""Phase 6 self-improvement: datasets, isolation, feedback, gates, training."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from neuralcut.backend.improvement.datasets import build_cases, build_manifest
from neuralcut.backend.improvement.training import (
    TrainingPreparer,
    validate_dataset_for_training,
)
from neuralcut.errors import UnavailableError, ValidationError
from neuralcut.tests.media_helpers import require_ffmpeg


def test_dataset_splits_deterministic_disjoint_with_provenance() -> None:
    cases_a, cases_b = build_cases(), build_cases()
    assert cases_a == cases_b  # deterministic
    by_split: dict[str, set[str]] = {}
    for case in cases_a:
        assert case["provenance"]["source"] == "synthetic_template"
        by_split.setdefault(case["split"], set()).add(case["id"])
    assert set(by_split) == {"train", "val", "held_out"}
    splits = list(by_split.values())
    for i, a in enumerate(splits):
        for b in splits[i + 1:]:
            assert not (a & b)
    manifest = build_manifest()
    assert manifest["case_count"] == len(cases_a)
    assert manifest["fingerprint"]


def test_training_dataset_validation_and_dry_run(container) -> None:  # noqa: ANN001
    result = validate_dataset_for_training()
    assert result["valid"] and result["problems"] == []
    spec = TrainingPreparer(container).prepare()
    assert spec["dry_run"] is True and spec["executes_training"] is False
    assert spec["dataset"]["held_out"].startswith("sealed")
    with pytest.raises(UnavailableError):
        TrainingPreparer(container).start()


def test_feedback_is_opt_in(container) -> None:  # noqa: ANN001
    service = container.improvement_service
    with pytest.raises(ValidationError):
        service.record_feedback({"kind": "note", "note": "hi"})
    assert service.feedback.list() == []

    container.settings.improvement.feedback_enabled = True
    record = service.record_feedback({"kind": "note", "note": "prefer tighter cuts"})
    assert service.feedback.list()[0]["id"] == record["id"]
    assert service.feedback.export()["count"] == 1
    assert service.feedback.delete(record["id"]) == {"deleted": 1}
    service.record_feedback({"kind": "rating", "rating": 4})
    assert service.feedback.delete() == {"deleted": 1}
    assert service.feedback.list() == []


def test_benchmark_isolated_and_baseline(container, tmp_path: Path) -> None:  # noqa: ANN001
    require_ffmpeg()
    # A sentinel "user project" that must remain byte-identical.
    sentinel_dir = tmp_path / "userproj"
    container.project_service.create("Real Project", sentinel_dir)
    sentinel_file = next(sentinel_dir.glob("*.neuralcut"))
    before = sentinel_file.read_bytes()

    report = container.improvement_service.run_baseline()
    assert report["overall"]["total"] == len(build_cases())
    assert report["overall"]["passed"] == len(build_cases())  # builtin baseline is exact
    assert set(report["per_split"]) <= {"train", "val", "held_out"}
    assert sentinel_file.read_bytes() == before
    assert container.improvement_service.registry.baseline() is not None


def test_experiment_gates_promotion_and_rollback(container) -> None:  # noqa: ANN001
    service = container.improvement_service
    baseline = {
        "candidate": "incumbent-builtin", "overall": {"accuracy": 0.9},
        "per_split": {"train": {"total": 9, "accuracy": 0.9},
                      "val": {"total": 3, "accuracy": 0.9},
                      "held_out": {"total": 2, "accuracy": 1.0}},
        "dataset_fingerprint": "fp",
    }
    service.registry.set_baseline(baseline)
    exp = service.create_experiment("candidate-a", {"models": {"provider": "builtin"}})
    good = {
        "candidate": "candidate-a", "overall": {"accuracy": 0.92},
        "per_split": {"train": {"total": 9, "accuracy": 0.92},
                      "val": {"total": 3, "accuracy": 0.9},
                      "held_out": {"total": 2, "accuracy": 1.0}},
        "dataset_fingerprint": "fp",
    }
    service.registry.record_evaluation(exp["id"], good)
    # Human gates: reviewer + explicit spot-check are mandatory.
    with pytest.raises(ValidationError):
        service.registry.promote(exp["id"], reviewer="", spot_check_confirmed=True)
    with pytest.raises(ValidationError):
        service.registry.promote(exp["id"], reviewer="jonas", spot_check_confirmed=False)
    champion = service.registry.promote(
        exp["id"], reviewer="jonas", spot_check_confirmed=True)
    assert champion["name"] == "candidate-a"
    restored = service.registry.rollback()
    assert restored["name"] == "incumbent-builtin"
    kinds = [e["event"] for e in service.registry.audit_tail()]
    assert "candidate_promoted" in kinds and "champion_rolled_back" in kinds

    # Regression gate blocks promotion.
    bad = dict(good, overall={"accuracy": 0.5})
    exp2 = service.create_experiment("candidate-b", {})
    service.registry.record_evaluation(exp2["id"], bad)
    with pytest.raises(ValidationError):
        service.registry.promote(exp2["id"], reviewer="jonas", spot_check_confirmed=True)


def test_candidate_cannot_smuggle_code(container) -> None:  # noqa: ANN001
    service = container.improvement_service
    with pytest.raises(ValidationError):
        service.run_benchmark({"name": "evil", "models": {"shell": "rm -rf /"}})


def test_improvement_api_flow(container) -> None:  # noqa: ANN001
    async def scenario() -> None:
        from neuralcut.backend.app import build_app

        app = build_app(container)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver") as http:
            status = (await http.get("/api/v1/improvement/status")).json()
            assert status["auto_promotion"] is False
            ds = (await http.get("/api/v1/improvement/dataset")).json()
            assert ds["dataset_version"] == "1.0.0"
            denied = await http.post(
                "/api/v1/improvement/feedback", json={"kind": "note", "note": "x"})
            assert denied.status_code == 400
            spec = (await http.post(
                "/api/v1/improvement/training/prepare", json={})).json()
            assert spec["executes_training"] is False
            exp = (await http.post(
                "/api/v1/improvement/experiments",
                json={"name": "api-candidate", "candidate": {}})).json()
            blocked = await http.post(
                f"/api/v1/improvement/experiments/{exp['id']}/promote",
                json={"reviewer": "jonas", "spot_check_confirmed": True})
            assert blocked.status_code == 400  # not evaluated yet

    asyncio.run(scenario())
