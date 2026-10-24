"""Versioned benchmark datasets: synthetic cases, provenance, splits.

Every case is generated from a template in this file -- no user media, no
user projects, no external downloads. Each case records its provenance
(generator, template id, setup, expectation) so a benchmark report can be
reproduced exactly from the dataset version + code version.

Splits are assigned deterministically by template order (60% train / 20%
validation / 20% held-out, cycling per template family), which splits by
*task template and setup*, not by random rows -- the leakage control the
Phase 6 roadmap requires. Held-out cases are flagged ``sealed``: the
runner uses them only for promotion-gate evaluation, never for tuning.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

DATASET_VERSION = "1.0.0"
GENERATOR = "neuralcut.synthetic_templates"

# setup kinds: empty | single | single_plus_asset | two | ambiguous
# expect kinds: answer | clips | effect | clarification | clip_start
CASE_TEMPLATES: list[dict[str, Any]] = [
    {"id": "q-duration", "setup": "single",
     "instruction": "how long is my timeline?",
     "expect": {"kind": "answer"}},
    {"id": "q-effects", "setup": "single",
     "instruction": "what effects do my clips have?",
     "expect": {"kind": "answer"}},
    {"id": "split-hero", "setup": "single",
     "instruction": "split clip hero at 1s",
     "expect": {"kind": "clips", "count": 2}},
    {"id": "trim-hero", "setup": "single",
     "instruction": "trim clip hero from 0.5s to 2s",
     "expect": {"kind": "clips", "count": 1}},
    {"id": "glow-hero", "setup": "single",
     "instruction": "add glow to clip hero",
     "expect": {"kind": "effect", "type": "glow"}},
    {"id": "fade-hero", "setup": "single",
     "instruction": "fade in clip hero",
     # The fade-in preset is keyframed opacity on the transform effect.
     "expect": {"kind": "effect", "type": "transform"}},
    {"id": "brighter-hero", "setup": "single",
     "instruction": "make clip hero brighter",
     "expect": {"kind": "effect", "type": "color"}},
    {"id": "remove-broll", "setup": "two",
     "instruction": "remove clip broll",
     "expect": {"kind": "clips", "count": 1}},
    {"id": "move-broll", "setup": "two",
     "instruction": "move clip broll to 6s",
     "expect": {"kind": "clip_start", "name": "broll", "start": 6.0}},
    {"id": "add-broll-to-timeline", "setup": "single_plus_asset",
     "instruction": "add broll to the timeline",
     "expect": {"kind": "clips", "count": 2}},
    {"id": "ambiguous-split", "setup": "ambiguous",
     "instruction": "split clip hero at 1s",
     "expect": {"kind": "clarification"}},
    {"id": "unknown-clip", "setup": "single",
     "instruction": "split clip wizard at 1s",
     "expect": {"kind": "clarification"}},
    {"id": "unsupported-request", "setup": "single",
     "instruction": "make it cinematic",
     "expect": {"kind": "clarification"}},
    {"id": "split-broll", "setup": "two",
     "instruction": "split clip broll at 4s",
     "expect": {"kind": "clips", "count": 3}},
]

_SPLIT_CYCLE = ("train", "train", "train", "val", "held_out")


def build_cases() -> list[dict[str, Any]]:
    """Materialize the deterministic case list with splits + provenance."""
    cases: list[dict[str, Any]] = []
    for index, template in enumerate(CASE_TEMPLATES):
        split = _SPLIT_CYCLE[index % len(_SPLIT_CYCLE)]
        cases.append({
            **template,
            "split": split,
            "sealed": split == "held_out",
            "provenance": {
                "source": "synthetic_template",
                "generator": GENERATOR,
                "template_id": template["id"],
                "setup": template["setup"],
                "license": "generated in-process; no external media",
            },
        })
    return cases


def dataset_fingerprint(cases: list[dict[str, Any]] | None = None) -> str:
    payload = json.dumps(cases or build_cases(), sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def build_manifest() -> dict[str, Any]:
    cases = build_cases()
    counts: dict[str, int] = {}
    for case in cases:
        counts[case["split"]] = counts.get(case["split"], 0) + 1
    return {
        "dataset_version": DATASET_VERSION,
        "generator": GENERATOR,
        "fingerprint": dataset_fingerprint(cases),
        "case_count": len(cases),
        "split_counts": counts,
        "split_policy": (
            "deterministic cycle per template (3 train / 1 val / 1 held_out); "
            "splits are by task template + setup, never random rows"),
        "provenance_policy": (
            "all cases synthetic, generated in-process from templates in "
            "backend/improvement/datasets.py; no user media or projects"),
        "cases": cases,
    }


def save_manifest(data_dir: str | Path) -> Path:
    target_dir = Path(data_dir) / "improvement" / "datasets"
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"benchmark-{DATASET_VERSION}.json"
    path.write_text(json.dumps(build_manifest(), indent=2, sort_keys=True),
                    encoding="utf-8")
    return path
