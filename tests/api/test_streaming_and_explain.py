"""Integration tests for the FastAPI surface.

These tests don't go to the network: a `FakeNarrative` and
`FakeCampaignGenerator` replace LiteLLM, so we exercise the routing,
serialization, and state-mutation contracts without spending tokens.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, cast

from dungeon_master.domain.models import (
    CairnCharacterState,
    CairnItemState,
    CairnItemTag,
    CairnMechanicsSource,
    GameState,
    InventoryItem,
    OracleKind,
    PartyMember,
)
from dungeon_master.persistence.state_store import StateStore
from dungeon_master.transport.http.asgi import (
    PlayerTurnRequest,
    reattach_request_stream,
    submit_turn_stream,
)
from tests.api.narrative_fakes import (
    BlockingThoughtfulNarrative,
    FakeExplainer,
)
from tests.api.support import (
    _broken_planner_client,
    _client,
    _collect_stream_events,
    _request_for_app,
    _thoughtful_client,
)


def test_submit_turn_stream_emits_ndjson_events(tmp_path: Path) -> None:
    """The streaming endpoint speaks the NDJSON contract the frontend expects.

    We assert the wire shape rather than parsing — a regression that
    drops `meta` or fakes the discriminator would still pass a parser
    test that's lenient about field names. Strict substring checks pin
    each event type and the order they fire (`meta` before any deltas,
    `final_state` last).
    """
    with _thoughtful_client(tmp_path) as client:
        response = client.post(
            "/api/turn/stream",
            json={"text": "I swing my cudgel at the abbey ghoul."},
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    lines = [line for line in response.text.splitlines() if line.strip()]
    parsed = [json.loads(line) for line in lines]
    types = [event["type"] for event in parsed]
    assert types[0] == "meta"
    assert "stage" in types
    assert "thinking_delta" in types
    assert "content_delta" in types
    assert types[-1] == "final_state"
    stages = [event for event in parsed if event["type"] == "stage"]
    stage_statuses = {(event["stage_id"], event["status"]) for event in stages}
    assert ("planning_turn", "active") in stage_statuses
    assert ("planning_turn", "done") in stage_statuses
    assert ("resolving_mechanics", "active") in stage_statuses
    assert ("resolving_mechanics", "done") in stage_statuses
    assert all(stage_id != "classifying_continuity" for stage_id, _ in stage_statuses)
    assert ("preparing_narration", "active") in stage_statuses
    assert ("preparing_narration", "done") in stage_statuses
    assert ("streaming_narration", "active") in stage_statuses
    assert ("streaming_narration", "done") in stage_statuses
    assert ("reconciling_continuity", "active") in stage_statuses
    assert ("reconciling_continuity", "done") in stage_statuses
    final = parsed[-1]
    assert final["state"]["action_log"][-1]["title"] == "Narrative response"
    assert final["thinking"] == "Thought about attack."


def test_submit_turn_stream_can_reattach_after_disconnect(tmp_path: Path) -> None:
    narrative = BlockingThoughtfulNarrative()
    with _client(tmp_path, narrative=narrative) as client:
        app = cast("Any", client.app)
        response = submit_turn_stream(
            request=_request_for_app(app, "/api/turn/stream"),
            svc=app.state.service,
            stream_runtime=app.state.stream_runtime,
            payload=PlayerTurnRequest(text="I swing my cudgel at the abbey ghoul."),
        )
        initial_events = asyncio.run(
            _collect_stream_events(
                response.body_iterator,
                until_type="thinking_delta",
            ),
        )
        meta = initial_events[0]
        thinking = next(event for event in initial_events if event["type"] == "thinking_delta")
        request_id = cast("str", meta["request_id"])
        assert meta["type"] == "meta"
        assert thinking == {"type": "thinking_delta", "text": "Thought about attack."}
        assert narrative.started.wait(timeout=1.0)
        persisted_before = client.get("/api/state").json()
        assert all(
            event["title"] != "Narrative response" for event in persisted_before["action_log"]
        )
        resumed = reattach_request_stream(
            request=_request_for_app(app, f"/api/requests/{request_id}/stream"),
            request_id=request_id,
            stream_runtime=app.state.stream_runtime,
        )
        resumed_events = asyncio.run(
            _collect_stream_events(
                resumed.body_iterator,
                release=narrative.release,
                release_on_type="thinking_delta",
            ),
        )

    assert resumed_events[0]["request_id"] == request_id
    assert thinking in resumed_events
    assert resumed_events[-1]["type"] == "final_state"
    assert resumed_events[-1]["state"]["action_log"][-1]["title"] == "Narrative response"


def test_submit_turn_stream_degrades_to_safe_final_state_on_planning_failure(
    tmp_path: Path,
) -> None:
    with _broken_planner_client(tmp_path) as client:
        response = client.post(
            "/api/turn/stream",
            json={"text": "I listen at the abbey door."},
        )

    assert response.status_code == 200
    parsed = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert parsed[0]["type"] == "meta"
    assert parsed[-1]["type"] == "final_state"
    assert len(parsed[-1]["state"]["oracle_history"]) == 1
    assert parsed[-1]["state"]["oracle_history"][-1]["kind"] == OracleKind.PLAYER_ACTION.value
    assert parsed[-1]["state"]["action_log"][-1]["title"] == "Narrative response"


def test_explain_endpoint_returns_non_canonical_answer(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        client.post(
            "/api/oracle/yes-no",
            json={"question": "Does anything stir?", "likelihood": "Even odds"},
        )
        response = client.post(
            "/api/explain",
            json={"question": "Why did that outcome happen?"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"].startswith("OOC: Why did that outcome happen?")
    assert "latest" in payload["answer"]
    assert payload["thinking"] == ""


def test_explain_endpoint_receives_party_member_weapon_state(tmp_path: Path) -> None:
    explainer = FakeExplainer()
    with _client(tmp_path, explainer=explainer) as client:
        state_response = client.get("/api/state")
        state_payload = state_response.json()
        state = GameState.model_validate(state_payload)
        weapon = InventoryItem(
            name="Rusted wood-axe",
            details="Already surfaced as this companion's weapon.",
            cairn=CairnItemState(
                source=CairnMechanicsSource.EXPLICIT,
                tags=[CairnItemTag.WEAPON],
                weapon_damage_die=6,
                equipped=True,
            ),
        )
        companion_sheet = state.character.model_copy(
            update={
                "name": "Test Companion",
                "inventory": [weapon],
                "cairn": CairnCharacterState(
                    source=CairnMechanicsSource.EXPLICIT,
                    hp=3,
                    max_hp=3,
                    primary_weapon_item_id=weapon.id,
                ),
            },
            deep=True,
        )
        state.party_members.append(PartyMember(sheet=companion_sheet))
        StateStore(tmp_path / "game_state.json").save(state, create_checkpoint=False)

        response = client.post(
            "/api/explain",
            json={"question": "What weapon does my companion use by default?"},
        )

    assert response.status_code == 200
    assert explainer.state is not None
    assert explainer.state.party_members[0].sheet.inventory[0].name == "Rusted wood-axe"
    assert (
        explainer.state.party_members[0].sheet.cairn.primary_weapon_item_id
        == explainer.state.party_members[0].sheet.inventory[0].id
    )


def test_explain_stream_emits_final_payload(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/explain/stream",
            json={"question": "What does ambush mean here?"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    parsed = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    types = [event["type"] for event in parsed]
    assert types[0] == "meta"
    assert parsed[0]["route"] == "explanation"
    assert "thinking_delta" in types
    assert "content_delta" in types
    assert types[-1] == "final_payload"
    final = parsed[-1]
    assert final["kind"] == "explanation"
    assert final["payload"]["answer"].startswith("OOC: What does ambush mean here?")
    assert final["thinking"] == "Explainer considered the current state."


def test_explain_endpoint_does_not_mutate_state_or_memory(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    with _client(tmp_path) as client:
        client.post(
            "/api/oracle/yes-no",
            json={"question": "Does anything stir?", "likelihood": "Even odds"},
        )
        before_state = store.state_path.read_text(encoding="utf-8")
        before_memory = store.memory_path.read_text(encoding="utf-8")

        response = client.post(
            "/api/explain",
            json={"question": "Why did I get that receipt?"},
        )

        after_state = store.state_path.read_text(encoding="utf-8")
        after_memory = store.memory_path.read_text(encoding="utf-8")

    assert response.status_code == 200
    assert before_state == after_state
    assert before_memory == after_memory


def test_streamed_turn_persists_thinking_on_narrative_event(tmp_path: Path) -> None:
    with _thoughtful_client(tmp_path) as client:
        response = client.post(
            "/api/turn",
            json={"text": "I swing my cudgel at the abbey ghoul."},
        )
    assert response.status_code == 200
    narrative_event = response.json()["action_log"][-1]
    assert narrative_event["title"] == "Narrative response"
    assert narrative_event["thinking"] == "Thought about attack."


def test_reset_replaces_state(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        original = client.get("/api/state").json()
        reset_state = client.post("/api/state/reset").json()
    assert original["id"] != reset_state["id"]
