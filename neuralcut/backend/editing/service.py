"""Timeline editing service: deterministic clip operations with undo/redo.

All mutations go through this service. Each mutation validates the resulting
timeline with the Pydantic project model (unknown assets, source ranges,
same-track overlaps) *before* it is committed, and pushes a full-project
snapshot onto the undo stack. Snapshot-based history is deliberately simple:
project documents are small JSON, so restoring an exact prior state is more
reliable than hand-written inverse operations for every edit type.

History is in-memory and belongs to the currently open project; it resets
when a different project object becomes current. Editing does not auto-save
— the user saves explicitly, exactly like other project changes.
"""

from __future__ import annotations

import copy
import uuid
from pathlib import Path
from typing import Any

from neuralcut.backend.projects.model import Project, ProjectAsset, ProjectClip
from neuralcut.backend.projects.service import ProjectService
from neuralcut.errors import NotFoundError, ValidationError

MAX_HISTORY = 100
_EPS = 1e-9


class TimelineService:
    def __init__(self, project_service: ProjectService, media) -> None:  # noqa: ANN001
        self._projects = project_service
        self._media = media
        self._undo: list[dict[str, Any]] = []
        self._redo: list[dict[str, Any]] = []
        self._history_owner: Project | None = None

    # ---- history plumbing ---------------------------------------------------

    def _project(self) -> Project:
        project = self._projects.get()
        if self._history_owner is not project:
            self._undo.clear()
            self._redo.clear()
            self._history_owner = project
        return project

    def _snapshot(self, project: Project) -> dict[str, Any]:
        return copy.deepcopy(project.model_dump(mode="json"))

    def _push_history(self, project: Project) -> None:
        self._undo.append(self._snapshot(project))
        if len(self._undo) > MAX_HISTORY:
            self._undo = self._undo[-MAX_HISTORY:]
        self._redo.clear()

    def _commit(self, project: Project, mutated: Project) -> Project:
        """Validate ``mutated`` and swap it in, recording history."""
        from pydantic import ValidationError as PydanticValidationError

        try:
            validated = Project.model_validate(mutated.model_dump(mode="json"))
        except PydanticValidationError as exc:
            first = exc.errors()[0] if exc.errors() else {}
            raise ValidationError(
                f"invalid timeline edit: {first.get('msg', exc)}",
                details={"error": str(exc)},
            ) from exc
        self._push_history(project)
        validated.touch()
        self._projects.replace_current(validated)
        self._history_owner = validated
        return validated

    def history_state(self) -> dict[str, Any]:
        self._project()
        return {
            "can_undo": bool(self._undo),
            "can_redo": bool(self._redo),
            "undo_depth": len(self._undo),
            "redo_depth": len(self._redo),
        }

    def undo(self) -> Project:
        project = self._project()
        if not self._undo:
            raise ValidationError("nothing to undo")
        snapshot = self._undo.pop()
        self._redo.append(self._snapshot(project))
        restored = Project.model_validate(snapshot)
        restored.touch()
        self._projects.replace_current(restored)
        self._history_owner = restored
        return restored

    def redo(self) -> Project:
        project = self._project()
        if not self._redo:
            raise ValidationError("nothing to redo")
        snapshot = self._redo.pop()
        self._undo.append(self._snapshot(project))
        restored = Project.model_validate(snapshot)
        restored.touch()
        self._projects.replace_current(restored)
        self._history_owner = restored
        return restored

    # ---- lookups --------------------------------------------------------------

    @staticmethod
    def _asset(project: Project, asset_id: str) -> ProjectAsset:
        for asset in project.assets:
            if asset.id == asset_id:
                return asset
        raise NotFoundError(f"asset not found: {asset_id}", details={"asset_id": asset_id})

    @staticmethod
    def _clip(project: Project, clip_id: str) -> ProjectClip:
        for clip in project.clips:
            if clip.id == clip_id:
                return clip
        raise NotFoundError(f"clip not found: {clip_id}", details={"clip_id": clip_id})

    @staticmethod
    def _track_end(project: Project, track: int) -> float:
        return max(
            (c.timeline_end_seconds for c in project.clips if c.track == track), default=0.0
        )

    # ---- asset operations ------------------------------------------------------

    def import_media(self, path: str | Path) -> ProjectAsset:
        project = self._project()
        resolved = str(Path(path).expanduser())
        for asset in project.assets:
            if asset.path == resolved:
                return asset  # already imported; no state change, no history entry
        info = self._media.probe(resolved)
        kind = "video" if info.has_video else ("audio" if info.has_audio else "video")
        asset = ProjectAsset(
            id=uuid.uuid4().hex,
            name=Path(resolved).name,
            path=resolved,
            kind=kind,
            duration_seconds=info.duration_seconds,
            width=info.width,
            height=info.height,
            fps=info.fps,
            has_audio=info.has_audio,
            codec=info.codec,
        )
        mutated = Project.model_validate(self._snapshot(project))
        mutated.assets.append(asset)
        self._commit(project, mutated)
        return self._asset(self._projects.get(), asset.id)

    def remove_asset(self, asset_id: str) -> Project:
        project = self._project()
        self._asset(project, asset_id)
        if any(c.asset_id == asset_id for c in project.clips):
            raise ValidationError(
                "asset is used by timeline clips; remove those clips first",
                details={"asset_id": asset_id},
            )
        mutated = Project.model_validate(self._snapshot(project))
        mutated.assets = [a for a in mutated.assets if a.id != asset_id]
        return self._commit(project, mutated)

    # ---- clip operations ---------------------------------------------------------

    def add_clip(
        self,
        asset_id: str,
        *,
        track: int = 0,
        timeline_start_seconds: float | None = None,
        source_start_seconds: float = 0.0,
        source_end_seconds: float | None = None,
        name: str | None = None,
    ) -> ProjectClip:
        project = self._project()
        asset = self._asset(project, asset_id)
        if not Path(asset.path).is_file():
            raise ValidationError(
                f"source media is missing: {asset.path}",
                details={"asset_id": asset_id, "path": asset.path},
            )
        if source_end_seconds is None:
            if asset.duration_seconds is None:
                raise ValidationError(
                    "asset duration is unknown; provide source_end_seconds explicitly",
                    details={"asset_id": asset_id},
                )
            source_end_seconds = asset.duration_seconds
        exceeds_source = (
            asset.duration_seconds is not None
            and source_end_seconds > asset.duration_seconds + 1e-6
        )
        if exceeds_source:
            raise ValidationError(
                f"source end {source_end_seconds}s exceeds asset duration "
                f"{asset.duration_seconds}s",
                details={"asset_id": asset_id, "duration_seconds": asset.duration_seconds},
            )
        if timeline_start_seconds is None:
            timeline_start_seconds = self._track_end(project, track)
        clip = ProjectClip(
            id=uuid.uuid4().hex,
            asset_id=asset_id,
            name=name or asset.name,
            track=track,
            timeline_start_seconds=timeline_start_seconds,
            source_start_seconds=source_start_seconds,
            source_end_seconds=source_end_seconds,
        )
        mutated = Project.model_validate(self._snapshot(project))
        mutated.clips.append(clip)
        self._commit(project, mutated)  # model validator rejects overlaps/bad ranges
        return self._clip(self._projects.get(), clip.id)

    def move_clip(
        self,
        clip_id: str,
        *,
        timeline_start_seconds: float,
        track: int | None = None,
    ) -> ProjectClip:
        project = self._project()
        mutated = Project.model_validate(self._snapshot(project))
        clip = self._clip(mutated, clip_id)
        clip.timeline_start_seconds = timeline_start_seconds
        if track is not None:
            clip.track = track
        self._commit(project, mutated)
        return self._clip(self._projects.get(), clip_id)

    def trim_clip(
        self,
        clip_id: str,
        *,
        source_start_seconds: float | None = None,
        source_end_seconds: float | None = None,
        timeline_start_seconds: float | None = None,
        name: str | None = None,
    ) -> ProjectClip:
        project = self._project()
        asset_by_clip = self._clip(project, clip_id)
        asset = self._asset(project, asset_by_clip.asset_id)
        new_start = (
            source_start_seconds if source_start_seconds is not None
            else asset_by_clip.source_start_seconds
        )
        new_end = (
            source_end_seconds if source_end_seconds is not None
            else asset_by_clip.source_end_seconds
        )
        if asset.duration_seconds is not None and new_end > asset.duration_seconds + 1e-6:
            raise ValidationError(
                f"source end {new_end}s exceeds asset duration {asset.duration_seconds}s",
                details={"asset_id": asset.id, "duration_seconds": asset.duration_seconds},
            )
        mutated = Project.model_validate(self._snapshot(project))
        clip = self._clip(mutated, clip_id)
        clip.source_start_seconds = new_start
        clip.source_end_seconds = new_end
        if name is not None:
            clip.name = name
        if timeline_start_seconds is not None:
            clip.timeline_start_seconds = timeline_start_seconds
        self._commit(project, mutated)
        return self._clip(self._projects.get(), clip_id)

    def split_clip(self, clip_id: str, *, at_timeline_seconds: float) -> list[ProjectClip]:
        project = self._project()
        original = self._clip(project, clip_id)
        offset = at_timeline_seconds - original.timeline_start_seconds
        if offset <= _EPS or offset >= original.duration_seconds - _EPS:
            raise ValidationError(
                "split point must be inside the clip (not at its edges)",
                details={
                    "clip_id": clip_id,
                    "at_timeline_seconds": at_timeline_seconds,
                    "clip_start": original.timeline_start_seconds,
                    "clip_end": original.timeline_end_seconds,
                },
            )
        mutated = Project.model_validate(self._snapshot(project))
        clip = self._clip(mutated, clip_id)
        split_source = clip.source_start_seconds + offset
        second = ProjectClip(
            id=uuid.uuid4().hex,
            asset_id=clip.asset_id,
            name=f"{clip.name} (2)" if clip.name else "(2)",
            track=clip.track,
            timeline_start_seconds=at_timeline_seconds,
            source_start_seconds=split_source,
            source_end_seconds=clip.source_end_seconds,
        )
        clip.source_end_seconds = split_source
        mutated.clips.append(second)
        self._commit(project, mutated)
        current = self._projects.get()
        return [self._clip(current, clip_id), self._clip(current, second.id)]

    def remove_clip(self, clip_id: str) -> Project:
        project = self._project()
        self._clip(project, clip_id)
        mutated = Project.model_validate(self._snapshot(project))
        mutated.clips = [c for c in mutated.clips if c.id != clip_id]
        return self._commit(project, mutated)

    # ---- effect operations (Phase 4) -------------------------------------------

    def _effect(self, clip: ProjectClip, effect_id: str):  # noqa: ANN202

        for effect in clip.effects:
            if effect.id == effect_id:
                return effect
        raise NotFoundError(
            f"effect not found: {effect_id}",
            details={"clip_id": clip.id, "effect_id": effect_id},
        )

    def add_effect(self, clip_id: str, *, type: str, params: dict | None = None,
                   keyframes: dict | None = None, preset: str | None = None):
        from neuralcut.backend.effects.engine import PRESETS, validate_effect
        from neuralcut.backend.projects.model import ClipEffect, EffectKeyframe

        project = self._project()
        self._clip(project, clip_id)
        if preset is not None:
            if preset not in PRESETS:
                raise ValidationError(
                    f"unknown effect preset: {preset}",
                    details={"known_presets": sorted(PRESETS)},
                )
            preset_def = PRESETS[preset]
            type = preset_def["type"]  # noqa: A002 - API field name
            params = {**(preset_def.get("params") or {}), **(params or {})}
            keyframes = keyframes if keyframes is not None else preset_def.get("keyframes")
        parsed_keyframes = {}
        for prop, frames in (keyframes or {}).items():
            parsed_keyframes[prop] = [
                EffectKeyframe.model_validate(f) if isinstance(f, dict) else f for f in frames
            ]
        validated = validate_effect(type, params or {}, parsed_keyframes)
        effect = ClipEffect(
            id=uuid.uuid4().hex, type=type, params=validated, keyframes=parsed_keyframes
        )
        mutated = Project.model_validate(self._snapshot(project))
        self._clip(mutated, clip_id).effects.append(effect)
        self._commit(project, mutated)
        return self._effect(self._clip(self._projects.get(), clip_id), effect.id)

    def update_effect(self, clip_id: str, effect_id: str, *, params: dict | None = None,
                      enabled: bool | None = None):
        from neuralcut.backend.effects.engine import validate_effect

        project = self._project()
        current = self._effect(self._clip(project, clip_id), effect_id)
        merged = {**current.params, **(params or {})}
        validated = validate_effect(current.type, merged, current.keyframes)
        mutated = Project.model_validate(self._snapshot(project))
        effect = self._effect(self._clip(mutated, clip_id), effect_id)
        effect.params = validated
        if enabled is not None:
            effect.enabled = enabled
        self._commit(project, mutated)
        return self._effect(self._clip(self._projects.get(), clip_id), effect_id)

    def remove_effect(self, clip_id: str, effect_id: str) -> Project:
        project = self._project()
        self._effect(self._clip(project, clip_id), effect_id)
        mutated = Project.model_validate(self._snapshot(project))
        clip = self._clip(mutated, clip_id)
        clip.effects = [e for e in clip.effects if e.id != effect_id]
        return self._commit(project, mutated)

    def move_effect(self, clip_id: str, effect_id: str, *, direction: int):
        """Move an effect one step in the chain (direction -1 up / +1 down)."""
        if direction not in (-1, 1):
            raise ValidationError("direction must be -1 or +1")
        project = self._project()
        clip = self._clip(project, clip_id)
        self._effect(clip, effect_id)
        index = next(i for i, e in enumerate(clip.effects) if e.id == effect_id)
        target = index + direction
        if target < 0 or target >= len(clip.effects):
            raise ValidationError("effect is already at the edge of the chain")
        mutated = Project.model_validate(self._snapshot(project))
        mclip = self._clip(mutated, clip_id)
        mclip.effects[index], mclip.effects[target] = mclip.effects[target], mclip.effects[index]
        self._commit(project, mutated)
        return self._effect(self._clip(self._projects.get(), clip_id), effect_id)

    def set_keyframes(self, clip_id: str, effect_id: str, *, property: str,
                      keyframes: list):
        """Replace the keyframe list for one property (empty list clears it)."""
        from neuralcut.backend.effects.engine import validate_effect
        from neuralcut.backend.projects.model import EffectKeyframe

        project = self._project()
        current = self._effect(self._clip(project, clip_id), effect_id)
        parsed = [
            EffectKeyframe.model_validate(f) if isinstance(f, dict) else f for f in keyframes
        ]
        candidate = dict(current.keyframes)
        if parsed:
            candidate[property] = parsed
        else:
            candidate.pop(property, None)
        validate_effect(current.type, current.params, candidate)
        mutated = Project.model_validate(self._snapshot(project))
        effect = self._effect(self._clip(mutated, clip_id), effect_id)
        effect.keyframes = candidate
        self._commit(project, mutated)
        return self._effect(self._clip(self._projects.get(), clip_id), effect_id)

    # ---- views ---------------------------------------------------------------------

    def timeline(self) -> dict[str, Any]:
        project = self._project()
        assets = {a.id: a for a in project.assets}
        missing = [a.id for a in project.assets if not Path(a.path).is_file()]
        clips = []
        for clip in sorted(
            project.clips, key=lambda c: (c.track, c.timeline_start_seconds, c.id)
        ):
            entry = clip.model_dump(mode="json")
            entry["duration_seconds"] = clip.duration_seconds
            entry["timeline_end_seconds"] = clip.timeline_end_seconds
            entry["asset_name"] = assets[clip.asset_id].name if clip.asset_id in assets else None
            entry["asset_missing"] = clip.asset_id in missing
            clips.append(entry)
        return {
            "project_id": project.id,
            "duration_seconds": project.timeline_duration_seconds,
            "assets": [
                {**a.model_dump(mode="json"), "missing": a.id in missing}
                for a in project.assets
            ],
            "clips": clips,
            "export_settings": project.export_settings.model_dump(mode="json"),
            "history": self.history_state(),
        }
