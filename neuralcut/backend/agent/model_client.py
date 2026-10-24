"""Model routing for the Phase 5 agent.

Routing is deterministic and explicit:

- models disabled or provider ``builtin`` -> the built-in deterministic
  planner (no model, no network, always available).
- provider ``local`` -> an OpenAI-compatible endpoint (Ollama, llama.cpp
  server, ...) that the *user* runs locally; requires endpoint + model.
- provider ``cloud`` -> only when ``allow_cloud`` is explicitly true and an
  API key exists in the configured environment variable. Nothing is ever
  sent to a cloud endpoint silently.

The model may only return a JSON plan (tool names + arguments). It cannot
execute anything; plans are schema-validated and, for consequential tools,
require user approval before execution.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Callable

from neuralcut.backend.agent.tools import ToolCall, tool_schemas
from neuralcut.errors import UnavailableError, ValidationError

Transport = Callable[[str, dict[str, Any], dict[str, str], float], dict[str, Any]]


def _urllib_transport(url: str, payload: dict[str, Any],
                      headers: dict[str, str], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(  # noqa: S310 - URL from validated local config
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _extract_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object out of model output, tolerating code fences and
    surrounding prose. Strict afterwards: the result must be an object."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        lines = lines[1:] if lines and lines[0].startswith("```") else lines
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise ValidationError("model did not return valid JSON") from None
        try:
            parsed = json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError as exc:
            raise ValidationError(f"model did not return valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValidationError("model response must be a JSON object")
    return parsed


class ModelRouter:
    def __init__(self, settings, transport: Transport | None = None) -> None:  # noqa: ANN001
        self.models = settings.models
        self.transport = transport or _urllib_transport

    def route(self) -> dict[str, Any]:
        """Describe the active route without contacting anything."""
        if not self.models.enabled or self.models.provider == "builtin":
            return {"mode": "builtin", "model": None,
                    "detail": "deterministic built-in planner (no model, no network)"}
        if self.models.provider == "local":
            if not self.models.endpoint or not self.models.model:
                return {"mode": "builtin", "model": None,
                        "detail": "local provider selected but endpoint/model not "
                                  "configured; falling back to built-in planner"}
            return {"mode": "local", "model": self.models.model,
                    "detail": f"OpenAI-compatible local endpoint {self.models.endpoint}"}
        # cloud
        if not self.models.allow_cloud:
            return {"mode": "builtin", "model": None,
                    "detail": "cloud provider selected but allow_cloud=false; "
                              "falling back to built-in planner"}
        if not self.models.endpoint or not self.models.model:
            return {"mode": "builtin", "model": None,
                    "detail": "cloud provider selected but endpoint/model not configured; "
                              "falling back to built-in planner"}
        if not os.environ.get(self.models.api_key_env):
            return {"mode": "builtin", "model": None,
                    "detail": f"cloud API key env var {self.models.api_key_env} is not set; "
                              "falling back to built-in planner"}
        return {"mode": "cloud", "model": self.models.model,
                "detail": f"cloud endpoint {self.models.endpoint} (explicitly allowed)"}

    def status(self) -> dict[str, Any]:
        route = self.route()
        return {
            "enabled": self.models.enabled,
            "provider": self.models.provider,
            "route": route,
            "endpoint": self.models.endpoint,
            "model": self.models.model,
            "allow_cloud": self.models.allow_cloud,
            "lazy": True,
            "note": "models are optional and never loaded at startup; "
                    "the built-in planner works without any model",
        }

    def generate_plan(self, message: str, context: dict[str, Any]) -> tuple[list[ToolCall], str]:
        """Ask the configured model for a JSON plan. Raises on any problem;
        the caller falls back to the built-in planner."""
        route = self.route()
        if route["mode"] == "builtin":
            raise UnavailableError("no external model routed", details=route)
        headers: dict[str, str] = {}
        if route["mode"] == "cloud":
            headers["Authorization"] = f"Bearer {os.environ[self.models.api_key_env]}"
        system = (
            "You are NeuralCut's editing planner. Reply with ONLY a JSON object: "
            '{"steps": [{"tool": "<tool name>", "args": {...}}], "explanation": "<short text>"}. '
            "Use only these tools and argument schemas: "
            + json.dumps(tool_schemas())
            + ". Never invent asset/clip/effect IDs; use only IDs from the project context. "
            "If the request is ambiguous or unsupported, reply with {\"steps\": [], "
            "\"explanation\": \"<what you need clarified>\"}."
        )
        payload = {
            "model": self.models.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(
                    {"request": message, "project_context": context})},
            ],
        }
        url = self.models.endpoint.rstrip("/") + "/chat/completions"
        try:
            response = self.transport(url, payload, headers, self.models.timeout_seconds)
            content = response["choices"][0]["message"]["content"]
        except Exception as exc:  # noqa: BLE001 - surfaced as fallback reason
            raise UnavailableError(
                f"model endpoint failed: {type(exc).__name__}: {exc}",
                details={"endpoint": self.models.endpoint},
            ) from exc
        if isinstance(content, str):
            content = _extract_json_object(content)
        if not isinstance(content, dict) or "steps" not in content:
            raise ValidationError("model response must be an object with a 'steps' list")
        calls = []
        for raw in content["steps"]:
            if not isinstance(raw, dict) or "tool" not in raw:
                raise ValidationError("each plan step must be an object with a 'tool'")
            calls.append(ToolCall.model_validate(
                {"tool": raw["tool"], "args": raw.get("args") or {}}))
        return calls, str(content.get("explanation") or "")
