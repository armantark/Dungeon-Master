"""Integration tests for the FastAPI surface.

These tests don't go to the network: a `FakeNarrative` and
`FakeCampaignGenerator` replace LiteLLM, so we exercise the routing,
serialization, and state-mutation contracts without spending tokens.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from dungeon_master.application.game_service import GameService
from dungeon_master.domain.models import (
    AttackStance,
    CairnAbility,
    CairnRestKind,
    CampaignEndReason,
    CampaignStatus,
    EncounterState,
    EnemyCombatant,
    GameState,
)
from dungeon_master.llm.planning import (
    TurnRouter,
)
from dungeon_master.mechanics.oracle import OracleEngine
from dungeon_master.persistence.state_store import StateStore
from dungeon_master.transport.http.asgi import (
    create_app,
)
from tests.api.mechanics_fakes import (
    FatalPlayableCairnEngine,
)
from tests.api.narrative_fakes import (
    FakeCampaignGenerator,
    FakeCharacterGenerator,
    FakeNarrative,
)
from tests.api.support import (
    _client,
    _setup_client,
    _thoughtful_setup_client,
    scripted_classifier,
)
from tests.factories import sample_state


def test_character_templates_endpoint(tmp_path: Path) -> None:
    with _setup_client(tmp_path) as client:
        response = client.get("/api/character/templates")
    assert response.status_code == 200
    assert len(response.json()["templates"]) == 1


def test_finalize_character_then_start_campaign(tmp_path: Path) -> None:
    character = sample_state().character.model_copy(deep=True)
    character.name = "Rook"

    with _setup_client(tmp_path) as client:
        finalized = client.post(
            "/api/character/finalize",
            json={"character": character.model_dump()},
        )
        started = client.post("/api/campaign/start")

    assert finalized.status_code == 200
    assert finalized.json()["campaign_status"] == "ready_to_start"
    assert started.status_code == 200
    assert started.json()["campaign_status"] == "active"
    assert started.json()["character"]["name"] == "Rook"


def test_character_quiz_endpoint_returns_questions(tmp_path: Path) -> None:
    with _setup_client(tmp_path) as client:
        response = client.post(
            "/api/character/quiz",
            json={"concept": "Armenian Apostolic paladin who refuses magic."},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["quiz"]["concept"] == "Armenian Apostolic paladin who refuses magic."
    assert len(payload["quiz"]["questions"]) >= 3
    assert payload["thinking"] == ""


def test_character_quizzed_draft_threads_inputs(tmp_path: Path) -> None:
    with _setup_client(tmp_path) as client:
        quiz = client.post(
            "/api/character/quiz",
            json={"concept": "A scarred deserter."},
        ).json()["quiz"]
        questions = quiz["questions"]
        answers = [
            {
                "question_id": questions[0]["id"],
                "prompt": questions[0]["prompt"],
                "value": "Wounded but standing.",
                "is_other": False,
            },
            {
                "question_id": questions[1]["id"],
                "prompt": questions[1]["prompt"],
                "value": "A name I cannot say.",
                "is_other": False,
            },
            {
                "question_id": questions[2]["id"],
                "prompt": questions[2]["prompt"],
                "value": "An old company that won't forget.",
                "is_other": True,
            },
        ]
        response = client.post(
            "/api/character/draft/quizzed",
            json={
                "concept": "A scarred deserter.",
                "answers": answers,
                "final_note": "Carries a brand they cannot read.",
            },
        )
    assert response.status_code == 200
    draft = response.json()["draft"]
    assert draft["epithet"] == "A scarred deserter."
    assert "Wounded but standing." in draft["backstory"]
    assert "A name I cannot say." in draft["backstory"]
    assert "An old company that won't forget." in draft["backstory"]
    assert draft["condition"] == "Carries a brand they cannot read."


def test_character_quiz_stream_emits_final_payload(tmp_path: Path) -> None:
    with _setup_client(tmp_path) as client:
        response = client.post(
            "/api/character/quiz/stream",
            json={"concept": "A scarred deserter."},
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    parsed = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    types = [event["type"] for event in parsed]
    assert types[0] == "meta"
    assert parsed[0]["route"] == "character_quiz"
    assert "content_delta" in types
    assert types[-1] == "final_payload"
    final = parsed[-1]
    assert final["kind"] == "character_quiz"
    assert "quiz" in final["payload"]


def test_character_draft_stream_emits_final_payload(tmp_path: Path) -> None:
    with _setup_client(tmp_path) as client:
        response = client.post(
            "/api/character/draft/stream",
            json={"mode": "scratch", "prompt": "A hollow-eyed pilgrim."},
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    parsed = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    types = [event["type"] for event in parsed]
    assert types[0] == "meta"
    assert parsed[0]["route"] == "character_draft"
    assert "content_delta" in types
    assert types[-1] == "final_payload"
    final = parsed[-1]
    assert final["kind"] == "character_draft"
    assert "draft" in final["payload"]


def test_campaign_start_persists_thinking_on_init_event(tmp_path: Path) -> None:
    character = sample_state().character.model_copy(deep=True)
    with _thoughtful_setup_client(tmp_path) as client:
        client.post("/api/character/finalize", json={"character": character.model_dump()})
        response = client.post("/api/campaign/start")
    assert response.status_code == 200
    system_event = response.json()["action_log"][-1]
    assert system_event["title"] == "Campaign initialized"
    assert "Thought" in system_event["thinking"] or system_event["thinking"] == ""


def test_campaign_end_endpoint_marks_retirement_and_blocks_future_turns(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        ended = client.post(
            "/api/campaign/end",
            json={
                "reason": CampaignEndReason.RETIREMENT.value,
                "summary": "Vrtanes leaves the abbey road and does not return.",
            },
        )
        blocked = client.post("/api/turn", json={"text": "I keep walking into the hills."})

    assert ended.status_code == 200
    body = ended.json()
    assert body["campaign_status"] == CampaignStatus.ENDED.value
    assert body["campaign_end_reason"] == CampaignEndReason.RETIREMENT.value
    assert body["campaign_end_summary"] == "Vrtanes leaves the abbey road and does not return."
    assert body["action_log"][-1]["title"] == "Campaign ended"
    assert blocked.status_code == 409
    assert "retirement" in blocked.json()["detail"]


def test_cairn_save_endpoint(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/cairn/save",
            json={"ability": CairnAbility.STR.value, "reason": "Force the chapel door."},
        )
    assert response.status_code == 200
    outcome = response.json()["oracle_history"][-1]
    assert outcome["kind"] == "save"
    assert outcome["cairn"]["ability"] == "STR"


def test_cairn_attack_endpoint(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        state = client.get("/api/state").json()
        weapon_id = state["character"]["cairn"]["primary_weapon_item_id"]
        response = client.post(
            "/api/cairn/attack",
            json={
                "target_name": "Abbey ghoul",
                "target_armor": 1,
                "weapon_item_id": weapon_id,
                "stance": AttackStance.NORMAL.value,
            },
        )
    assert response.status_code == 200
    outcome = response.json()["oracle_history"][-1]
    assert outcome["kind"] == "attack"
    assert outcome["cairn"]["weapon_item_id"] == weapon_id


def test_cairn_harm_and_recover_endpoints(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        harmed = client.post(
            "/api/cairn/harm",
            json={
                "amount": 2,
                "source": "Falling masonry",
                "in_combat": True,
                "armor_applies": False,
            },
        )
        recovered = client.post(
            "/api/cairn/recover",
            json={"kind": CairnRestKind.BREATHER.value},
        )
    assert harmed.status_code == 200
    assert harmed.json()["oracle_history"][-1]["kind"] == "harm"
    assert recovered.status_code == 200
    assert recovered.json()["oracle_history"][-1]["kind"] == "recovery"


def test_cairn_harm_endpoint_can_end_campaign_on_death(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FatalPlayableCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    with TestClient(create_app(service=service)) as client:
        seeded = client.get("/api/state").json()
        seeded["character"]["cairn"]["hp"] = 1
        seeded["character"]["cairn"]["str_score"] = 1
        store.save(GameState.model_validate(seeded), create_checkpoint=False)

        response = client.post(
            "/api/cairn/harm",
            json={
                "amount": 5,
                "source": "Falling masonry",
                "in_combat": True,
                "armor_applies": False,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["campaign_status"] == CampaignStatus.ENDED.value
    assert body["campaign_end_reason"] == CampaignEndReason.DEATH.value
    assert "Final turn: Fatal harm from Falling masonry." in body["campaign_end_summary"]
    assert body["action_log"][-1]["title"] == "Campaign ended"


def test_cairn_retreat_endpoint(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    seeded = sample_state()
    seeded.encounter = EncounterState(
        active=True,
        round_number=2,
        combatants=[EnemyCombatant(name="Abbey ghoul", hp=4, max_hp=4)],
    )
    store.save(seeded, create_checkpoint=True)

    with _client(tmp_path) as client:
        response = client.post(
            "/api/cairn/retreat",
            json={"reason": "Break contact and reach the chapel arch."},
        )
    assert response.status_code == 200
    outcome = response.json()["oracle_history"][-1]
    assert outcome["kind"] == "retreat"
    assert outcome["cairn"]["retreat_outcome"] == "escaped"


def test_cairn_acquire_endpoint(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/cairn/acquire",
            json={"text": "I buy a lantern and a purse of old silver."},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["action_log"][0]["title"] == "Inventory acquired"
    assert body["oracle_history"][-1]["summary"] == "Acquired Pilgrim lantern, Purse of old silver."
    assert [item["name"] for item in body["character"]["inventory"]][-2:] == [
        "Pilgrim lantern",
        "Purse of old silver",
    ]


def test_cairn_equip_endpoint(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        state = client.get("/api/state").json()
        item_id = state["character"]["inventory"][0]["id"]
        response = client.post(
            "/api/cairn/equip",
            json={"item_id": item_id, "equipped": True},
        )
    assert response.status_code == 200
    assert response.json()["action_log"][-1]["title"] == "Equipment updated"


def test_regenerate_latest_message(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        first = client.post(
            "/api/oracle/yes-no",
            json={"question": "Does anything stir?", "likelihood": "Even odds"},
        ).json()
        narrative_event_id = first["action_log"][-1]["id"]
        repaired = client.post(f"/api/messages/{narrative_event_id}/regenerate")

    assert repaired.status_code == 200
    log_titles = [event["title"] for event in repaired.json()["action_log"]]
    assert "Narrative regenerated" in log_titles
