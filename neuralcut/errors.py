"""Error handling for NeuralCut.

- ``NeuralCutError``: typed application errors with a stable error code,
  human-readable message, optional details, and an HTTP status code.
- ``problem_details()``: builds an RFC 7807 style payload.
- FastAPI exception handlers convert errors (and unexpected exceptions) into
  consistent JSON problem responses instead of HTML tracebacks.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class NeuralCutError(Exception):
    """Base class for all NeuralCut application errors."""

    code: str = "neuralcut_error"
    message: str = "An unexpected error occurred"
    http_status: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    details: dict[str, Any] | None = None

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
        http_status: int | None = None,
    ) -> None:
        if message is not None:
            self.message = message
        if code is not None:
            self.code = code
        if details is not None:
            self.details = details
        if http_status is not None:
            self.http_status = http_status
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": "about:blank",
            "title": self.message,
            "code": self.code,
            "status": self.http_status,
        }
        if self.details:
            payload["details"] = self.details
        return payload


class ValidationError(NeuralCutError):
    code = "validation_error"
    http_status = status.HTTP_400_BAD_REQUEST


class NotFoundError(NeuralCutError):
    code = "not_found"
    http_status = status.HTTP_404_NOT_FOUND


class ConflictError(NeuralCutError):
    code = "conflict"
    http_status = status.HTTP_409_CONFLICT


class UnavailableError(NeuralCutError):
    code = "unavailable"
    http_status = status.HTTP_503_SERVICE_UNAVAILABLE


class ProjectError(NeuralCutError):
    code = "project_error"


class JobError(NeuralCutError):
    code = "job_error"


class ConfigurationError(NeuralCutError):
    code = "configuration_error"


class ProblemDetails(BaseModel):
    type: str = "about:blank"
    title: str
    code: str | None = None
    status: int | None = None
    details: dict[str, Any] | None = None
    instance: str | None = None


def problem_details(
    request: Request,
    exc: NeuralCutError,
) -> JSONResponse:
    payload = ProblemDetails(
        title=exc.message,
        code=exc.code,
        status=exc.http_status,
        details=exc.details,
        instance=str(request.url.path),
    )
    return JSONResponse(status_code=exc.http_status, content=payload.model_dump(exclude_none=True))


async def neuralcut_error_handler(request: Request, exc: NeuralCutError) -> JSONResponse:
    import logging

    logger = logging.getLogger("neuralcut.errors")
    if exc.http_status >= 500:
        logger.error(
            "application error: %s (%s)",
            exc.message,
            exc.code,
            exc_info=(type(exc), exc, exc.__traceback__),
            extra={"error_details": exc.details or {}},
        )
    else:
        logger.info(
            "client error: %s (%s)",
            exc.message,
            exc.code,
            extra={"error_details": exc.details or {}},
        )
    return problem_details(request, exc)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    import logging

    logger = logging.getLogger("neuralcut.errors")
    logger.error(
        "unhandled exception",
        exc_info=(type(exc), exc, exc.__traceback__),
        extra={"path": str(request.url.path)},
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ProblemDetails(
            title="Internal server error",
            code="internal_error",
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            instance=str(request.url.path),
        ).model_dump(exclude_none=True),
    )
