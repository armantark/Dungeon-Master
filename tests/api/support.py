"""Integration tests for the FastAPI surface.

These tests don't go to the network: a `FakeNarrative` and
`FakeCampaignGenerator` replace LiteLLM, so we exercise the routing,
serialization, and state-mutation contracts without spending tokens.
"""

from __future__ import annotations

import json
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, Any, cast

from fastapi.testclient import TestClient
from starlette.requests import Request

from dungeon_master.application.continuity import ThreadUpdater as ThreadUpdaterPort
from dungeon_master.application.game_service import GameService, NPCUpdaterPort
from dungeon_master.domain.models import (
    AttackStance,
    CairnAbility,
    CairnRestKind,
    Likelihood,
)
from dungeon_master.llm.narration import (
    NarrativeConfig,
)
from dungeon_master.llm.planning import (
    PlannedTurnOp,
    PlannedTurnOpKind,
    TurnPlan,
    TurnRoute,
    TurnRouter,
)
from dungeon_master.mechanics.oracle import OracleEngine
from dungeon_master.persistence.state_store import StateStore
from dungeon_master.transport.http.asgi import (
    create_app,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


from tests.api.mechanics_fakes import (
    FakePlayableCairnEngine,
    SetupCharacterGenerator,
)
from tests.api.narrative_fakes import (
    BlockingThoughtfulNarrative,
    BrokenPlannerCompletion,
    FakeCampaignGenerator,
    FakeCharacterGenerator,
    FakeExplainer,
    FakeNarrative,
    ThoughtfulNarrative,
)


def scripted_classifier(text: str, likelihood: Likelihood | None) -> TurnPlan:  # noqa: PLR0911
    if text == "Is the abbey gate watched?":
        return TurnPlan(
            route=TurnRoute.YES_NO,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.YES_NO,
                    text=text,
                    likelihood=likelihood or Likelihood.UNLIKELY,
                ),
            ),
        )
    if text == "I balance across the abbey beam.":
        return TurnPlan(
            route=TurnRoute.SAVE,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.SAVE,
                    text=text,
                    ability=CairnAbility.DEX,
                ),
            ),
        )
    if text == "I swing my cudgel at the abbey ghoul.":
        return TurnPlan(
            route=TurnRoute.ATTACK,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.ATTACK,
                    text=text,
                    target_name="Abbey ghoul",
                    stance=AttackStance.NORMAL,
                ),
            ),
        )
    if text == "I catch my breath and drink water.":
        return TurnPlan(
            route=TurnRoute.RECOVERY,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.RECOVERY,
                    text=text,
                    rest_kind=CairnRestKind.BREATHER,
                ),
            ),
        )
    if text == "I draw the test knife.":
        return TurnPlan(
            route=TurnRoute.EQUIP,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.EQUIP,
                    text=text,
                    item_name="Test knife",
                    equipped=True,
                ),
            ),
        )
    if text == "I fall back through the chapel arch.":
        return TurnPlan(
            route=TurnRoute.RETREAT,
            text=text,
            ops=(PlannedTurnOp(kind=PlannedTurnOpKind.RETREAT, text=text),),
        )
    return TurnPlan(
        route=TurnRoute.PLAYER_ACTION,
        text=text,
        ops=(PlannedTurnOp(kind=PlannedTurnOpKind.NARRATE, text=text),),
    )


def _client(  # noqa: PLR0913
    tmp_path: Path,
    *,
    narrative: FakeNarrative | ThoughtfulNarrative | BlockingThoughtfulNarrative | None = None,
    turn_router: TurnRouter | None = None,
    thread_updater: ThreadUpdaterPort | None = None,
    npc_updater: NPCUpdaterPort | None = None,
    explainer: FakeExplainer | None = None,
) -> TestClient:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=narrative or FakeNarrative(),
        explainer=explainer or FakeExplainer(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakePlayableCairnEngine(),
        turn_router=turn_router or TurnRouter(classifier=scripted_classifier),
        thread_updater=thread_updater,
        npc_updater=npc_updater,
    )
    return TestClient(create_app(service=service))


def _request_for_app(app: object, path: str) -> Request:
    return Request(
        {
            "type": "http",
            "app": app,
            "method": "GET",
            "path": path,
            "headers": [],
            "query_string": b"",
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "scheme": "http",
            "http_version": "1.1",
        },
    )


async def _collect_stream_events(
    iterator: object,
    *,
    limit: int | None = None,
    release: Event | None = None,
    release_on_type: str | None = None,
    until_type: str | None = None,
) -> list[dict[str, Any]]:
    stream = cast("AsyncIterator[str]", iterator)
    events: list[dict[str, Any]] = []
    try:
        async for line in stream:
            if not line:
                continue
            events.append(cast("dict[str, Any]", json.loads(line)))
            latest_type = cast("str | None", events[-1].get("type"))
            if release is not None and (
                (release_on_type is not None and latest_type == release_on_type)
                or (release_on_type is None and len(events) == 2)
            ):
                release.set()
            if until_type is not None and latest_type == until_type:
                break
            if limit is not None and len(events) >= limit:
                break
    finally:
        aclose = getattr(stream, "aclose", None)
        if callable(aclose):
            await aclose()
    return events


def _setup_client(tmp_path: Path) -> TestClient:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        explainer=FakeExplainer(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=SetupCharacterGenerator(),
        cairn_engine=FakePlayableCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )
    return TestClient(create_app(service=service))


def _thoughtful_client(tmp_path: Path) -> TestClient:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=ThoughtfulNarrative(),
        explainer=FakeExplainer(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakePlayableCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )
    return TestClient(create_app(service=service))


def _thoughtful_setup_client(tmp_path: Path) -> TestClient:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=ThoughtfulNarrative(),
        explainer=FakeExplainer(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=SetupCharacterGenerator(),
        cairn_engine=FakePlayableCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )
    return TestClient(create_app(service=service))


def _broken_planner_client(tmp_path: Path) -> TestClient:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        explainer=FakeExplainer(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakePlayableCairnEngine(),
        turn_router=TurnRouter(
            config=NarrativeConfig(
                model="test-model",
                api_key="test-key",
                base_url="https://example.com",
                exclude_reasoning=True,
            ),
            completion_function=BrokenPlannerCompletion(),
        ),
    )
    return TestClient(create_app(service=service))


def _library_service(tmp_path: Path) -> GameService:
    return GameService(
        store=StateStore(tmp_path / "seed_game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        explainer=FakeExplainer(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=SetupCharacterGenerator(),
        cairn_engine=FakePlayableCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )
