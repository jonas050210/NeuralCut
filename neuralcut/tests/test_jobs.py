from __future__ import annotations

import threading
import time

import pytest

from neuralcut.errors import JobError, ValidationError
from neuralcut.jobs import JobManager, JobStatus


def wait_for_status(manager: JobManager, job_id: str, status: JobStatus, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = manager.get(job_id)
        assert job is not None
        if job.status == status:
            return job
        time.sleep(0.02)
    job = manager.get(job_id)
    raise AssertionError(
        f"job {job_id} did not reach {status}; current={job.status if job else None}"
    )


def test_job_completion_and_progress() -> None:
    manager = JobManager(max_workers=1)

    def work(job, *, progress, cancel_event, value=3):
        progress(50, "halfway")
        return {"value": value * 2}

    manager.register_job_type("work", work)
    job = manager.submit("work", payload={"value": 4})
    completed = wait_for_status(manager, job.id, JobStatus.COMPLETED)

    assert completed.result == {"value": 8}
    assert completed.progress == 100.0
    assert completed.finished_at is not None


def test_job_failure_reports_error() -> None:
    manager = JobManager(max_workers=1)

    def bad(job, *, progress, cancel_event):
        raise ValidationError("bad input", details={"field": "x"})

    manager.register_job_type("bad", bad)
    job = manager.submit("bad")
    failed = wait_for_status(manager, job.id, JobStatus.FAILED)

    assert "bad input" in (failed.error or "")
    assert failed.details["error_code"] == "validation_error"
    assert failed.details["field"] == "x"


def test_job_cooperative_cancellation() -> None:
    manager = JobManager(max_workers=1)
    started = threading.Event()

    def long_work(job, *, progress, cancel_event):
        started.set()
        for i in range(100):
            if cancel_event.is_set():
                return {"cancelled_at": i}
            progress(i, f"step {i}")
            time.sleep(0.02)
        return {"done": True}

    manager.register_job_type("long", long_work)
    job = manager.submit("long")
    assert started.wait(timeout=2)
    manager.cancel(job.id)

    cancelled = wait_for_status(manager, job.id, JobStatus.CANCELLED)
    assert cancelled.result is None  # cancelled results are not promoted
    assert cancelled.error is None


def test_unknown_and_reserved_jobs_are_client_errors() -> None:
    manager = JobManager(max_workers=1)

    with pytest.raises(JobError) as unknown:
        manager.submit("missing")
    assert unknown.value.http_status == 400

    manager.register_job_type("ok", lambda job, **kwargs: {"ok": True})
    with pytest.raises(JobError) as reserved:
        manager.submit("ok", payload={"progress": "nope"})
    assert reserved.value.http_status == 400


def test_cancel_completed_job_conflicts() -> None:
    manager = JobManager(max_workers=1)
    manager.register_job_type("ok", lambda job, **kwargs: {"ok": True})
    job = manager.submit("ok")
    wait_for_status(manager, job.id, JobStatus.COMPLETED)

    with pytest.raises(JobError) as exc:
        manager.cancel(job.id)
    assert exc.value.http_status == 409
