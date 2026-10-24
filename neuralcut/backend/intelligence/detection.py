"""Motion-based object detection, tracking, and masks (Phase 3).

Deliberately dependency-free: frames are extracted with ffmpeg at a small
analysis resolution and processed in pure Python. The detector estimates a
per-pixel background (median across sampled frames), thresholds the
difference, extracts connected components as bounding boxes, and links
boxes across frames into tracks (greedy centroid/IoU association). Masks
are stored as row-major run-length encodings at analysis resolution.

Honest scope: this detects *moving* regions against a mostly static
background. It does not semantically classify objects (a moving box is a
"moving_object", not a "car") and it degrades with camera motion, lighting
changes, or objects that stop for long periods. The detector interface is
kept narrow so a future ML detector (Phase 5-era, opt-in model) can emit
the same track representation. All of this is documented in the UI/docs.
"""

from __future__ import annotations

import math
from typing import Any


def rle_encode(mask: list[bool]) -> list[int]:
    """Run-length encode a boolean list: [run0_len, run1_len, ...] starting
    with the run of False values (possibly 0)."""
    runs: list[int] = []
    current = False
    count = 0
    for value in mask:
        if value == current:
            count += 1
        else:
            runs.append(count)
            current = value
            count = 1
    runs.append(count)
    return runs


def rle_decode(runs: list[int], size: int) -> list[bool]:
    out: list[bool] = []
    value = False
    for length in runs:
        out.extend([value] * length)
        value = not value
    return out[:size]


def _components(mask: list[bool], width: int, height: int,
                min_area: int) -> list[dict[str, Any]]:
    visited = bytearray(width * height)
    components: list[dict[str, Any]] = []
    for start in range(width * height):
        if not mask[start] or visited[start]:
            continue
        # BFS flood fill
        stack = [start]
        visited[start] = 1
        pixels: list[int] = []
        min_x, max_x = width, -1
        min_y, max_y = height, -1
        while stack:
            idx = stack.pop()
            pixels.append(idx)
            x, y = idx % width, idx // width
            min_x, max_x = min(min_x, x), max(max_x, x)
            min_y, max_y = min(min_y, y), max(max_y, y)
            for neighbor in (idx - 1, idx + 1, idx - width, idx + width):
                if neighbor < 0 or neighbor >= width * height or visited[neighbor]:
                    continue
                # avoid wrapping across rows for left/right neighbors
                if neighbor == idx - 1 and idx % width == 0:
                    continue
                if neighbor == idx + 1 and idx % width == width - 1:
                    continue
                if mask[neighbor]:
                    visited[neighbor] = 1
                    stack.append(neighbor)
        if len(pixels) >= min_area:
            comp_mask = [False] * (width * height)
            for idx in pixels:
                comp_mask[idx] = True
            components.append({
                "bbox_px": [min_x, min_y, max_x - min_x + 1, max_y - min_y + 1],
                "area_px": len(pixels),
                "mask": comp_mask,
                "centroid_px": [
                    sum(i % width for i in pixels) / len(pixels),
                    sum(i // width for i in pixels) / len(pixels),
                ],
            })
    return components


def _iou(a: list[float], b: list[float]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    return inter / (aw * ah + bw * bh - inter)


def detect_and_track(
    frames: list[bytes],
    *,
    width: int,
    height: int,
    times: list[float],
    source_width: int,
    source_height: int,
    diff_threshold: int = 28,
    min_area_fraction: float = 0.002,
    max_centroid_jump_fraction: float = 0.25,
) -> list[dict[str, Any]]:
    """Detect moving regions and link them into tracks.

    ``frames`` are raw grayscale bytes at analysis resolution. Returns track
    dicts with normalized bboxes (0..1), per-frame RLE masks at analysis
    resolution, and aggregate motion stats.
    """
    if len(frames) < 3:
        return []
    pixel_count = width * height
    # Background: per-pixel median across frames (robust to a moving object
    # occupying each pixel for a minority of the time).
    background = bytearray(pixel_count)
    middle = len(frames) // 2
    columns = zip(*frames, strict=True)  # each item: one pixel across all frames
    for idx, column in enumerate(columns):
        background[idx] = sorted(column)[middle]
    min_area = max(4, int(pixel_count * min_area_fraction))
    max_jump = math.hypot(width, height) * max_centroid_jump_fraction
    scale_x = 1.0 / width
    scale_y = 1.0 / height

    tracks: list[dict[str, Any]] = []
    active: list[dict[str, Any]] = []

    for frame_index, frame in enumerate(frames):
        mask = [abs(frame[i] - background[i]) > diff_threshold for i in range(pixel_count)]
        detections = _components(mask, width, height, min_area)
        matched_track_ids: set[int] = set()
        for detection in detections:
            bbox_norm = [
                detection["bbox_px"][0] * scale_x,
                detection["bbox_px"][1] * scale_y,
                detection["bbox_px"][2] * scale_x,
                detection["bbox_px"][3] * scale_y,
            ]
            best: dict[str, Any] | None = None
            best_score = -1.0
            for track in active:
                if track["id"] in matched_track_ids:
                    continue
                last = track["frames"][-1]
                if times[frame_index] - last["time_seconds"] > 2.0:
                    continue
                cx, cy = detection["centroid_px"]
                lx = (last["bbox"][0] + last["bbox"][2] / 2) * width
                ly = (last["bbox"][1] + last["bbox"][3] / 2) * height
                distance = math.hypot(cx - lx, cy - ly)
                if distance > max_jump:
                    continue
                score = _iou(bbox_norm, last["bbox"]) - distance / (max_jump * 10)
                if score > best_score:
                    best_score = score
                    best = track
            entry = {
                "time_seconds": round(times[frame_index], 3),
                "bbox": [round(v, 4) for v in bbox_norm],
                "mask_rle": rle_encode(detection["mask"]),
                "area_fraction": round(detection["area_px"] / pixel_count, 5),
            }
            if best is None:
                best = {
                    "id": f"track-{len(tracks) + 1}",
                    "label": "moving_object",
                    "detector": "motion-background-subtraction",
                    "frames": [],
                }
                tracks.append(best)
                active.append(best)
            best["frames"].append(entry)
            matched_track_ids.add(best["id"])
        active = [
            t for t in active
            if times[frame_index] - t["frames"][-1]["time_seconds"] <= 2.0
        ]

    result: list[dict[str, Any]] = []
    for track in tracks:
        if len(track["frames"]) < 2:
            continue  # single-frame noise is not a track
        frames_list = track["frames"]
        first, last = frames_list[0], frames_list[-1]
        displacement = math.hypot(
            (last["bbox"][0] + last["bbox"][2] / 2) - (first["bbox"][0] + first["bbox"][2] / 2),
            (last["bbox"][1] + last["bbox"][3] / 2) - (first["bbox"][1] + first["bbox"][3] / 2),
        )
        track = dict(track)
        track.update({
            "start_seconds": first["time_seconds"],
            "end_seconds": last["time_seconds"],
            "frame_count": len(frames_list),
            "displacement": round(displacement, 4),
            "mask_resolution": [width, height],
            "source_resolution": [source_width, source_height],
        })
        result.append(track)
    result.sort(key=lambda t: (t["start_seconds"], t["id"]))
    # Renumber after filtering so ids are stable and gapless.
    for index, track in enumerate(result, start=1):
        track["id"] = f"track-{index}"
    return result
