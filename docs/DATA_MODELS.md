# Data Models

This document describes the canonical project data model (schema v3, Phases 2–4) and the Phase 3 derived-analysis artifact format.
The code of record is `neuralcut/backend/projects/model.py`; this file explains
semantics and invariants for humans and future phases.

## Project document (`.neuralcut`, schema version 2)

```json
{
  "version": 3,
  "id": "…",
  "name": "My project",
  "created_at": "…", "modified_at": "…",
  "assets": [ … ],
  "clips": [ … ],
  "export_settings": { "width": 1280, "height": 720, "fps": 30.0, "crf": 23, "preset": "veryfast" },
  "settings": {},
  "metadata": {}
}
```

Files are pretty-printed JSON, written atomically (temp file + replace), and
validated with Pydantic on load. Future schema versions are rejected with a
clear error; older versions are migrated (see below).

## ProjectAsset

| Field | Meaning |
|---|---|
| `id` | Opaque id (`[A-Za-z0-9_.-]+`) |
| `name` | Display name (source file name at import) |
| `path` | Absolute/relative local path of the source file. **Referenced, not copied.** |
| `kind` | `video`, `audio`, or `image` (from probing) |
| `duration_seconds` | Probed duration, or `null` if unknown |
| `width` / `height` / `fps` | Probed video metadata, `null` when unknown |
| `has_audio` | Whether an audio stream was found (drives silence generation at export) |
| `codec` | Primary codec name from probing |
| `added_at` | Import timestamp (UTC ISO-8601) |

Importing the same path twice returns the existing asset (no duplicate).
If the file later disappears, the API marks the asset `missing`, clip
operations on it fail with a validation error, and export aborts with the
offending path in the message.

## ProjectClip (timeline clip)

| Field | Meaning |
|---|---|
| `id` | Opaque clip id |
| `asset_id` | References `ProjectAsset.id` (must exist) |
| `name` | Display name |
| `track` | Track index ≥ 0 |
| `timeline_start_seconds` | Where the clip starts in the edited output (≥ 0) |
| `source_start_seconds` | In-point inside the source asset (≥ 0) |
| `source_end_seconds` | Out-point inside the source asset (> in-point, ≤ asset duration when known) |

Derived: `duration_seconds = source_end − source_start`,
`timeline_end = timeline_start + duration`. There are no speed changes,
effects, or transitions in Phase 2, so a clip's timeline duration always
equals its source-range duration.

### Invariants (enforced by the model and `TimelineService`)

- Clip ids and asset ids are unique; clips reference existing assets.
- Clips on the **same track must not overlap** (gaps are allowed).
- Editing operations never produce an invalid project: `TimelineService`
  validates the full mutated document before committing it, so a rejected
  edit leaves the previous state (and undo history) untouched.
- Export additionally requires the flattened sequence (sorted by timeline
  start, then track, then id) to be non-overlapping; cross-track overlaps
  are reported instead of being composited (compositing is a later phase).

## Undo/redo representation

Undo history is **not** stored in the project file. `TimelineService` keeps
in-memory snapshots (full project JSON, max 100) of the state before each
edit. Undo/redo swaps the current project with a snapshot, which guarantees
exact restoration for every operation type. History resets when a different
project is opened/created and is lost when the backend exits. Edits are not
auto-saved; “Save project” writes the current state.

## ExportSettings

Stored in the project as defaults; a render request may override
width/height/fps/crf per export. Phase 2 renders MP4 (libx264 + AAC,
yuv420p, 48 kHz stereo) only.

## Schema history and migration

| Version | Phase | Contents |
|---|---|---|
| 1 | Foundation | Asset/clip references; clips had only `start_seconds`/`end_seconds` (source range) |
| 2 | Editing Core | Timeline placement, names, probed asset metadata, export settings |
| 3 | Effects & Animation | Ordered per-clip `effects` with keyframes (v2→v3 migration adds empty lists) |

Migrations operate on the **raw JSON dict** before Pydantic validation
(`RAW_MIGRATIONS` in `projects/model.py`), so renamed fields survive
translation. The v1→v2 migration places each track's clips sequentially in
file order starting at 0s, preserving each clip's source range and duration.
Loading a migrated project and saving it writes schema v2.

Rule for future changes: bump `PROJECT_SCHEMA_VERSION`, add a raw-dict
migration, add a load test with a real old-version document, and record the
change in `CHANGELOG.md` and `DECISIONS.md`.

## ClipEffect and keyframes (schema v3, Phase 4)

Each clip carries an ordered `effects` list. Effects apply in list order in
the render pipeline; disabled effects are skipped but retained.

| Field | Meaning |
|---|---|
| `id` | Opaque effect instance id (unique per clip) |
| `type` | One of `transform`, `color`, `blur`, `glow`, `bloom` (registry: `backend/effects/engine.py`) |
| `enabled` | Whether the effect renders |
| `params` | Base parameter values (validated ranges in the registry) |
| `keyframes` | Map of parameter name → sorted `[{time_seconds, value, interpolation}]`, times are **clip-local** seconds, interpolation `linear` or `hold` (applies to the segment ending at that keyframe) |

Effective value at clip-local time *t*: keyframe evaluation if keyframes
exist for the parameter (clamped outside the keyframe range), else the base
param. `transform` is special: it is applied at compositing time
(opacity/scale/position), not as a stream filter. Rendering evaluates
keyframed values once per atomic interval (the spans between clip
boundaries) at the interval midpoint — this is the documented
preview/render parity rule; the browser preview evaluates the same values
at the playhead and applies CSS approximations.

Multi-track semantics: tracks composite bottom-to-top by track number;
within a track, clips never overlap (schema invariant). Gaps show the
layers beneath, or black when no layer is active.

## Analysis artifacts (Phase 3, derived data — not in the project file)

Stored as JSON at `<data_dir>/analysis/<fingerprint>.json` where the
fingerprint hashes file size, mtime, and sampled head/tail chunks — a
changed source file therefore invalidates the cache automatically.

| Field | Meaning |
|---|---|
| `version` | Artifact format version (currently 1) |
| `asset_id` / `asset_path` / `fingerprint` | Provenance |
| `analyzed_at` | UTC timestamp |
| `shots[]` | `index`, start/end, per-shot motion level, 12-dim color-histogram `embedding` (L2-normalized), `dominant_color`, heuristic `caption` |
| `tracks[]` | Motion tracks: `id`, `label: "moving_object"`, `detector`, start/end, `displacement` (frame fraction), per-frame `{time_seconds, bbox [x,y,w,h] normalized, mask_rle, area_fraction}`, `mask_resolution`, `source_resolution` |
| `speech_segments[]` | Non-silent ranges from ffmpeg `silencedetect` |
| `transcript` | `{status: ready|unavailable|failed, reason?, engine?, segments[]}` — segments include word timings only when the optional ASR engine actually ran |

Masks are run-length encoded row-major over the analysis-resolution grid
(96×54), starting with a False run (possibly 0). `rle_decode` in
`backend/intelligence/detection.py` is the reference decoder.
