"""Integration tests for the FastAPI surface.

These tests don't go to the network: a `FakeNarrative` and
`FakeCampaignGenerator` replace LiteLLM, so we exercise the routing,
serialization, and state-mutation contracts without spending tokens.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from dungeon_master.application.game_service import GameService
from dungeon_master.domain.models import (
    NPC,
    CairnCharacterState,
    CairnItemEffectKind,
    CairnItemPower,
    CairnItemPowerKind,
    CairnItemState,
    CairnItemTag,
    CairnMechanicsSource,
    CairnRestKind,
    CairnTimeAdvance,
    EncounterState,
    EnemyCombatant,
    GameState,
    GameThread,
    InventoryItem,
    Likelihood,
    NPCStatus,
    OracleKind,
    OracleOutcome,
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
from dungeon_master.mechanics.engine import CairnEngine
from dungeon_master.mechanics.oracle import OracleEngine
from dungeon_master.persistence.state_store import StateStore
from dungeon_master.transport.http.asgi import (
    create_app,
)
from tests.api.mechanics_fakes import (
    FakeNpcUpdater,
    FakeThreadUpdater,
)
from tests.api.narrative_fakes import (
    FakeCampaignGenerator,
    FakeCharacterGenerator,
    FakeExplainer,
    FakeNarrative,
)
from tests.api.support import (
    _broken_planner_client,
    _client,
    scripted_classifier,
)
from tests.factories import sample_state


def test_submit_action_records_player_then_narrative(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/action",
            json={"action": "I sift the ash for teeth."},
        )
    log = response.json()["action_log"]
    titles = [event["title"] for event in log]
    assert "Player action" in titles
    assert "Narrative response" in titles


def test_submit_turn_routes_natural_question(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/turn",
            json={"text": "Is the abbey gate watched? [unlikely]"},
        )
    assert response.status_code == 200
    payload = response.json()
    log = payload["action_log"]
    assert [event["title"] for event in log] == [
        "Player action",
        "Oracle answer",
        "Narrative response",
    ]
    outcome = payload["oracle_history"][0]
    assert outcome["kind"] == "yes_no"
    assert outcome["likelihood"] == "Unlikely"


def test_submit_turn_recon_question_does_not_advance_scene(tmp_path: Path) -> None:
    def recon_classifier(text: str, likelihood: Likelihood | None) -> TurnPlan:
        if text == "Are there enemies along the goat-path?":
            return TurnPlan(
                route=TurnRoute.PLAYER_ACTION,
                text=text,
                ops=(
                    PlannedTurnOp(
                        kind=PlannedTurnOpKind.SEARCH_SCENE,
                        text=text,
                    ),
                ),
            )
        return scripted_classifier(text, likelihood)

    with _client(tmp_path, turn_router=TurnRouter(classifier=recon_classifier)) as client:
        initial = client.get("/api/state").json()
        response = client.post(
            "/api/turn",
            json={"text": "Are there enemies along the goat-path?"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["scene_number"] == initial["scene_number"]
    assert payload["current_scene"] == initial["current_scene"]
    assert [event["title"] for event in payload["action_log"]] == [
        "Player action",
        "Narrative response",
    ]
    assert payload["oracle_history"][-1]["kind"] == OracleKind.PLAYER_ACTION.value
    assert "current vantage without advancing" in payload["action_log"][-1]["content"]


def test_submit_turn_degrades_to_safe_narration_when_planning_fails(tmp_path: Path) -> None:
    with _broken_planner_client(tmp_path) as client:
        response = client.post(
            "/api/turn",
            json={"text": "I listen at the abbey door."},
        )

    assert response.status_code == 200
    payload = response.json()
    assert [event["title"] for event in payload["action_log"]] == [
        "Player action",
        "Narrative response",
    ]
    assert len(payload["oracle_history"]) == 1
    assert payload["oracle_history"][-1]["kind"] == OracleKind.PLAYER_ACTION.value


def test_submit_turn_routes_obvious_cairn_save(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/turn",
            json={"text": "I balance across the abbey beam."},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["oracle_history"][0]["kind"] == "save"
    assert payload["oracle_history"][0]["cairn"]["ability"] == "DEX"


def test_submit_turn_routes_attack(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/turn",
            json={"text": "I swing my cudgel at the abbey ghoul."},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["oracle_history"][0]["kind"] == "attack"
    assert payload["oracle_history"][0]["cairn"]["target_name"] == "Abbey ghoul"


def test_submit_turn_routes_enemy_opener_into_tracked_encounter(tmp_path: Path) -> None:
    def ambush_classifier(text: str, likelihood: Likelihood | None) -> TurnPlan:
        del likelihood
        return TurnPlan(
            route=TurnRoute.HARM,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.ENEMY_OPENER,
                    text=text,
                    harm_source="Abbey ghoul",
                ),
            ),
        )

    with _client(tmp_path, turn_router=TurnRouter(classifier=ambush_classifier)) as client:
        response = client.post(
            "/api/turn",
            json={
                "text": (
                    "The abbey ghoul drops from the choir loft and claws me before I can "
                    "raise my cudgel."
                ),
            },
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["oracle_history"][0]["kind"] == "harm"
    assert payload["oracle_history"][0]["cairn"]["combat_started"] is True
    assert payload["oracle_history"][0]["cairn"]["combat_initiator"] == "enemy"
    assert payload["encounter"]["active"] is True
    assert payload["encounter"]["initiator"] == "enemy"


def test_submit_turn_routes_recovery(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/turn",
            json={"text": "I catch my breath and drink water."},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["oracle_history"][0]["kind"] == "recovery"
    assert payload["oracle_history"][0]["cairn"]["rest_kind"] == "breather"


def test_submit_turn_persists_survival_clock_fields(tmp_path: Path) -> None:
    def waiting_classifier(text: str, likelihood: Likelihood | None) -> TurnPlan:
        del likelihood
        return TurnPlan(
            route=TurnRoute.PLAYER_ACTION,
            text=text,
            time_advance=CairnTimeAdvance.WATCH,
            ops=(PlannedTurnOp(kind=PlannedTurnOpKind.NARRATE, text=text),),
        )

    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=CairnEngine(
            seed=1,
            config=NarrativeConfig(model="", api_key=None, base_url=None),
        ),
        turn_router=TurnRouter(classifier=waiting_classifier),
    )
    seeded = sample_state()
    seeded.character.cairn = CairnCharacterState(
        source=CairnMechanicsSource.EXPLICIT,
        str_score=12,
        dex_score=12,
        wil_score=10,
        max_str_score=12,
        max_dex_score=12,
        max_wil_score=10,
        hp=4,
        max_hp=4,
        primary_weapon_item_id=seeded.character.inventory[0].id,
    )
    seeded.character.inventory[0].cairn = CairnItemState(
        source=CairnMechanicsSource.EXPLICIT,
        tags=[CairnItemTag.WEAPON],
        weapon_damage_die=6,
        equipped=True,
    )
    service._store.save(seeded, create_checkpoint=False)  # noqa: SLF001

    with TestClient(create_app(service=service)) as client:
        response = client.post(
            "/api/turn",
            json={"text": "I keep watch by the thorn hedge until dusk."},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["character"]["cairn"]["survival"]["watch_index"] == 1
    assert payload["oracle_history"][-1]["cairn"]["time_advance"] == "watch"


def test_cairn_recover_full_rest_consumes_rations_before_healing(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=CairnEngine(
            seed=1,
            config=NarrativeConfig(model="", api_key=None, base_url=None),
        ),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )
    state = sample_state()
    state.character.cairn = CairnCharacterState(
        source=CairnMechanicsSource.EXPLICIT,
        str_score=12,
        dex_score=12,
        wil_score=10,
        max_str_score=12,
        max_dex_score=12,
        max_wil_score=10,
        hp=4,
        max_hp=4,
        primary_weapon_item_id=state.character.inventory[0].id,
    )
    state.character.inventory[0].cairn = CairnItemState(
        source=CairnMechanicsSource.EXPLICIT,
        tags=[CairnItemTag.WEAPON],
        weapon_damage_die=6,
        equipped=True,
    )
    state.character.cairn.hp = 1
    state.character.cairn.survival.watches_since_meal = 3
    state.character.cairn.survival.food_deprived = True
    state.character.cairn.deprived = True
    state.character.inventory.append(
        InventoryItem(
            name="Trail rations",
            details="Hard bread and salt fish.",
            cairn=CairnItemState(
                source=CairnMechanicsSource.EXPLICIT,
                tags=[CairnItemTag.SUPPLIES],
                slots=1,
                uses=None,
            ),
        ),
    )
    service._store.save(state, create_checkpoint=False)  # noqa: SLF001

    with TestClient(create_app(service=service)) as client:
        response = client.post(
            "/api/cairn/recover",
            json={"kind": CairnRestKind.FULL_REST.value},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["character"]["cairn"]["hp"] == payload["character"]["cairn"]["max_hp"]
    assert payload["character"]["cairn"]["deprived"] is False
    assert payload["oracle_history"][-1]["cairn"]["ration_uses_before"] == 3
    assert payload["oracle_history"][-1]["cairn"]["ration_uses_after"] == 2


def test_submit_turn_routes_retreat(tmp_path: Path) -> None:
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
            "/api/turn",
            json={"text": "I fall back through the chapel arch."},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["oracle_history"][0]["kind"] == "retreat"
    assert payload["oracle_history"][0]["cairn"]["retreat_outcome"] == "escaped"


def test_submit_turn_routes_equip(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/turn",
            json={"text": "I draw the test knife."},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["oracle_history"][0]["summary"] == "Equipment updated: Test knife equipped."
    assert payload["action_log"][-1]["title"] == "Narrative response"


def test_submit_turn_routes_holy_relic_use_with_receipt_fields(tmp_path: Path) -> None:
    def relic_classifier(text: str, likelihood: Likelihood | None) -> TurnPlan:
        del likelihood
        return TurnPlan(
            route=TurnRoute.PLAYER_ACTION,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.USE_ITEM,
                    text=text,
                    item_name="leaden icon",
                ),
            ),
        )

    store = StateStore(tmp_path / "game_state.json")
    seeded = sample_state()
    seeded.character.cairn = CairnCharacterState(
        source=CairnMechanicsSource.EXPLICIT,
        wil_score=7,
        max_wil_score=10,
        hp=4,
        max_hp=4,
    )
    seeded.character.inventory.append(
        InventoryItem(
            name="Leaden icon",
            details="A cold icon of a nameless patriarch.",
            cairn=CairnItemState(
                source=CairnMechanicsSource.EXPLICIT,
                tags=[CairnItemTag.HOLY, CairnItemTag.RELIC],
                slots=0,
                uses=1,
                power=CairnItemPower(
                    kind=CairnItemPowerKind.HOLY_RELIC,
                    name="Intercession of the Nameless Patriarch",
                    effect=CairnItemEffectKind.RESTORE_ATTRIBUTE,
                    effect_amount=1,
                ),
            ),
        ),
    )
    store.save(seeded, create_checkpoint=False)
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        explainer=FakeExplainer(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=CairnEngine(
            seed=1,
            config=NarrativeConfig(model="", api_key=None, base_url=None),
        ),
        turn_router=TurnRouter(classifier=relic_classifier),
    )
    with TestClient(create_app(service=service)) as client:
        response = client.post(
            "/api/turn",
            json={"text": "I kiss the leaden icon and ask for intercession."},
        )

    assert response.status_code == 200
    payload = response.json()
    outcome = payload["oracle_history"][0]
    assert outcome["kind"] == "player_action"
    assert outcome["cairn"]["item_name"] == "Leaden icon"
    assert outcome["cairn"]["item_power_kind"] == "holy_relic"
    assert outcome["cairn"]["item_effect_kind"] == "restore_attribute"
    assert outcome["cairn"]["wil_before"] == 7
    assert outcome["cairn"]["wil_after"] == 8
    assert payload["character"]["cairn"]["wil_score"] == 8


def test_submit_turn_can_return_dynamic_thread_updates(tmp_path: Path) -> None:
    def mutate(state: GameState, outcome: OracleOutcome) -> tuple[str, ...]:
        del outcome
        created = GameThread(
            title="The hierophant's unfinished demand",
            stakes="If ignored, the abbey's claim hardens into pursuit.",
        )
        state.threads.append(created)
        return (created.id,)

    with _client(tmp_path, thread_updater=FakeThreadUpdater(mutate=mutate)) as client:
        response = client.post(
            "/api/turn",
            json={"text": "I agree to hear the hierophant's charge."},
        )
    assert response.status_code == 200
    payload = response.json()
    created = next(
        thread
        for thread in payload["threads"]
        if thread["title"] == "The hierophant's unfinished demand"
    )
    assert payload["oracle_history"][0]["referenced_thread_id"] == created["id"]
    assert payload["oracle_history"][0]["referenced_thread_ids"] == [created["id"]]


def test_submit_turn_can_return_dynamic_npc_updates(tmp_path: Path) -> None:
    def mutate(state: GameState, outcome: OracleOutcome) -> tuple[str, ...]:
        del outcome
        created = NPC(
            name="Brother Vahagn",
            role="Bell-ringer hiding a blood debt",
            disposition="guarded",
        )
        state.npcs.append(created)
        return (created.id,)

    with _client(tmp_path, npc_updater=FakeNpcUpdater(mutate=mutate)) as client:
        response = client.post(
            "/api/turn",
            json={"text": "I ask the bell-ringer why he watches me."},
        )

    assert response.status_code == 200
    payload = response.json()
    created = next(npc for npc in payload["npcs"] if npc["name"] == "Brother Vahagn")
    assert created["status"] == NPCStatus.ACTIVE.value
    assert payload["oracle_history"][0]["referenced_npc_id"] == created["id"]
    assert payload["oracle_history"][0]["referenced_npc_ids"] == [created["id"]]


def test_update_directives_endpoint_persists_ooc_guidance(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/state/directives",
            json={
                "world_guidance": "Keep miracles subtle and costly.",
                "play_guidance": "The hierophant cannot speak first.",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["directives"]["world_guidance"] == "Keep miracles subtle and costly."
    assert payload["directives"]["play_guidance"] == "The hierophant cannot speak first."
    assert all(event["title"] != "Campaign directives updated" for event in payload["action_log"])
