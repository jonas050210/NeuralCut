"""Centralized application configuration.

Configuration sources (in priority order, high to low):
  1. CLI arguments (handled by ``neuralcut.main``)
  2. Environment variables with the ``NEURALCUT_`` prefix
     (nested keys use ``__``, e.g. ``NEURALCUT_LOGGING__LEVEL=DEBUG``)
  3. JSON config file (``NEURALCUT_CONFIG_FILE``, default
     ``<data_dir>/config.json``)
  4. Hard-coded defaults below

All values are validated by Pydantic. Invalid config fails fast at startup
with a clear error instead of behaving subtly wrong later.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, JsonConfigSettingsSource, PydanticBaseSettingsSource


class LoggingConfig(BaseModel):
    level: str = Field(default="INFO", description="Log level: DEBUG, INFO, WARNING, ERROR")
    json_logs: bool = Field(default=True, description="Emit JSON-structured log records")
    file: str | None = Field(
        default=None,
        description="Log file path. None means <data_dir>/logs/neuralcut.log",
    )
    max_bytes: int = Field(default=5_000_000, gt=0)
    backup_count: int = Field(default=3, ge=0)
    stdout: bool = Field(default=True, description="Also write logs to stdout")

    @field_validator("level")
    @classmethod
    def _validate_level(cls, value: str) -> str:
        import logging

        value_up = value.upper()
        if value_up not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"invalid log level: {value}")
        logging.getLevelName(value_up)  # raises for unknown levels
        return value_up


class JobsConfig(BaseModel):
    max_workers: int = Field(default=2, ge=1, le=16)
    result_ttl_seconds: int = Field(default=86400, ge=60)
    max_jobs: int = Field(default=100, ge=1, le=10000)


class MediaConfig(BaseModel):
    ffmpeg_path: str | None = Field(
        default=None,
        description="Path to ffmpeg binary. None means resolve from PATH. "
        "Media processing is an extension point — ffmpeg is optional.",
    )
    probe_path: str | None = Field(
        default=None,
        description="Path to ffprobe binary. None means resolve from PATH.",
    )


class ModelsConfig(BaseModel):
    enabled: bool = Field(
        default=False,
        description="AI models are optional. When disabled, no model files are "
        "downloaded and no GPU is initialized at startup.",
    )
    orchestrator_path: str | None = Field(
        default=None, description="Path to the orchestrator LLM GGUF (optional)."
    )
    max_vram_gb: float | None = Field(
        default=None,
        gt=0,
        description="Optional VRAM budget in GB for model scheduling (extension point).",
    )


class UISettings(BaseModel):
    theme: str = Field(default="system", pattern=r"^(system|light|dark)$")
    default_project_dir: str | None = Field(
        default=None, description="Default directory for new projects."
    )


class NeuralCutSettings(BaseSettings):
    """Application settings with validation and multiple sources."""

    app_name: str = "NeuralCut"
    version: str = "0.2.0"
    debug: bool = False
    host: str = Field(default="127.0.0.1", description="Backend bind host")
    port: int = Field(default=8765, ge=1024, le=65535, description="Backend bind port")
    data_dir: str = Field(
        default="",
        description="Application data directory. Empty means the platform default "
        "(%APPDATA%/NeuralCut on Windows, ~/.local/share/neuralcut elsewhere).",
    )
    recent_projects: list[str] = Field(default_factory=list, max_length=50)

    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    jobs: JobsConfig = Field(default_factory=JobsConfig)
    media: MediaConfig = Field(default_factory=MediaConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    ui: UISettings = Field(default_factory=UISettings)

    model_config = {
        "env_prefix": "NEURALCUT_",
        "env_nested_delimiter": "__",
    }

    @field_validator("recent_projects", mode="before")
    @classmethod
    def _split_recent_projects(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        return list(value)


def default_config_file(data_dir: str | Path) -> Path:
    return Path(data_dir) / "config.json"


def _default_data_dir() -> str:
    """Platform default data directory."""
    import os

    home = Path.home()
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        return str((Path(appdata) / "NeuralCut") if appdata else home / "AppData/Roaming/NeuralCut")
    if sys.platform == "darwin":
        return str(home / "Library/Application Support/NeuralCut")
    return str(home / ".local/share/neuralcut")


@dataclass
class AppContext:
    """Resolved runtime context: settings plus the directories they point at."""

    settings: NeuralCutSettings
    data_dir: Path
    config_path: Path


def load_settings(
    config_file: str | Path | None = None,
    data_dir: str | Path | None = None,
) -> AppContext:
    """Load settings, resolving the data directory and config file first.

    Priority: CLI args > env vars (NEURALCUT_*) > JSON config file > defaults.
    The config file is created on first save if it does not exist yet.
    """
    resolved_data_dir = Path(
        data_dir or os.environ.get("NEURALCUT_DATA_DIR") or _default_data_dir()
    )
    resolved_data_dir.mkdir(parents=True, exist_ok=True)

    config_path = Path(
        config_file
        or os.environ.get("NEURALCUT_CONFIG_FILE")
        or default_config_file(resolved_data_dir)
    )

    class FileSettings(NeuralCutSettings):
        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            sources: list[PydanticBaseSettingsSource] = [init_settings, env_settings]
            if config_path.exists():
                sources.append(JsonConfigSettingsSource(settings_cls, json_file=str(config_path)))
            return tuple(sources)

    settings = FileSettings()
    return AppContext(settings=settings, data_dir=resolved_data_dir, config_path=config_path)


def save_settings(context: AppContext) -> Path:
    """Persist settings to the JSON config file (atomic write)."""
    import json

    config_path = context.config_path
    config_path.parent.mkdir(parents=True, exist_ok=True)
    data = context.settings.model_dump(exclude_unset=False)
    tmp = config_path.with_name(f"{config_path.name}.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(config_path)
    return config_path
