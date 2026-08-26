"""Stable public facade for the Dungeon Master HTTP application."""

from dungeon_master.transport.http.app import create_app, router
from dungeon_master.transport.http.routes.gameplay import submit_turn_stream
from dungeon_master.transport.http.routes.system import reattach_request_stream
from dungeon_master.transport.http.schemas import PlayerTurnRequest

__all__ = [
    "PlayerTurnRequest",
    "app",
    "create_app",
    "reattach_request_stream",
    "router",
    "submit_turn_stream",
]

app = create_app()
