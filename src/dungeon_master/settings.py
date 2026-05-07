from __future__ import annotations

from pathlib import Path

from dungeon_master.config import AppConfig


def state_path_from_env() -> Path:
    return AppConfig.from_env().state_path
