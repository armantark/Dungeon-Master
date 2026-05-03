from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


def state_path_from_env() -> Path:
    load_dotenv()
    return Path(os.getenv("DUNGEON_MASTER_STATE_PATH", "data/game_state.json"))
