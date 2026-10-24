"""Built-in deterministic planner (works with no model at all).

Parses a bounded set of well-defined intents into validated tool calls.
Anything ambiguous (unknown or non-unique clip/asset references, missing
paths/times, unsupported requests) becomes a clarification request with
**no** executable steps — the agent never guesses IDs or fabricates media.
"""

from __future__ import annotations

import re
from typing import Any

from neuralcut.backend.agent.tools import ToolCall

MEDIA_EXT = r"(?:mp4|mov|mkv|webm|avi|m4v|mp3|wav)"
SUPPORTED = [
    'import "C:\\path\\to\\video.mp4"',
    "add <asset name> to the timeline",
    "move clip <name> to 5s",
    "trim clip <name> from 1s to 3s",
    "split clip <name> at 2s",
    "remove clip <name>",
    "add glow to clip <name>  /  fade in clip <name>  /  make clip <name> brighter",
    "analyze <asset name>",
    'export to "C:\\path\\export.mp4"',
    "undo  /  redo",
    "how long is my timeline?  /  what clips do I have?",
]


def _resolve(ref: str, items: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str | None]:
    ref = (ref or "").strip().strip('"').strip()
    if not ref:
        return None, "no reference given"
    for item in items:
        if item["id"] == ref:
            return item, None
    matches = [i for i in items if ref.lower() in str(i.get("name", "")).lower()]
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        names = ", ".join(str(m.get("name")) for m in matches)
        return None, f"'{ref}' matches multiple items ({names}); be more specific"
    return None, f"no clip/asset matches '{ref}'"


def _num(text: str) -> float:
    return float(text.replace(",", "."))


def builtin_plan(message: str, context: dict[str, Any]) -> dict[str, Any]:
    """Return {steps, explanation, answer?, clarification?}."""
    msg = message.strip()
    low = msg.lower()
    assets = context.get("assets", [])
    clips = context.get("clips", [])

    def clarification(text: str) -> dict[str, Any]:
        return {"steps": [], "explanation": text, "clarification": text}

    # Questions / read-only
    if low.startswith(("how", "what", "which", "list", "show", "tell")) or low.endswith("?"):
        answer = _answer(msg, context)
        return {"steps": [ToolCall(tool="answer_question", args={"question": msg})],
                "explanation": "Read-only question about project state.", "answer": answer}

    if re.fullmatch(r"undo\.?", low):
        return {"steps": [ToolCall(tool="undo")], "explanation": "Undo the last edit."}
    if re.fullmatch(r"redo\.?", low):
        return {"steps": [ToolCall(tool="redo")], "explanation": "Redo."}

    # Import: quoted path or a bare media path token
    path_match = re.search(r'"([^"]+\.' + MEDIA_EXT + r')"', msg, re.IGNORECASE)
    if not path_match:
        path_match = re.search(r"(\S+\." + MEDIA_EXT + r")\b", msg, re.IGNORECASE)
    if low.startswith(("import", "add media", "add video")) or (
        path_match and ("import" in low or "add" in low)
    ):
        if not path_match:
            return clarification("Which file should I import? Give a full local path.")
        return {"steps": [ToolCall(tool="import_media", args={"path": path_match.group(1)})],
                "explanation": f"Import {path_match.group(1)}."}

    # Export / render
    if low.startswith(("export", "render")):
        out = re.search(r'"([^"]+\.mp4)"', msg, re.IGNORECASE) or re.search(
            r"(\S+\.mp4)\b", msg, re.IGNORECASE)
        if not out:
            return clarification('Where should I export? Example: export to "C:\\Videos\\out.mp4".')
        return {"steps": [ToolCall(tool="start_render", args={"output_path": out.group(1)})],
                "explanation": f"Render the timeline to {out.group(1)} as a background job."}

    # Analyze
    if low.startswith(("analyze", "analyse")):
        ref = re.sub(r"^(analyze|analyse)\s+", "", msg, flags=re.IGNORECASE)
        asset, err = _resolve(ref, assets)
        if err:
            return clarification(f"Cannot analyze: {err}.")
        return {"steps": [ToolCall(tool="analyze_asset", args={"asset_id": asset["id"]})],
                "explanation": f"Analyze asset {asset['name']} as a background job."}

    # Split clip X at Ns
    match = re.search(r"split\s+(?:clip\s+)?(.+?)\s+at\s+([0-9.,]+)\s*s?\b", msg, re.IGNORECASE)
    if match or low.startswith("split"):
        if not match:
            return clarification("Split needs a clip and a time: 'split clip <name> at 2s'.")
        clip, err = _resolve(match.group(1), clips)
        if err:
            return clarification(f"Cannot split: {err}.")
        return {"steps": [ToolCall(tool="split_clip", args={
            "clip_id": clip["id"], "at_timeline_seconds": _num(match.group(2))})],
            "explanation": f"Split {clip['name']} at {match.group(2)}s."}

    # Move clip X to Ns
    match = re.search(r"move\s+(?:clip\s+)?(.+?)\s+to\s+([0-9.,]+)\s*s?\b", msg, re.IGNORECASE)
    if match or low.startswith("move"):
        if not match:
            return clarification("Move needs a clip and a target time: 'move clip <name> to 5s'.")
        clip, err = _resolve(match.group(1), clips)
        if err:
            return clarification(f"Cannot move: {err}.")
        return {"steps": [ToolCall(tool="move_clip", args={
            "clip_id": clip["id"], "timeline_start_seconds": _num(match.group(2))})],
            "explanation": f"Move {clip['name']} to {match.group(2)}s."}

    # Trim clip X from As to Bs
    match = re.search(
        r"trim\s+(?:clip\s+)?(.+?)\s+from\s+([0-9.,]+)\s*s?\s+to\s+([0-9.,]+)\s*s?\b",
        msg, re.IGNORECASE)
    if match or low.startswith("trim"):
        if not match:
            return clarification(
                "Trim needs source in/out times: 'trim clip <name> from 1s to 3s'.")
        clip, err = _resolve(match.group(1), clips)
        if err:
            return clarification(f"Cannot trim: {err}.")
        return {"steps": [ToolCall(tool="trim_clip", args={
            "clip_id": clip["id"],
            "source_start_seconds": _num(match.group(2)),
            "source_end_seconds": _num(match.group(3))})],
            "explanation": f"Trim {clip['name']} to source {match.group(2)}–{match.group(3)}s."}

    # Remove clip X
    if low.startswith(("remove", "delete")):
        ref = re.sub(r"^(remove|delete)\s+(clip\s+)?", "", msg, flags=re.IGNORECASE)
        clip, err = _resolve(ref, clips)
        if err:
            return clarification(f"Cannot remove: {err}.")
        return {"steps": [ToolCall(tool="remove_clip", args={"clip_id": clip["id"]})],
                "explanation": f"Remove clip {clip['name']} from the timeline."}

    # Fade in clip X
    match = re.search(r"fade\s+in\s+(?:clip\s+)?(.+)$", msg, re.IGNORECASE)
    if match:
        clip, err = _resolve(match.group(1), clips)
        if err:
            return clarification(f"Cannot fade: {err}.")
        return {"steps": [ToolCall(tool="add_effect", args={
            "clip_id": clip["id"], "preset": "fade-in"})],
            "explanation": f"Add a fade-in (keyframed opacity) to {clip['name']}."}

    # Make clip X brighter / add <effect> to clip X
    match = re.search(r"make\s+(?:clip\s+)?(.+?)\s+brighter\b", msg, re.IGNORECASE)
    if match:
        clip, err = _resolve(match.group(1), clips)
        if err:
            return clarification(f"Cannot restyle: {err}.")
        return {"steps": [ToolCall(tool="add_effect", args={
            "clip_id": clip["id"], "type": "color", "params": {"brightness": 0.2}})],
            "explanation": f"Make {clip['name']} brighter (+0.2 brightness effect)."}
    match = re.search(r"add\s+(glow|bloom|blur)\s+to\s+(?:clip\s+)?(.+)$", msg, re.IGNORECASE)
    if match:
        clip, err = _resolve(match.group(2), clips)
        if err:
            return clarification(f"Cannot add effect: {err}.")
        return {"steps": [ToolCall(tool="add_effect", args={
            "clip_id": clip["id"], "type": match.group(1).lower()})],
            "explanation": f"Add a {match.group(1).lower()} effect to {clip['name']}."}

    # Add <asset> to the timeline / track N
    if low.startswith("add") and ("timeline" in low or "track" in low):
        ref = re.sub(r"^add\s+", "", msg, flags=re.IGNORECASE)
        ref = re.sub(r"\s+to\s+(the\s+)?(timeline|track\s*\d*).*$", "", ref, flags=re.IGNORECASE)
        asset, err = _resolve(ref, assets)
        if err:
            return clarification(f"Cannot add clip: {err}.")
        track_match = re.search(r"track\s*(\d+)", low)
        args: dict[str, Any] = {"asset_id": asset["id"]}
        if track_match:
            args["track"] = int(track_match.group(1))
        return {"steps": [ToolCall(tool="add_clip", args=args)],
                "explanation": f"Add {asset['name']} to the timeline."}

    return clarification(
        "I can't map that to a supported, safe editing operation. Supported examples: "
        + "; ".join(SUPPORTED)
    )


def _answer(message: str, context: dict[str, Any]) -> str:
    low = message.lower()
    assets = context.get("assets", [])
    clips = context.get("clips", [])
    if "long" in low or "duration" in low:
        return (
            f"The timeline is {context.get('duration_seconds', 0):.2f}s long "
            f"across {len(clips)} clip(s)."
        )
    if "object" in low or "track" in low and "timeline" not in low:
        return context.get("analysis_summary") or (
            "No analysis results are loaded for the project assets yet. "
            "Run Analyze on an asset first."
        )
    if "asset" in low or "media" in low or "footage" in low:
        if not assets:
            return "No media has been imported yet."
        return "Assets: " + "; ".join(
            f"{a['name']} ({a.get('duration_seconds') or 0:.1f}s"
            + (", MISSING FILE" if a.get("missing") else "") + ")" for a in assets)
    if "effect" in low:
        lines = [
            f"{c['name']}: {', '.join(e['type'] for e in c.get('effects', [])) or 'no effects'}"
            for c in clips
        ]
        return "Clip effects — " + ("; ".join(lines) if lines else "no clips yet.")
    if not clips:
        return "The timeline is empty. Import media and add a clip to get started."
    return "Timeline clips: " + "; ".join(
        f"{c['name']} (track {c['track']}, {c['timeline_start_seconds']:.1f}s–"
        f"{c['timeline_end_seconds']:.1f}s)" for c in clips)
