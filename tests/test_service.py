from collections.abc import Generator
from pathlib import Path

import pytest

from dungeon_master.campaign import (
    CampaignWorldResult,
    CharacterDraftMode,
    CharacterDraftResult,
    CharacterQuizResult,
    CharacterTemplatesResult,
)
from dungeon_master.cancel import CancellationRegistry, CancellationToken, RequestCancelledError
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
    EventType,
    GameState,
    Likelihood,
    OracleKind,
    OracleOutcome,
    RetreatOutcome,
)
from dungeon_master.narrative import CompletionDelta
from dungeon_master.oracle import OracleEngine
from dungeon_master.service import GameService
from dungeon_master.state_store import StateStore
from dungeon_master.turn_router import (
    PlannedTurnOp,
    PlannedTurnOpKind,
    RoutedTurn,
    TurnPlan,
    TurnRoute,
    TurnRouter,
)
from tests.factories import sample_state


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
            concept=concept or "Test concept",
            questions=[
                CharacterQuizQuestion(
                    prompt="Test question one?",
                    options=[
                        CharacterQuizOption(label="Test option A"),
                        CharacterQuizOption(label="Test option B"),
                        CharacterQuizOption(label="Test option C"),
                    ],
                ),
                CharacterQuizQuestion(
                    prompt="Test question two?",
                    options=[
                        CharacterQuizOption(label="Test option D"),
                        CharacterQuizOption(label="Test option E"),
                        CharacterQuizOption(label="Test option F"),
                    ],
                ),
                CharacterQuizQuestion(
                    prompt="Test question three?",
                    options=[
                        CharacterQuizOption(label="Test option G"),
                        CharacterQuizOption(label="Test option H"),
                        CharacterQuizOption(label="Test option I"),
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
        # Make the test sheet visibly reflect inputs so we can assert plumbing.
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


class CountingNarrative:
    def __init__(self) -> None:
        self.calls = 0

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
        del cancel_token, execution_context, memory_context
        self.calls += 1
        return f"GEN {self.calls}: {outcome.summary} / {player_input} / chaos {state.chaos_factor}"


class SlowStreamingNarrative(FakeNarrative):
    def iter_stream(  # noqa: PLR0913
        self,
        state: GameState,
        outcome: OracleOutcome,
        player_input: str,
        *,
        execution_context: str | None = None,
        memory_context: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, str]:
        del state, outcome, player_input, execution_context, memory_context
        yield CompletionDelta(thinking="Working...")
        while True:
            if cancel_token is not None:
                cancel_token.raise_if_cancelled()
            yield CompletionDelta(content="...")


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
        state.character.cairn.str_score = min(
            state.character.cairn.str_score,
            state.character.cairn.max_str_score,
        )
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


def scripted_classifier(text: str, likelihood: Likelihood | None) -> RoutedTurn:  # noqa: PLR0911
    if text == "Is the abbey gate watched?":
        return RoutedTurn(
            route=TurnRoute.YES_NO,
            text=text,
            likelihood=likelihood or Likelihood.LIKELY,
        )
    if text == "I cross the bone bridge before dawn.":
        return RoutedTurn(route=TurnRoute.SCENE_CHECK, text=text)
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


def test_service_commits_oracle_turn_with_narration(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    state = service.ask_oracle("Is the abbey gate watched?", Likelihood.LIKELY)

    assert len(state.oracle_history) == 1
    assert len(state.action_log) == 2
    assert state.action_log[-1].content.startswith("FAKE:")


def test_service_persists_memory_sidecar_after_committed_turn(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    service.ask_oracle("Is the abbey gate watched?", Likelihood.LIKELY)
    memory = store.load_memory()

    assert memory.turn_count == 1
    assert memory.recent_turn_summaries[-1].oracle_kind == OracleKind.YES_NO
    assert memory.current_scene_summary


def test_service_scene_check_updates_current_scene(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    state = service.check_scene("I arrive before midnight.")

    assert state.scene_number == 2
    assert state.current_scene == "Interrupted before: I arrive before midnight."
    assert len(state.oracle_history) == 1


def test_service_player_action_does_not_require_oracle_roll(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    state = service.submit_player_action("I listen at the abbey door.")

    assert state.oracle_history[0].rolls == []
    assert state.action_log[0].title == "Player action"
    assert state.action_log[1].title == "Narrative response"


def test_service_player_turn_routes_question_through_oracle(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    state = service.submit_player_turn("Is the abbey gate watched? [likely]")

    assert state.action_log[0].title == "Player action"
    assert state.action_log[1].title == "Oracle answer"
    assert state.action_log[2].title == "Narrative response"
    assert state.oracle_history[0].kind == "yes_no"
    assert state.oracle_history[0].likelihood == Likelihood.LIKELY


def test_service_player_turn_routes_scene_transition(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    state = service.submit_player_turn("I cross the bone bridge before dawn.")

    assert state.action_log[0].title == "Player action"
    assert state.action_log[1].title == "Scene check"
    assert state.scene_number == 2
    assert state.oracle_history[0].kind == "scene_check"


def test_service_player_turn_routes_obvious_save(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    state = service.submit_player_turn("I balance across the abbey beam.")

    assert state.action_log[0].title == "Player action"
    assert state.action_log[1].title == "Cairn save"
    assert state.oracle_history[0].kind == "save"
    assert state.oracle_history[0].cairn is not None
    assert state.oracle_history[0].cairn.ability == CairnAbility.DEX


def test_service_player_turn_routes_attack(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    state = service.submit_player_turn("I swing my cudgel at the abbey ghoul.")

    assert state.action_log[0].title == "Player action"
    assert state.action_log[1].title == "Attack resolution"
    assert state.oracle_history[0].kind == "attack"
    assert state.oracle_history[0].cairn is not None
    assert state.oracle_history[0].cairn.target_name == "Abbey ghoul"


def test_service_player_turn_routes_recovery(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    state = service.submit_player_turn("I catch my breath and drink water.")

    assert state.action_log[0].title == "Player action"
    assert state.action_log[1].title == "Recovery"
    assert state.oracle_history[0].kind == "recovery"
    assert state.oracle_history[0].cairn is not None
    assert state.oracle_history[0].cairn.rest_kind == CairnRestKind.BREATHER


def test_service_player_turn_routes_retreat(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )
    state = service.load_state()
    state.encounter = EncounterState(
        active=True,
        round_number=2,
        combatants=[EnemyCombatant(name="Abbey ghoul", hp=4, max_hp=4)],
    )
    store.save(state, create_checkpoint=False)

    retreated = service.submit_player_turn("I fall back through the chapel arch.")

    assert retreated.action_log[0].title == "Player action"
    assert retreated.action_log[1].title == "Retreat resolution"
    assert retreated.oracle_history[0].kind == "retreat"
    assert retreated.oracle_history[0].cairn is not None
    assert retreated.oracle_history[0].cairn.retreat_outcome == RetreatOutcome.ESCAPED


def test_service_player_turn_routes_equip(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    state = service.submit_player_turn("I draw the test knife.")

    assert state.action_log[0].title == "Player action"
    assert state.action_log[1].title == "Narrative response"
    assert state.oracle_history[0].summary == "Equipment updated: Test knife equipped."


def test_service_player_turn_executes_compound_inventory_plan(tmp_path: Path) -> None:
    def compound_classifier(text: str, likelihood: Likelihood | None) -> TurnPlan:
        del likelihood
        return TurnPlan(
            route=TurnRoute.PLAYER_ACTION,
            text=text,
            ops=(
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.INSPECT_INVENTORY,
                    text="I check my supplies.",
                ),
                PlannedTurnOp(
                    kind=PlannedTurnOpKind.DROP_ITEM,
                    text="I drop the test map.",
                    item_name="Test map",
                ),
            ),
        )

    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=compound_classifier),
    )

    state = service.submit_player_turn("I check my supplies and drop the map.")

    assert state.action_log[0].title == "Player action"
    assert state.action_log[1].title == "Narrative response"
    assert state.oracle_history[0].kind == OracleKind.PLAYER_ACTION
    assert [item.name for item in state.character.inventory] == ["Test knife"]
    assert "Dropped Test map." in state.action_log[1].content


def test_finalize_character_sets_ready_to_start(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=SetupCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    character = sample_state().character
    state = service.finalize_character(character)

    assert state.campaign_status == CampaignStatus.READY_TO_START
    assert state.character.name == character.name


def test_start_campaign_uses_finalized_character(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=SetupCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    character = sample_state().character.model_copy(deep=True)
    character.name = "Sable"
    service.finalize_character(character)
    state = service.start_campaign()

    assert state.campaign_status == CampaignStatus.ACTIVE
    assert state.character.name == "Sable"
    assert state.character.cairn.source == CairnMechanicsSource.NARRATIVE_BACKFILL
    assert state.character.cairn.slots_used >= 1
    assert state.character.cairn.primary_weapon_item_id is not None


def test_load_state_backfills_active_character_once(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    state = service.load_state()

    assert state.character.cairn.source == CairnMechanicsSource.NARRATIVE_BACKFILL
    assert state.character.cairn.max_hp >= 1
    assert any(
        item.cairn.source == CairnMechanicsSource.NARRATIVE_BACKFILL
        for item in state.character.inventory
    )


def test_service_resolve_save_records_deterministic_outcome(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    state = service.resolve_cairn_save(CairnAbility.WIL, "Resist the bell's whisper.")

    assert state.oracle_history[-1].kind == "save"
    assert state.oracle_history[-1].cairn is not None
    assert state.oracle_history[-1].cairn.ability == CairnAbility.WIL


def test_service_attack_uses_primary_weapon(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    state = service.load_state()
    primary_weapon_id = state.character.cairn.primary_weapon_item_id
    assert primary_weapon_id is not None

    attacked = service.attack_target(
        target_name="Abbey ghoul",
        target_armor=1,
        weapon_item_id=primary_weapon_id,
        stance=AttackStance.NORMAL,
    )

    assert attacked.oracle_history[-1].kind == "attack"
    assert attacked.oracle_history[-1].cairn is not None
    assert attacked.oracle_history[-1].cairn.weapon_item_id == primary_weapon_id


def test_service_harm_can_trigger_str_loss(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    state = service.load_state()
    state.character.cairn.hp = 1
    store.save(state, create_checkpoint=False)

    harmed = service.suffer_harm(
        amount=5,
        source="Falling masonry",
        in_combat=True,
        armor_applies=False,
    )

    assert harmed.oracle_history[-1].kind == "harm"
    assert harmed.character.cairn.hp == 0
    assert harmed.character.cairn.str_score <= harmed.character.cairn.max_str_score


def test_service_recovery_restores_hp(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    state = service.load_state()
    state.character.cairn.hp = 0
    store.save(state, create_checkpoint=False)

    recovered = service.recover_character(CairnRestKind.BREATHER)

    assert recovered.oracle_history[-1].kind == "recovery"
    assert recovered.character.cairn.hp == recovered.character.cairn.max_hp


def test_service_explicit_retreat_records_deterministic_outcome(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )
    state = service.load_state()
    state.encounter = EncounterState(
        active=True,
        round_number=2,
        combatants=[EnemyCombatant(name="Abbey ghoul", hp=4, max_hp=4)],
    )
    store.save(state, create_checkpoint=False)

    retreated = service.retreat_from_encounter("Break contact and reach the chapel arch.")

    assert retreated.oracle_history[-1].kind == "retreat"
    assert retreated.oracle_history[-1].cairn is not None
    assert retreated.oracle_history[-1].cairn.retreat_outcome == RetreatOutcome.ESCAPED


def test_generate_character_quiz_uses_concept(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=SetupCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    quiz = service.generate_character_quiz("An Armenian Apostolic paladin.")

    assert quiz.concept == "An Armenian Apostolic paladin."
    assert len(quiz.questions) >= 3


def test_generate_quizzed_draft_threads_answers_through(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=SetupCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    quiz = service.generate_character_quiz("A scarred deserter.")
    answers = [
        CharacterQuizAnswer(
            question_id=quiz.questions[0].id,
            prompt=quiz.questions[0].prompt,
            value="Wounded but standing.",
        ),
        CharacterQuizAnswer(
            question_id=quiz.questions[1].id,
            prompt=quiz.questions[1].prompt,
            value="A name I cannot say.",
        ),
        CharacterQuizAnswer(
            question_id=quiz.questions[2].id,
            prompt=quiz.questions[2].prompt,
            value="My old company.",
            is_other=True,
        ),
    ]

    draft = service.generate_quizzed_character_draft(
        concept="A scarred deserter.",
        answers=answers,
        final_note="One scar shaped like a sigil.",
    )

    assert draft.epithet == "A scarred deserter."
    assert "Wounded but standing." in draft.backstory
    assert "A name I cannot say." in draft.backstory
    assert "My old company." in draft.backstory
    assert draft.condition == "One scar shaped like a sigil."


def test_regenerate_response_preserves_oracle_outcome(tmp_path: Path) -> None:
    narrative = CountingNarrative()
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=narrative,
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )

    first = service.ask_oracle("Is the abbey gate watched?", Likelihood.LIKELY)
    first_event_id = first.action_log[-1].id
    first_outcome = first.oracle_history[-1]

    repaired = service.regenerate_response(first_event_id)
    latest_outcome = repaired.oracle_history[-1]

    assert latest_outcome.id == first_outcome.id
    assert latest_outcome.answer == first_outcome.answer
    assert repaired.action_log[-2].title == "Narrative regenerated"
    assert repaired.action_log[-1].title == "Narrative response"
    assert repaired.action_log[-1].content.startswith("GEN 2:")


def test_streamed_regenerate_does_not_duplicate_prior_narrative(tmp_path: Path) -> None:
    narrative = CountingNarrative()
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=narrative,
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    stream = service.stream_submit_player_turn("Is the abbey gate watched? [likely]")
    for _ in stream:
        pass
    state = service.load_state()
    first_event_id = state.action_log[-1].id

    repaired = service.regenerate_response(first_event_id)
    narrative_events = [
        event for event in repaired.action_log if event.event_type == EventType.NARRATIVE
    ]

    assert len(narrative_events) == 1
    assert repaired.action_log[-2].title == "Narrative regenerated"
    assert repaired.action_log[-1].title == "Narrative response"


def test_memory_sidecar_preserves_explicit_input_and_execution_context(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
        turn_router=TurnRouter(classifier=scripted_classifier),
    )

    service.ask_oracle("Is the abbey gate watched?", Likelihood.LIKELY)
    service.submit_player_turn("I draw the test knife.")
    memory = store.load_memory()

    assert (
        memory.recent_turn_summaries[0].player_input
        == "Oracle question: Is the abbey gate watched?"
    )
    assert memory.recent_turn_summaries[-1].execution_context
    assert "Equipment updated" in memory.recent_turn_summaries[-1].execution_context


def test_stream_cancel_discards_inflight_turn_state(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "game_state.json")
    service = GameService(
        store=store,
        oracle=OracleEngine(seed=1),
        narrative=SlowStreamingNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
        cairn_engine=FakeCairnEngine(),
    )
    before = service.load_state()
    registry = CancellationRegistry()
    token = registry.register("req_test")

    stream = service.stream_submit_player_action(
        "I wait in silence.",
        cancel_token=token,
    )
    first = next(stream)
    assert first.thinking == "Working..."

    token.cancel()
    with pytest.raises(RequestCancelledError):
        next(stream)

    after = store.load()
    assert after.updated_at == before.updated_at
    assert after.action_log == before.action_log
    assert after.oracle_history == before.oracle_history
    assert not store.events_path.exists()
    assert not store.turn_checkpoints_dir.exists()
