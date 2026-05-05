"""Integration tests for the FastAPI surface.

These tests don't go to the network: a `FakeNarrative` and
`FakeCampaignGenerator` replace LiteLLM, so we exercise the routing,
serialization, and state-mutation contracts without spending tokens.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from fastapi.testclient import TestClient

from dungeon_master.api import create_app
from dungeon_master.campaign import (
    CampaignWorldResult,
    CharacterDraftMode,
    CharacterDraftResult,
    CharacterQuizResult,
    CharacterTemplatesResult,
)
from dungeon_master.cancel import CancellationToken
from dungeon_master.models import (
    AttackStance,
    CairnAbility,
    CairnCharacterState,
    CairnItemState,
    CairnItemTag,
    CairnMechanicsSource,
    CairnResolution,
    CairnRestKind,
    CampaignStatus,
    CharacterQuiz,
    CharacterQuizAnswer,
    CharacterQuizOption,
    CharacterQuizQuestion,
    CharacterSheet,
    EncounterState,
    EnemyCombatant,
    GameState,
    Likelihood,
    OracleKind,
    OracleOutcome,
    RetreatOutcome,
)
from dungeon_master.narrative import (
    CompletionDelta,
    CompletionRequest,
    NarrativeConfig,
    NarrativeResult,
)
from dungeon_master.oracle import OracleEngine
from dungeon_master.service import GameService
from dungeon_master.state_store import StateStore
from dungeon_master.turn_router import RoutedTurn, TurnRoute, TurnRouter
from tests.factories import sample_state

if TYPE_CHECKING:
    from litellm.types.utils import ModelResponse


class FakeNarrative:
    def generate(  # noqa: PLR0913
        self,
        state: GameState,
        outcome: OracleOutcome,
        player_input: str,
        *,
        execution_context: str | None = None,
        memory_context: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> str:
        del cancel_token
        suffix = f" / ctx {execution_context}" if execution_context else ""
        memory_suffix = " / mem yes" if memory_context else ""
        return (
            f"FAKE: {outcome.summary} / {player_input} / chaos {state.chaos_factor}"
            f"{suffix}{memory_suffix}"
        )


class ThoughtfulNarrative(FakeNarrative):
    def generate_result(  # noqa: PLR0913
        self,
        state: GameState,
        outcome: OracleOutcome,
        player_input: str,
        *,
        execution_context: str | None = None,
        memory_context: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> NarrativeResult:
        del cancel_token
        return NarrativeResult(
            content=self.generate(
                state,
                outcome,
                player_input,
                execution_context=execution_context,
                memory_context=memory_context,
            ),
            thinking=f"Thought about {outcome.kind}.",
        )

    def iter_stream(  # noqa: PLR0913
        self,
        state: GameState,
        outcome: OracleOutcome,
        player_input: str,
        *,
        execution_context: str | None = None,
        memory_context: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, NarrativeResult]:
        del cancel_token
        yield CompletionDelta(thinking=f"Thought about {outcome.kind}.")
        yield CompletionDelta(
            content=self.generate(
                state,
                outcome,
                player_input,
                execution_context=execution_context,
                memory_context=memory_context,
            ),
        )
        return self.generate_result(
            state,
            outcome,
            player_input,
            execution_context=execution_context,
            memory_context=memory_context,
        )


class BrokenPlannerCompletion:
    def __call__(self, request: CompletionRequest) -> ModelResponse:
        del request
        return []  # type: ignore[return-value]


class FakeCampaignGenerator:
    def generate(self, character: CharacterSheet) -> GameState:
        state = sample_state()
        state.character = character
        state.player_notes = character.backstory
        return state

    def generate_result(self, character: CharacterSheet) -> CampaignWorldResult:
        return CampaignWorldResult(state=self.generate(character))

    def iter_generate(
        self,
        character: CharacterSheet,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CampaignWorldResult]:
        del cancel_token
        result = self.generate_result(character)
        yield CompletionDelta(content=result.state.model_dump_json())
        return result


class FakeCharacterGenerator:
    def setup_state(self) -> GameState:
        return sample_state()

    def generate_templates(self) -> list[CharacterSheet]:
        return [sample_state().character]

    def generate_templates_result(self) -> CharacterTemplatesResult:
        return CharacterTemplatesResult(templates=self.generate_templates())

    def iter_generate_templates(
        self,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterTemplatesResult]:
        del cancel_token
        result = self.generate_templates_result()
        yield CompletionDelta(content=result.templates[0].model_dump_json())
        return result

    def generate_draft(
        self,
        *,
        mode: CharacterDraftMode,
        prompt: str | None,
        template: CharacterSheet | None,
    ) -> CharacterSheet:
        del mode, prompt, template
        return sample_state().character

    def generate_draft_result(
        self,
        *,
        mode: CharacterDraftMode,
        prompt: str | None,
        template: CharacterSheet | None,
    ) -> CharacterDraftResult:
        return CharacterDraftResult(
            draft=self.generate_draft(mode=mode, prompt=prompt, template=template),
        )

    def iter_generate_draft(
        self,
        *,
        mode: CharacterDraftMode,
        prompt: str | None,
        template: CharacterSheet | None,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterDraftResult]:
        del cancel_token
        result = self.generate_draft_result(mode=mode, prompt=prompt, template=template)
        yield CompletionDelta(content=result.draft.model_dump_json())
        return result

    def generate_quiz(self, concept: str) -> CharacterQuiz:
        return CharacterQuiz(
            concept=concept,
            questions=[
                CharacterQuizQuestion(
                    prompt="Where were you when faith asked too much?",
                    options=[
                        CharacterQuizOption(label="At a roadside crucifixion."),
                        CharacterQuizOption(label="In a sacked monastery cellar."),
                        CharacterQuizOption(label="Watching a child you couldn't bury."),
                    ],
                ),
                CharacterQuizQuestion(
                    prompt="What sin do you keep committing?",
                    options=[
                        CharacterQuizOption(label="Mercy for the wrong people."),
                        CharacterQuizOption(label="Keeping a relic you should burn."),
                        CharacterQuizOption(label="Bargains spoken at thresholds."),
                    ],
                ),
                CharacterQuizQuestion(
                    prompt="Who is still hunting you?",
                    options=[
                        CharacterQuizOption(label="The order that ordained you."),
                        CharacterQuizOption(label="A creditor with a writ of teeth."),
                        CharacterQuizOption(label="Your own dead."),
                    ],
                ),
            ],
        )

    def generate_quiz_result(self, concept: str) -> CharacterQuizResult:
        return CharacterQuizResult(quiz=self.generate_quiz(concept))

    def iter_generate_quiz(
        self,
        concept: str,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterQuizResult]:
        del cancel_token
        result = self.generate_quiz_result(concept)
        yield CompletionDelta(content=result.quiz.model_dump_json())
        return result

    def generate_quizzed_draft(
        self,
        *,
        concept: str,
        answers: list[CharacterQuizAnswer],
        final_note: str | None,
    ) -> CharacterSheet:
        sheet = sample_state().character.model_copy(deep=True)
        sheet.epithet = concept
        sheet.backstory = "; ".join(answer.value for answer in answers) or "no answers"
        if final_note:
            sheet.condition = final_note
        return sheet

    def generate_quizzed_draft_result(
        self,
        *,
        concept: str,
        answers: list[CharacterQuizAnswer],
        final_note: str | None,
    ) -> CharacterDraftResult:
        return CharacterDraftResult(
            draft=self.generate_quizzed_draft(
                concept=concept,
                answers=answers,
                final_note=final_note,
            ),
        )

    def iter_generate_quizzed_draft(
        self,
        *,
        concept: str,
        answers: list[CharacterQuizAnswer],
        final_note: str | None,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterDraftResult]:
        del cancel_token
        result = self.generate_quizzed_draft_result(
            concept=concept,
            answers=answers,
            final_note=final_note,
        )
        yield CompletionDelta(content=result.draft.model_dump_json())
        return result


class SetupCharacterGenerator(FakeCharacterGenerator):
    def setup_state(self) -> GameState:
        state = sample_state()
        state.campaign_status = CampaignStatus.CHARACTER_CREATION
        state.threads = []
        state.npcs = []
        state.action_log = []
        state.oracle_history = []
        return state


class FakeCairnEngine:
    def ensure_character_state(
        self,
        state: GameState,
        *,
        allow_backfill: bool,
        cancel_token: CancellationToken | None = None,
    ) -> bool:
        del cancel_token
        if state.character.cairn.source != CairnMechanicsSource.UNSET:
            return False
        if not allow_backfill:
            return False
        state.character.cairn = CairnCharacterState(
            source=CairnMechanicsSource.NARRATIVE_BACKFILL,
            backfill_version=3,
            skills=["Shrine lore"],
            abilities=["Condemn sorcery"],
            str_score=14,
            dex_score=12,
            wil_score=15,
            max_str_score=14,
            max_dex_score=12,
            max_wil_score=15,
            hp=4,
            max_hp=4,
            primary_weapon_item_id=state.character.inventory[0].id,
        )
        for item in state.character.inventory:
            item.cairn = CairnItemState(
                source=CairnMechanicsSource.NARRATIVE_BACKFILL,
                backfill_version=3,
                tags=[CairnItemTag.WEAPON] if item == state.character.inventory[0] else [],
                weapon_damage_die=6 if item == state.character.inventory[0] else None,
                equipped=item == state.character.inventory[0],
            )
        state.character.cairn.slots_used = len(state.character.inventory)
        return True

    def set_item_equipped(self, state: GameState, *, item_id: str, equipped: bool) -> None:
        for item in state.character.inventory:
            item.cairn.equipped = item.id == item_id if equipped else False
        if equipped:
            state.character.cairn.primary_weapon_item_id = item_id

    def use_item(self, state: GameState, *, item_id: str, intent: str) -> str:
        for item in list(state.character.inventory):
            if item.id != item_id:
                continue
            if item.cairn.uses is None:
                return f"Used {item.name}: {intent}. No limited uses were consumed."
            remaining = item.cairn.uses - 1
            if remaining <= 0:
                state.character.inventory = [
                    candidate for candidate in state.character.inventory if candidate.id != item_id
                ]
                return f"Used {item.name}: final use spent, item exhausted and removed."
            item.cairn.uses = remaining
            return f"Used {item.name}: {remaining} uses remain."
        message = f"Unknown inventory item: {item_id}"
        raise ValueError(message)

    def drop_item(self, state: GameState, *, item_id: str) -> str:
        for item in list(state.character.inventory):
            if item.id != item_id:
                continue
            state.character.inventory = [
                candidate for candidate in state.character.inventory if candidate.id != item_id
            ]
            return f"Dropped {item.name}."
        message = f"Unknown inventory item: {item_id}"
        raise ValueError(message)

    def resolve_retreat(self, state: GameState, reason: str) -> OracleOutcome:
        state.encounter.active = False
        state.encounter.notes = "You escaped the encounter."
        return OracleOutcome(
            kind=OracleKind.RETREAT,
            summary=f"Retreat resolved: {reason}",
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                ability=CairnAbility.DEX,
                target=12,
                success=True,
                retreat_outcome=RetreatOutcome.ESCAPED,
                combat_active=False,
            ),
        )


class FakePlayableCairnEngine(FakeCairnEngine):
    def resolve_save(self, state: GameState, ability: CairnAbility, reason: str) -> OracleOutcome:
        return OracleOutcome(
            kind=OracleKind.SAVE,
            summary=f"{ability.value} save passed: {reason}",
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(ability=ability, target=12, success=True),
        )

    def resolve_attack(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        target_name: str,
        target_armor: int,
        weapon_item_id: str | None,
        stance: AttackStance,
        cancel_token: CancellationToken | None = None,
    ) -> OracleOutcome:
        del cancel_token
        return OracleOutcome(
            kind=OracleKind.ATTACK,
            summary=f"Attack against {target_name}.",
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                weapon_item_id=weapon_item_id,
                target_name=target_name,
                target_armor=target_armor,
                attack_stance=stance,
                base_damage=5,
                damage_after_armor=max(0, 5 - target_armor),
            ),
        )

    def suffer_harm(
        self,
        state: GameState,
        *,
        amount: int,
        source: str,
        in_combat: bool,
        armor_applies: bool,
    ) -> OracleOutcome:
        del in_combat, armor_applies
        state.character.cairn.hp = max(0, state.character.cairn.hp - amount)
        return OracleOutcome(
            kind=OracleKind.HARM,
            summary=f"Harm from {source}.",
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(
                target_name=source,
                base_damage=amount,
                damage_after_armor=amount,
                hp_before=4,
                hp_after=state.character.cairn.hp,
                str_before=state.character.cairn.max_str_score,
                str_after=state.character.cairn.str_score,
            ),
        )

    def recover(self, state: GameState, kind: CairnRestKind) -> OracleOutcome:
        state.character.cairn.hp = state.character.cairn.max_hp
        return OracleOutcome(
            kind=OracleKind.RECOVERY,
            summary=f"Recovery: {kind.value}",
            chaos_factor=state.chaos_factor,
            cairn=CairnResolution(rest_kind=kind, hp_before=0, hp_after=state.character.cairn.hp),
        )


def scripted_classifier(text: str, likelihood: Likelihood | None) -> RoutedTurn:  # noqa: PLR0911
    if text == "Is the abbey gate watched?":
        return RoutedTurn(
            route=TurnRoute.YES_NO,
            text=text,
            likelihood=likelihood or Likelihood.UNLIKELY,
        )
    if text == "I balance across the abbey beam.":
        return RoutedTurn(route=TurnRoute.SAVE, text=text, ability=CairnAbility.DEX)
    if text == "I swing my cudgel at the abbey ghoul.":
        return RoutedTurn(
            route=TurnRoute.ATTACK,
            text=text,
            target_name="Abbey ghoul",
            stance=AttackStance.NORMAL,
        )
    if text == "I catch my breath and drink water.":
        return RoutedTurn(
            route=TurnRoute.RECOVERY,
            text=text,
            rest_kind=CairnRestKind.BREATHER,
        )
    if text == "I draw the test knife.":
        return RoutedTurn(
            route=TurnRoute.EQUIP,
            text=text,
            item_name="Test knife",
            equipped=True,
        )
    if text == "I fall back through the chapel arch.":
        return RoutedTurn(route=TurnRoute.RETREAT, text=text)
    return RoutedTurn(route=TurnRoute.PLAYER_ACTION, text=text)


def _client(tmp_path: Path, *, turn_router: TurnRouter | None = None) -> TestClient:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakePlayableCairnEngine(),
        turn_router=turn_router or TurnRouter(classifier=scripted_classifier),
    )
    return TestClient(create_app(service=service))


def _setup_client(tmp_path: Path) -> TestClient:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
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
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakePlayableCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )
    return TestClient(create_app(service=service))


def _broken_planner_client(tmp_path: Path) -> TestClient:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
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


def test_health(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cancel_unknown_request_returns_false(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post("/api/requests/req_missing/cancel")
    assert response.status_code == 200
    assert response.json() == {"cancelled": False}


def test_cancel_live_request_returns_true(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        token = cast("Any", client.app).state.cancellation_registry.register("req_live")
        response = client.post("/api/requests/req_live/cancel")
    assert response.status_code == 200
    assert response.json() == {"cancelled": True}
    assert token.cancelled


def test_state_round_trip(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        first = client.get("/api/state").json()
        second = client.get("/api/state").json()
    # The campaign is generated once on the first read and persisted, so a
    # second read must return the same canonical state - this is what
    # protects us from "the oracle keeps regenerating my campaign" bugs.
    assert first["id"] == second["id"]
    assert len(first["threads"]) == 3


def test_chaos_factor_clamped(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post("/api/state/chaos", json={"value": 12})
    # Pydantic must reject out-of-range values up front; we never want a
    # chaos factor outside [1, 9] to slip into the persisted state file.
    assert response.status_code == 422


def test_chaos_factor_persists(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        client.post("/api/state/chaos", json={"value": 7})
        state = client.get("/api/state").json()
    assert state["chaos_factor"] == 7


def test_oracle_yes_no(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/oracle/yes-no",
            json={"question": "Does anything stir?", "likelihood": "Even odds"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["oracle_history"]) == 1
    assert payload["oracle_history"][0]["kind"] == "yes_no"


def test_random_event_uses_generated_tables(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post("/api/oracle/random-event")
    assert response.status_code == 200
    outcome = response.json()["oracle_history"][0]
    # Random events must pull from the campaign-generated word banks; a
    # missing focus/action would mean we accidentally re-introduced the
    # hardcoded oracle tables.
    assert outcome["event_focus"]
    assert outcome["event_action"]


def test_scene_check_advances_scene(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post(
            "/api/oracle/scene-check",
            json={"expected_scene": "I cross the bone bridge."},
        )
    state = response.json()
    assert state["scene_number"] >= 2


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


def test_submit_turn_returns_explicit_planning_failure(tmp_path: Path) -> None:
    with _broken_planner_client(tmp_path) as client:
        response = client.post(
            "/api/turn",
            json={"text": "I listen at the abbey door."},
        )

    assert response.status_code == 503
    assert "deterministic resolution" in response.json()["detail"]


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
    assert "thinking_delta" in types
    assert "content_delta" in types
    assert types[-1] == "final_state"
    final = parsed[-1]
    assert final["state"]["action_log"][-1]["title"] == "Narrative response"
    assert final["thinking"] == "Thought about attack."


def test_submit_turn_stream_emits_explicit_planning_error(tmp_path: Path) -> None:
    with _broken_planner_client(tmp_path) as client:
        response = client.post(
            "/api/turn/stream",
            json={"text": "I listen at the abbey door."},
        )

    assert response.status_code == 200
    parsed = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert parsed[0]["type"] == "meta"
    assert parsed[-1]["type"] == "error"
    assert parsed[-1]["code"] == "planning_failed"


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
    parsed = [
        json.loads(line) for line in response.text.splitlines() if line.strip()
    ]
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
    parsed = [
        json.loads(line) for line in response.text.splitlines() if line.strip()
    ]
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
    with _thoughtful_client(tmp_path) as client:
        client.post("/api/character/finalize", json={"character": character.model_dump()})
        response = client.post("/api/campaign/start")
    assert response.status_code == 200
    system_event = response.json()["action_log"][-1]
    assert system_event["title"] == "Campaign initialized"
    assert "Thought" in system_event["thinking"] or system_event["thinking"] == ""


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
