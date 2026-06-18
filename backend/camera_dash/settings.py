"""Runtime settings loaded from YAML config + env overrides.

Per-deploy YAML profiles (mac/rpi/dgx) set device + model defaults so the same
pipeline JSON ships everywhere. Pipeline nodes can reference profile values via
``${profile.default_device}`` / ``${env.FOO}`` substitution at load time.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Profile(BaseModel):
    name: str = "default"
    default_device: str = "cpu"  # cpu | mps | cuda | coral | hailo
    default_detector_model: str = "yolov8n.pt"
    target_fps: int = 15
    max_inflight_frames: int = 2  # latest-wins backpressure depth


class StorageSettings(BaseModel):
    dsn: str = "sqlite+aiosqlite:///./data/camera_dash.db"
    clips_dir: Path = Path("./data/clips")


class StreamingSettings(BaseModel):
    mediamtx_host: str = "127.0.0.1"
    mediamtx_rtsp_port: int = 8554
    mediamtx_webrtc_port: int = 8889
    mediamtx_api_port: int = 9997


class ServerSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])


class Settings(BaseSettings):
    """Top-level settings. Loaded from a YAML file + env vars (prefix CAMERA_DASH_)."""

    model_config = SettingsConfigDict(env_prefix="CAMERA_DASH_", env_nested_delimiter="__")

    profile: Profile = Field(default_factory=Profile)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    streaming: StreamingSettings = Field(default_factory=StreamingSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    config_path: Path | None = None

    @classmethod
    def from_yaml(cls, path: str | Path) -> Settings:
        with open(path) as fh:
            raw = yaml.safe_load(fh) or {}
        s = cls(**raw)
        s.config_path = Path(path).resolve()
        # Resolve any relative storage paths relative to the project root
        # (= config file's parent's parent, since configs/ lives one level down).
        # Without this, paths are CWD-dependent and the DB silently moves around.
        project_root = s.config_path.parent.parent
        s.storage.dsn = _resolve_sqlite_dsn(s.storage.dsn, project_root)
        if not s.storage.clips_dir.is_absolute():
            s.storage.clips_dir = (project_root / s.storage.clips_dir).resolve()
        return s


def _resolve_sqlite_dsn(dsn: str, base: Path) -> str:
    """Rewrite ``sqlite+aiosqlite:///./relative.db`` to use an absolute path."""
    prefix = "sqlite+aiosqlite:///"
    if not dsn.startswith(prefix):
        return dsn
    raw = dsn[len(prefix):]
    if raw.startswith(":memory:") or raw.startswith("/"):
        return dsn
    return prefix + str((base / raw).resolve())


_SUBST = re.compile(r"\$\{(env|profile)\.([A-Za-z0-9_]+)\}")


def substitute(value: Any, settings: Settings) -> Any:
    """Recursively replace ${env.X} and ${profile.X} in node config dicts."""
    if isinstance(value, str):
        def _sub(m: re.Match[str]) -> str:
            scope, key = m.group(1), m.group(2)
            if scope == "env":
                return os.environ.get(key, m.group(0))
            return str(getattr(settings.profile, key, m.group(0)))
        return _SUBST.sub(_sub, value)
    if isinstance(value, dict):
        return {k: substitute(v, settings) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, settings) for v in value]
    return value
