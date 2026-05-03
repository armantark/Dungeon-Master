"""Integration tests for the FastAPI surface.

These tests don't go to the network: a `FakeNarrative` and
`FakeCampaignGenerator` replace LiteLLM, so we exercise the routing,
serialization, and state-mutation contracts without spending tokens.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from dungeon_master.api import create_app
from dungeon_master.campaign import CharacterDraftMode
from dungeon_master.models import (
    CampaignStatus,
    CharacterQuiz,
    CharacterQuizAnswer,
    CharacterQuizOption,
    CharacterQuizQuestion,
)
from dungeon_master.oracle import OracleEngine
from dungeon_master.service import GameService
from dungeon_master.state_store import StateStore
from tests.factories import sample_state

if TYPE_CHECKING:
    from dungeon_master.models import CharacterSheet, GameState, OracleOutcome


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


class SetupCharacterGenerator(FakeCharacterGenerator):
    def setup_state(self) -> GameState:
        state = sample_state()
        state.campaign_status = CampaignStatus.CHARACTER_CREATION
        state.threads = []
        state.npcs = []
        state.action_log = []
        state.oracle_history = []
        return state


def _client(tmp_path: Path) -> TestClient:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=FakeCharacterGenerator(),
    )
    return TestClient(create_app(service=service))


def _setup_client(tmp_path: Path) -> TestClient:
    service = GameService(
        store=StateStore(tmp_path / "game_state.json"),
        oracle=OracleEngine(seed=1),
        narrative=FakeNarrative(),
        campaign_generator=FakeCampaignGenerator(),
        character_generator=SetupCharacterGenerator(),
    )
    return TestClient(create_app(service=service))


def test_health(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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
