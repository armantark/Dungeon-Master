from __future__ import annotations

from pathlib import Path

from dungeon_master.config import AppConfig


def state_path_from_env() -> Path:
    return AppConfig.from_env().state_path


def runtime_settings_path_from_env() -> Path:
    return AppConfig.from_env().runtime_settings_path


def credentials_path_from_env() -> Path:
    return AppConfig.from_env().credentials_path
