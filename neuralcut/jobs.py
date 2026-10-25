"""Background jobs: status, progress, safe cancellation, error reporting.

Jobs run on a pool of worker threads. Each job exposes:

- ``status``: queued / running / completed / failed / cancelled
- ``progress``: 0.0 - 100.0
- ``result`` / ``error``: terminal payload
- ``cancel()``: cooperative cancellation via :class:`threading.Event`; the job
  function receives a ``cancel_event`` keyword argument and should poll it.

Job functions signature::

    def my_job(job, *, cancel_event, progress, **kwargs) -> Any:
        ...
        progress(10, "loading ...")
        if cancel_event.is_set():
            return  # manager marks the job cancelled
        return {"ok": true}

Registration::

    job_manager.register_job_type("analysis", analysis_job)
    job = job_manager.submit("analysis", name="Analyze clip", asset_id="...")
    job_manager.cancel(job.id)

This is intentionally dependency-free (stdlib threading only) so job machinery
never pulls in model or media dependencies.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

from neuralcut.errors import JobError, NeuralCutError


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}


@dataclass
class Job:
    id: str
    type: str
    name: str
    status: JobStatus = JobStatus.QUEUED
    progress: float = 0.0
    progress_message: str = ""
    result: Any = None
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: str | None = None
    finished_at: str | None = None

    # Internal, not serialized by default
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)

    def to_dict(self) -> dict[str, Any]:
        details = dict(self.details)
        if "payload" in details:
            payload = details["payload"]
            details["payload"] = {
                "redacted": True,
                "keys": sorted(payload) if isinstance(payload, dict) else [],
            }
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "status": self.status.value,
            "progress": round(self.progress, 2),
            "progress_message": self.progress_message,
            "result": self.result,
            "error": self.error,
            "details": details,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


JobFunc = Callable[["Job", Any], Any]


class JobManager:
    _RESERVED_PAYLOAD_KEYS = {"job", "progress", "cancel_event"}

    def __init__(
        self,
        max_workers: int = 2,
        max_jobs: int = 100,
        result_ttl_seconds: int | None = None,
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        self.max_workers = max_workers
        self.max_jobs = max_jobs
        self.result_ttl_seconds = result_ttl_seconds
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._semaphore = threading.BoundedSemaphore(max_workers)
        self._job_types: dict[str, JobFunc] = {}

    # ---- registration -----------------------------------------------------

    def register_job_type(self, type_name: str, func: JobFunc) -> None:
        self._job_types[type_name] = func

    def has_job_type(self, type_name: str) -> bool:
        return type_name in self._job_types

    # ---- submission -------------------------------------------------------

    def submit(
        self,
        type_name: str,
        *,
        name: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Job:
        payload = payload or {}
        reserved = sorted(self._RESERVED_PAYLOAD_KEYS.intersection(payload))
        if reserved:
            raise JobError(
                "job payload uses reserved keys",
                details={"reserved_keys": reserved},
                http_status=400,
            )
        if self.result_ttl_seconds is not None:
            self.purge(older_than_seconds=self.result_ttl_seconds)
        with self._lock:
            if len(self._jobs) >= self.max_jobs:
                raise JobError(
                    f"job queue full ({self.max_jobs} jobs)",
                    details={"max_jobs": self.max_jobs},
                    http_status=429,
                )
            if type_name not in self._job_types:
                raise JobError(
                    f"unknown job type: {type_name}",
                    details={"known_types": sorted(self._job_types)},
                    http_status=400,
                )
            job = Job(
                id=uuid.uuid4().hex,
                type=type_name,
                name=name or type_name,
                details={"payload": payload or {}},
            )
            self._jobs[job.id] = job

        threading.Thread(
            target=self._run, args=(job,), daemon=True, name=f"nc-job-{job.id[:8]}"
        ).start()
        return job

    # ---- queries ----------------------------------------------------------

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self, status: JobStatus | None = None) -> list[Job]:
        with self._lock:
            jobs = list(self._jobs.values())
        if status is not None:
            jobs = [j for j in jobs if j.status == status]
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs

    def cancel(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobError(f"job not found: {job_id}", http_status=404)
            if job.status in TERMINAL_STATUSES:
                raise JobError(
                    f"job already {job.status.value}",
                    details={"job_id": job_id, "status": job.status.value},
                    http_status=409,
                )
            job.cancel_event.set()
            if job.status == JobStatus.QUEUED:
                job.status = JobStatus.CANCELLED
                job.finished_at = _now()
        return job

    def purge(self, older_than_seconds: int | None = None) -> int:
        """Remove terminal jobs. Returns number of jobs removed."""
        import time

        now = time.time()
        removed: list[str] = []
        with self._lock:
            for job_id, job in list(self._jobs.items()):
                if job.status not in TERMINAL_STATUSES:
                    continue
                if older_than_seconds is not None and job.finished_at:
                    finished = datetime.fromisoformat(job.finished_at).timestamp()
                    if now - finished < older_than_seconds:
                        continue
                removed.append(job_id)
            for job_id in removed:
                del self._jobs[job_id]
        return len(removed)

    # ---- internals --------------------------------------------------------

    def _run(self, job: Job) -> None:
        # Wait for a worker slot indefinitely, but stay responsive to
        # cancellation: a queued job must never fail spuriously just
        # because the queue was long (previously: hard 300s timeout).
        acquired = False
        while not acquired:
            if job.cancel_event.is_set():
                with self._lock:
                    job.status = JobStatus.CANCELLED
                    job.finished_at = _now()
                return
            acquired = self._semaphore.acquire(timeout=0.25)

        try:
            with self._lock:
                if job.cancel_event.is_set():
                    job.status = JobStatus.CANCELLED
                    job.finished_at = _now()
                    return
                job.status = JobStatus.RUNNING
                job.started_at = _now()

            func = self._job_types[job.type]

            def progress(value: float, message: str = "") -> None:
                with self._lock:
                    job.progress = max(0.0, min(100.0, float(value)))
                    job.progress_message = message

            result = func(
                job,
                progress=progress,
                cancel_event=job.cancel_event,
                **job.details.get("payload", {}),
            )

            with self._lock:
                if job.cancel_event.is_set():
                    job.status = JobStatus.CANCELLED
                else:
                    job.status = JobStatus.COMPLETED
                    job.result = result
                    job.progress = 100.0
                job.finished_at = _now()
        except NeuralCutError as exc:
            self._fail(job, exc.message, code=exc.code, details=exc.details)
        except Exception as exc:  # noqa: BLE001 - report any job failure as job error
            self._fail(job, f"{type(exc).__name__}: {exc}")
        finally:
            self._semaphore.release()

    def _fail(
        self,
        job: Job,
        message: str,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            job.status = JobStatus.FAILED
            job.error = message
            job.finished_at = _now()
            if code:
                job.details["error_code"] = code
            if details:
                job.details.update(details)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
