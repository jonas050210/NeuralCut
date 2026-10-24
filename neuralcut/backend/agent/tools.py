"""Agent tool registry: strict schemas, risk levels, permission boundary.

The agent can only ever invoke the tools declared here. Every call is
validated twice: (1) against the JSON-schema-style argument spec in this
registry (types, required fields, ranges, enums), and (2) semantically by
the deterministic services underneath (existing IDs, timeline invariants,
parameter ranges). Model output is data — it is never executed as code,
never reaches a shell, and tools are implemented as direct calls into
``TimelineService``/job submission.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from neuralcut.errors import ValidationError

RISK_READ = "read"          # no state change; may auto-execute
RISK_EDIT = "edit"          # reversible project edit; approval required
RISK_EXTERNAL = "external"  # creates files/jobs outside the project doc; approval required


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str = Field(min_length=1, max_length=60)
    args: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_tool(self) -> "ToolCall":
        if self.tool not in TOOL_REGISTRY:
            raise ValueError(f"unknown tool: {self.tool}")
        validate_args(self.tool, self.args)
        return self


def _type_ok(value: Any, type_name: str) -> bool:
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "object":
        return isinstance(value, dict)
    if type_name == "array":
        return isinstance(value, list)
    return False


# arg spec: name -> (type, required, min, max)  (min/max numeric or length)
TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    "answer_question": {"risk": RISK_READ, "args": {"question": ("string", False, 0, 2000)}},
    "get_project_state": {"risk": RISK_READ, "args": {}},
    "import_media": {"risk": RISK_EXTERNAL, "args": {"path": ("string", True, 1, 2000)}},
    "add_clip": {"risk": RISK_EDIT, "args": {
        "asset_id": ("string", True, 1, 200), "track": ("integer", False, 0, 64),
        "timeline_start_seconds": ("number", False, 0, 86400),
        "source_start_seconds": ("number", False, 0, 86400),
        "source_end_seconds": ("number", False, 0, 86400)}},
    "move_clip": {"risk": RISK_EDIT, "args": {
        "clip_id": ("string", True, 1, 200),
        "timeline_start_seconds": ("number", True, 0, 86400),
        "track": ("integer", False, 0, 64)}},
    "trim_clip": {"risk": RISK_EDIT, "args": {
        "clip_id": ("string", True, 1, 200),
        "source_start_seconds": ("number", False, 0, 86400),
        "source_end_seconds": ("number", False, 0, 86400)}},
    "split_clip": {"risk": RISK_EDIT, "args": {
        "clip_id": ("string", True, 1, 200),
        "at_timeline_seconds": ("number", True, 0, 86400)}},
    "remove_clip": {"risk": RISK_EDIT, "args": {"clip_id": ("string", True, 1, 200)}},
    "add_effect": {"risk": RISK_EDIT, "args": {
        "clip_id": ("string", True, 1, 200), "type": ("string", False, 0, 50),
        "preset": ("string", False, 0, 100), "params": ("object", False, 0, 0)}},
    "update_effect": {"risk": RISK_EDIT, "args": {
        "clip_id": ("string", True, 1, 200), "effect_id": ("string", True, 1, 200),
        "params": ("object", False, 0, 0), "enabled": ("boolean", False, 0, 0)}},
    "remove_effect": {"risk": RISK_EDIT, "args": {
        "clip_id": ("string", True, 1, 200), "effect_id": ("string", True, 1, 200)}},
    "set_keyframes": {"risk": RISK_EDIT, "args": {
        "clip_id": ("string", True, 1, 200), "effect_id": ("string", True, 1, 200),
        "property": ("string", True, 1, 50), "keyframes": ("array", True, 0, 200)}},
    "undo": {"risk": RISK_EDIT, "args": {}},
    "redo": {"risk": RISK_EDIT, "args": {}},
    "analyze_asset": {"risk": RISK_EXTERNAL, "args": {
        "asset_id": ("string", True, 1, 200), "force": ("boolean", False, 0, 0)}},
    "start_render": {"risk": RISK_EXTERNAL, "args": {
        "output_path": ("string", True, 1, 2000),
        "width": ("integer", False, 16, 7680), "height": ("integer", False, 16, 4320),
        "fps": ("number", False, 1, 240)}},
}


def validate_args(tool: str, args: dict[str, Any]) -> None:
    spec = TOOL_REGISTRY[tool]["args"]
    for name in args:
        if name not in spec:
            raise ValidationError(
                f"tool {tool} does not accept argument {name!r}",
                details={"tool": tool, "known_args": sorted(spec)},
            )
    for name, (type_name, required, lo, hi) in spec.items():
        if name not in args:
            if required:
                raise ValidationError(
                    f"tool {tool} requires argument {name!r}", details={"tool": tool}
                )
            continue
        value = args[name]
        if not _type_ok(value, type_name):
            raise ValidationError(
                f"tool {tool} argument {name!r} must be {type_name}",
                details={"tool": tool, "arg": name},
            )
        if type_name in {"number", "integer"} and not (lo <= float(value) <= hi):
            raise ValidationError(
                f"tool {tool} argument {name!r}={value} out of range [{lo}, {hi}]",
                details={"tool": tool, "arg": name},
            )
        if type_name == "string" and hi and len(value) > hi:
            raise ValidationError(
                f"tool {tool} argument {name!r} is too long", details={"tool": tool}
            )


def tool_schemas() -> dict[str, Any]:
    """JSON-schema-style description handed to models and shown in the UI."""
    out: dict[str, Any] = {}
    for name, entry in TOOL_REGISTRY.items():
        properties = {}
        required = []
        for arg, (type_name, req, lo, hi) in entry["args"].items():
            prop: dict[str, Any] = {"type": type_name}
            if type_name in {"number", "integer"}:
                prop["minimum"], prop["maximum"] = lo, hi
            properties[arg] = prop
            if req:
                required.append(arg)
        out[name] = {
            "risk": entry["risk"],
            "parameters": {"type": "object", "properties": properties,
                           "required": required, "additionalProperties": False},
        }
    return out


def plan_risk(calls: list[ToolCall]) -> str:
    risks = {TOOL_REGISTRY[c.tool]["risk"] for c in calls}
    if risks <= {RISK_READ}:
        return RISK_READ
    if RISK_EXTERNAL in risks:
        return RISK_EXTERNAL
    return RISK_EDIT
