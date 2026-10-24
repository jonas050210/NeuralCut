"""Structured logging for NeuralCut.

Design goals:
- JSON-structured records by default (machine-readable, easy to ship to a log
  viewer or diagnostics endpoint).
- Logs go to a rotating file in the app data dir and optionally to stdout.
- A correlation ID can be attached to every record created while processing a
  single request/job (set via ``set_correlation_id`` / contextvar).
- No third-party dependencies beyond the standard library; keeps startup fast
  and avoids initializing anything GPU- or model-related.
"""

from __future__ import annotations

import contextvars
import json
import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Any

from neuralcut.config import AppContext, LoggingConfig

#: Correlation id carried through one request or job. Defaults to a dash so
#: records produced outside a request context still have the field.
_correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "neuralcut_correlation_id", default="-"
)


def get_correlation_id() -> str:
    return _correlation_id.get()


def set_correlation_id(cid: str) -> contextvars.Token[str]:
    """Set the correlation id for the current context and return its reset token."""
    return _correlation_id.set(cid)


class CorrelationIdFilter(logging.Filter):
    """Injects the current correlation id into every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.cid = get_correlation_id()
        return True


class JsonFormatter(logging.Formatter):
    """Formats LogRecords as a single JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "cid": getattr(record, "cid", "-"),
            "msg": record.getMessage(),
            "module": record.module,
            "line": record.lineno,
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = record.stack_info
        # Extra fields attached via logger.bind-style kwargs (record.extra).
        for key, value in record.__dict__.items():
            if key not in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "getMessage",
                "cid",
            }:
                payload[key] = value
        return json.dumps(payload, sort_keys=True, default=str)


def _default_log_file(data_dir: Path) -> Path:
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "neuralcut.log"


def setup_logging(context: AppContext) -> logging.Logger:
    """Configure root logging once at startup.

    Returns the ``neuralcut`` application logger. Safe to call only once;
    calling again reconfigures handlers (idempotent-ish).
    """
    cfg: LoggingConfig = context.settings.logging
    log_file = Path(cfg.file) if cfg.file else _default_log_file(context.data_dir)

    root = logging.getLogger()
    root.setLevel(getattr(logging, cfg.level))

    # Remove previously configured handlers so re-setup does not duplicate.
    for handler in list(root.handlers):
        root.removeHandler(handler)
        try:
            handler.close()
        except Exception:  # pragma: no cover - defensive cleanup
            pass

    fmt: logging.Formatter = (
        JsonFormatter()
        if cfg.json_logs
        else logging.Formatter(
            "%(asctime)s %(levelname)s [%(cid)s] %(name)s: %(message)s"
        )
    )

    if cfg.stdout:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        sh.addFilter(CorrelationIdFilter())
        root.addHandler(sh)

    try:
        fh = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=cfg.max_bytes, backupCount=cfg.backup_count, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        fh.addFilter(CorrelationIdFilter())
        root.addHandler(fh)
    except OSError as exc:  # pragma: no cover - environment dependent
        logging.getLogger("neuralcut").warning("could not open log file %s: %s", log_file, exc)

    logger = logging.getLogger("neuralcut")
    logger.info(
        "logging initialized",
        extra={"log_file": str(log_file), "level": cfg.level, "json_logs": cfg.json_logs},
    )
    return logger


class CorrelationScope:
    """Context manager that binds a correlation id to the current context.

    Usage::

        with CorrelationScope("req-123"):
            logger.info("processing request")

    Nesting restores the previous id on exit.
    """

    def __init__(self, cid: str | None = None) -> None:
        import uuid

        self.cid = cid or uuid.uuid4().hex
        self._token: contextvars.Token[str] | None = None

    def __enter__(self) -> "CorrelationScope":
        self._token = _correlation_id.set(self.cid)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._token is not None:
            _correlation_id.reset(self._token)


def bind_cid(cid: str | None = None) -> CorrelationScope:
    return CorrelationScope(cid)
