"""Command-line entrypoint that serves the FastAPI app via uvicorn.

Kept tiny on purpose: configuration lives in `.env` (read by `settings.py`
and `narrative.py`). This module's only job is "run the server".
"""

from __future__ import annotations

import argparse

import uvicorn

from dungeon_master.observability import log_level_from_env


def main() -> None:
    parser = argparse.ArgumentParser(prog="dungeon-master")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host interface to bind. Defaults to localhost so we never "
        "accidentally expose a personal LLM key on the LAN.",
    )
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable autoreload for backend development.",
    )
    args = parser.parse_args()
    log_level = log_level_from_env().lower()

    uvicorn.run(
        "dungeon_master.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=log_level,
    )


if __name__ == "__main__":
    main()
