"""Effect registry, parameter validation, keyframe evaluation, filters.

The registry is the single source of truth for which effects exist, their
parameters (defaults/ranges), and how they map to FFmpeg filters. Rendering
evaluates keyframed parameters at the midpoint of each atomic render
interval (see rendering/ffmpeg.py); the browser preview approximates the
same values with CSS filters at the current playhead. Both use the values
produced here, which is the documented preview/render parity strategy.
"""

from __future__ import annotations

from typing import Any

from neuralcut.backend.projects.model import ClipEffect, EffectKeyframe
from neuralcut.errors import ValidationError

# type -> {param: (default, min, max)}
EFFECT_REGISTRY: dict[str, dict[str, tuple[float, float, float]]] = {
    "transform": {
        "opacity": (1.0, 0.0, 1.0),
        "scale": (1.0, 0.1, 4.0),
        "x": (0.0, -1.0, 1.0),
        "y": (0.0, -1.0, 1.0),
    },
    "color": {
        "brightness": (0.0, -1.0, 1.0),
        "contrast": (1.0, 0.0, 3.0),
        "saturation": (1.0, 0.0, 3.0),
    },
    "blur": {"radius": (0.0, 0.0, 50.0)},
    "glow": {"strength": (0.5, 0.0, 1.0), "radius": (20.0, 0.0, 100.0)},
    "bloom": {
        "strength": (0.5, 0.0, 1.0),
        "radius": (20.0, 0.0, 100.0),
        "threshold": (0.7, 0.0, 1.0),
    },
}

PRESETS: dict[str, dict[str, Any]] = {
    "subtle-glow": {"type": "glow", "params": {"strength": 0.35, "radius": 15.0}},
    "strong-bloom": {
        "type": "bloom", "params": {"strength": 0.8, "radius": 30.0, "threshold": 0.6}
    },
    "fade-in": {
        "type": "transform",
        "params": {"opacity": 0.0},
        "keyframes": {"opacity": [
            {"time_seconds": 0.0, "value": 0.0}, {"time_seconds": 1.0, "value": 1.0}
        ]},
    },
    "punch-in": {
        "type": "transform",
        "params": {"scale": 1.0},
        "keyframes": {"scale": [
            {"time_seconds": 0.0, "value": 1.0}, {"time_seconds": 2.0, "value": 1.5}
        ]},
    },
}


def effect_types() -> dict[str, Any]:
    return {
        type_name: {
            param: {"default": spec[0], "min": spec[1], "max": spec[2]}
            for param, spec in params.items()
        }
        for type_name, params in EFFECT_REGISTRY.items()
    }


def validate_effect(effect_type: str, params: dict[str, float],
                    keyframes: dict[str, list[EffectKeyframe]] | None = None) -> dict[str, float]:
    """Validate type/params/keyframes; return params with defaults filled."""
    if effect_type not in EFFECT_REGISTRY:
        raise ValidationError(
            f"unknown effect type: {effect_type}",
            details={"known_types": sorted(EFFECT_REGISTRY)},
        )
    spec = EFFECT_REGISTRY[effect_type]
    validated: dict[str, float] = {}
    for name, value in (params or {}).items():
        if name not in spec:
            raise ValidationError(
                f"unknown parameter {name!r} for effect {effect_type}",
                details={"known_params": sorted(spec)},
            )
        default, lo, hi = spec[name]
        numeric = float(value)
        if numeric < lo or numeric > hi:
            raise ValidationError(
                f"parameter {name}={numeric} out of range [{lo}, {hi}] for {effect_type}",
                details={"param": name, "min": lo, "max": hi},
            )
        validated[name] = numeric
    for name, spec_tuple in spec.items():
        _default = spec_tuple[0]
        validated.setdefault(name, _default)
    for prop, frames in (keyframes or {}).items():
        if prop not in spec:
            raise ValidationError(
                f"cannot keyframe unknown parameter {prop!r} for {effect_type}",
                details={"known_params": sorted(spec)},
            )
        _pdefault, lo, hi = spec[prop]
        times = [f.time_seconds for f in frames]
        if times != sorted(times):
            raise ValidationError(f"keyframes for {prop} must be sorted by time")
        for frame in frames:
            if frame.value < lo or frame.value > hi:
                raise ValidationError(
                    f"keyframe value {frame.value} for {prop} out of range [{lo}, {hi}]",
                    details={"param": prop, "min": lo, "max": hi},
                )
    return validated


