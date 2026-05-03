from pathlib import Path

from dungeon_master.campaign import CharacterDraftMode
from dungeon_master.models import (
    CampaignStatus,
    CharacterQuiz,
    CharacterQuizAnswer,
    CharacterQuizOption,
    CharacterQuizQuestion,
    CharacterSheet,
    GameState,
    Likelihood,
    OracleOutcome,
)
from dungeon_master.oracle import OracleEngine
from dungeon_master.service import GameService
from dungeon_master.state_store import StateStore
from tests.factories import sample_state


class FakeNarrative:
    def generate(self, state: GameState, outcome: OracleOutcome, player_input: str) -> str:
        return f"FAKE: {outcome.summary} / {player_input} / chaos {state.chaos_factor}"


class FakeCampaignGenerator:
    def generate(self, character: CharacterSheet) -> GameState:
        state = sample_state()
        state.character = character
        state.player_notes = character.backstory
        return state


class FakeCharacterGenerator:
    def setup_state(self) -> GameState:
        return sample_state()

    def generate_templates(self) -> list[CharacterSheet]:
        return [sample_state().character]

    def generate_draft(
        self,
        *,
        mode: CharacterDraftMode,
        prompt: str | None,
        template: CharacterSheet | None,
    ) -> CharacterSheet:
        del mode, prompt, template
        return sample_state().character

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

    def generate(self, state: GameState, outcome: OracleOutcome, player_input: str) -> str:
        self.calls += 1
        return f"GEN {self.calls}: {outcome.summary} / {player_input} / chaos {state.chaos_factor}"


def test_service_commits_oracle_turn_with_narration(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
    )

    state = service.ask_oracle("Is the abbey gate watched?", Likelihood.LIKELY)

    assert len(state.oracle_history) == 1
    assert len(state.action_log) == 2
    assert state.action_log[-1].content.startswith("FAKE:")


def test_service_scene_check_updates_current_scene(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
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
    )

    state = service.submit_player_turn("I cross the bone bridge before dawn.")

    assert state.action_log[0].title == "Player action"
    assert state.action_log[1].title == "Scene check"
    assert state.scene_number == 2
    assert state.oracle_history[0].kind == "scene_check"


def test_finalize_character_sets_ready_to_start(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=SetupCharacterGenerator(),
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
    )

    character = sample_state().character.model_copy(deep=True)
    character.name = "Sable"
    service.finalize_character(character)
    state = service.start_campaign()

    assert state.campaign_status == CampaignStatus.ACTIVE
    assert state.character.name == "Sable"


def test_generate_character_quiz_uses_concept(tmp_path: Path) -> None:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=SetupCharacterGenerator(),
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
