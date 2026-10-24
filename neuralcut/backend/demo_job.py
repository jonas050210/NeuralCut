"""A demonstration job type used to exercise the job manager in Phase 1.

It performs incremental work with cooperative cancellation. Real job types
(import, analysis, render) are Phase 2+ and go through the same manager.
"""

from __future__ import annotations

import time

from neuralcut.errors import ValidationError


def register_demo_jobs(job_manager) -> None:
    def demo_job(job, *, progress, cancel_event, steps=5, delay=0.3, **_ignored):
        try:
            total = int(steps)
            delay_seconds = float(delay)
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                "demo job steps and delay must be numbers",
                details={"steps": steps, "delay": delay},
            ) from exc
        if total < 1 or total > 1000:
            raise ValidationError(
                "demo job steps must be between 1 and 1000",
                details={"steps": total},
            )
        if delay_seconds < 0 or delay_seconds > 60:
            raise ValidationError(
                "demo job delay must be between 0 and 60 seconds",
                details={"delay": delay_seconds},
            )

        for i in range(total):
            if cancel_event.is_set():
                return {"cancelled": True, "completed_steps": i}
            if delay_seconds:
                time.sleep(delay_seconds)
            if cancel_event.is_set():
                return {"cancelled": True, "completed_steps": i}
            progress((i + 1) / total * 100.0, f"step {i + 1} of {total}")
        return {"steps": total, "done": True}

    job_manager.register_job_type("demo", demo_job)