def evaluate_keyframes(frames: list[EffectKeyframe], t: float, base: float) -> float:
    """Value at time t: hold/linear interpolation, clamped to keyframe range."""
    if not frames:
        return base
    ordered = sorted(frames, key=lambda f: f.time_seconds)
    if t <= ordered[0].time_seconds:
        return ordered[0].value
    if t >= ordered[-1].time_seconds:
        return ordered[-1].value
    for prev, cur in zip(ordered, ordered[1:], strict=False):
        if prev.time_seconds <= t <= cur.time_seconds:
            if cur.interpolation == "hold" or cur.time_seconds == prev.time_seconds:
                return prev.value
            fraction = (t - prev.time_seconds) / (cur.time_seconds - prev.time_seconds)
            return prev.value + (cur.value - prev.value) * fraction
    return ordered[-1].value


def value_at(effect: ClipEffect, param: str, clip_local_t: float) -> float:
    spec = EFFECT_REGISTRY[effect.type][param]
    base = float(effect.params.get(param, spec[0]))
    frames = effect.keyframes.get(param) or []
    return evaluate_keyframes(frames, clip_local_t, base)


def evaluated_params(effect: ClipEffect, clip_local_t: float) -> dict[str, float]:
    return {param: value_at(effect, param, clip_local_t) for param in EFFECT_REGISTRY[effect.type]}


# ---- FFmpeg filter mapping ---------------------------------------------------
# Filters operate on a video stream label and return a new label expression.
# transform is handled at compositing time (scale/position/opacity), not here.


def video_filter_chain(effects: list[ClipEffect], clip_local_t: float, label_in: str,
                       width: int, height: int) -> tuple[str, str]:
    """Build filter steps for non-transform effects; returns (chain, out_label).

    ``label_in`` like ``[1:v]``; chain may be empty when nothing applies.
    """
    steps: list[str] = []
    current = label_in
    counter = 0

    def out_label() -> str:
        nonlocal counter
        counter += 1
        return f"[fx{counter}]"

    for effect in effects:
        if not effect.enabled or effect.type == "transform":
            continue
        params = evaluated_params(effect, clip_local_t)
        target = out_label()
        if effect.type == "color":
            steps.append(
                f"{current}eq=brightness={params['brightness']:.4f}:contrast={params['contrast']:.4f}"
                f":saturation={params['saturation']:.4f}{target}"
            )
        elif effect.type == "blur":
            if params["radius"] > 0.05:
                steps.append(f"{current}gblur=sigma={params['radius']:.3f}{target}")
            else:
                continue
        elif effect.type in {"glow", "bloom"}:
            sigma = max(params["radius"], 0.1)
            strength = params["strength"]
            # Glow/bloom: screen-blend a blurred copy over the source. This
            # is implemented with overlay (a blurred RGBA copy at partial
            # alpha) instead of the blend filter, whose framesync produces
            # runaway durations on older ffmpeg builds (observed: a 2s clip
            # exporting as 2048s on ffmpeg 6.x).
            if effect.type == "bloom":
                # Threshold highlights before blurring: lift blacks to cutoff.
                steps.append(
                    f"{current}split[bloom_src{counter}][bloom_hi{counter}];"
                    f"[bloom_hi{counter}]eq=brightness={params['threshold'] - 1.0:.4f}"
                    f":contrast=2,gblur=sigma={sigma:.3f},format=rgba,"
                    f"colorchannelmixer=aa={strength:.4f}[bloom_fg{counter}];"
                    f"[bloom_src{counter}][bloom_fg{counter}]overlay=0:0{target}"
                )
            else:
                steps.append(
                    f"{current}split[glow_src{counter}][glow_hi{counter}];"
                    f"[glow_hi{counter}]gblur=sigma={sigma:.3f},format=rgba,"
                    f"colorchannelmixer=aa={strength:.4f}[glow_fg{counter}];"
                    f"[glow_src{counter}][glow_fg{counter}]overlay=0:0{target}"
                )
        current = target
    return ";".join(steps), current


def transform_params(effects: list[ClipEffect], clip_local_t: float) -> dict[str, float]:
    """Combined compositing transform (later transform effects win per-param
    only where they define keyframes or non-default values — in practice the
    last enabled transform effect provides the values)."""
    result = dict(opacity=1.0, scale=1.0, x=0.0, y=0.0)
    found = False
    for effect in effects:
        if effect.enabled and effect.type == "transform":
            result.update(evaluated_params(effect, clip_local_t))
            found = True
    return result if found else result
