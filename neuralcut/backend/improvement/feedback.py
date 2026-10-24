"""Opt-in local feedback collection (Phase 6).

Feedback is OFF unless ``improvement.feedback_enabled`` is set in the
user's config. While disabled, ``record`` refuses (raises) rather than
silently dropping or silently storing. Records live in one local JSONL
file under the app data dir; they can be listed, exported, and deleted
through the API/UI. Nothing is uploaded anywhere by this module -- there
is no network code here at all.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from neuralcut.errors import ValidationError

MAX_EVENT_CHARS = 4000


class FeedbackStore:
    def __init__(self, data_dir: str | Path, enabled) -> None:  # noqa: ANN001
        self._file = Path(data_dir) / "improvement" / "feedback.jsonl"
        self._enabled = enabled  # callable -> bool (reads live settings)

    @property
    def enabled(self) -> bool:
        return bool(self._enabled())

    def _load(self) -> list[dict[str, Any]]:
        if not self._file.is_file():
            return []
        out = []
        for line in self._file.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    def _save(self, events: list[dict[str, Any]]) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._file.with_suffix(".tmp")
        tmp.write_text(
            "".join(json.dumps(e, sort_keys=True) + "\n" for e in events),
            encoding="utf-8")
        tmp.replace(self._file)

    def record(self, event: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            raise ValidationError(
                "feedback collection is disabled (opt-in). Enable "
                "improvement.feedback_enabled in config to record feedback; "
                "nothing was stored.")
        kind = str(event.get("kind") or "")
        if kind not in {"plan_accepted", "plan_rejected", "plan_undone",
                        "correction", "rating", "note"}:
            raise ValidationError(f"unknown feedback kind: {kind!r}")
        record = {
            "id": uuid.uuid4().hex,
            "ts": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "plan_id": event.get("plan_id"),
            "instruction": str(event.get("instruction") or "")[:MAX_EVENT_CHARS],
            "note": str(event.get("note") or "")[:MAX_EVENT_CHARS],
            "rating": event.get("rating"),
        }
        events = self._load()
        events.append(record)
        self._save(events)
        return record

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._load()[-limit:]

    def export(self) -> dict[str, Any]:
        events = self._load()
        return {"count": len(events), "events": events,
                "exported_from": "local feedback store (never uploaded)"}

    def delete(self, event_id: str | None = None) -> dict[str, Any]:
        events = self._load()
        if event_id is None:
            removed = len(events)
            self._save([])
            return {"deleted": removed}
        kept = [e for e in events if e["id"] != event_id]
        self._save(kept)
        return {"deleted": len(events) - len(kept)}
