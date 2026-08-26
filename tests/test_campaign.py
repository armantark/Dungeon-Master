import json
from collections.abc import Iterator
from typing import cast

import pytest
from litellm.types.utils import ModelResponse

from dungeon_master.domain.models import (
    CampaignGenre,
    CampaignMagicLevel,
    CampaignSeed,
    CampaignStakesScale,
    CampaignTechLevel,
    CampaignTimePeriod,
    CampaignToneDarkBright,
    CampaignToneGrimNoble,
)
from dungeon_master.generation import (
    CampaignGenerationError,
    CampaignGenerator,
    CharacterDraftMode,
    CharacterGenerator,
)
from dungeon_master.llm.narration import CompletionRequest, NarrativeConfig
from tests.factories import sample_state


def _streamed_chunks(content: str) -> Iterator[dict[str, object]]:
    yield {"choices": [{"delta": {"content": content}}]}


def _campaign_payload(*, npc_count: int = 2) -> dict[str, object]:
    return {
        "current_scene": "A generated opening scene.",
        "setting_notes": "Generated setting notes.",
        "threads": [
            {"title": "Thread one", "stakes": "Stakes one."},
            {"title": "Thread two", "stakes": "Stakes two."},
            {"title": "Thread three", "stakes": "Stakes three."},
        ],
        "npcs": [
            {
                "name": f"NPC {index}",
                "role": f"Role {index}",
                "disposition": "watchful",
            }
            for index in range(1, npc_count + 1)
        ],
        "oracle_tables": {
            "event_focus": [
                "thread pressure",
                "npc pressure",
                "location pressure",
                "hidden cost",
                "dangerous choice",
                "new omen",
            ],
            "event_actions": [
                "betray",
                "conceal",
                "demand",
                "forsake",
                "guard",
                "pursue",
                "shatter",
                "withhold",
            ],
            "event_tones": [
                "bitter",
                "cold",
                "desperate",
                "forbidden",
                "hollow",
                "patient",
                "ruined",
                "solemn",
            ],
            "event_subjects": [
                "a debt",
                "a witness",
                "a gate",
                "a relic",
                "a road",
                "a wound",
                "an oath",
                "old blood",
            ],
        },
    }


class CampaignCompletion:
    def __init__(self, *, npc_count: int = 2) -> None:
        self.npc_count = npc_count
        self.request: CompletionRequest | None = None

    def __call__(self, request: CompletionRequest) -> ModelResponse:
        self.request = request
        body = json.dumps(_campaign_payload(npc_count=self.npc_count))
        if request.stream:
            # Mirror the OpenRouter streaming shape so `_iter_stream_response`
            # picks up the content via `choices[0].delta.content`.
            return cast("ModelResponse", _streamed_chunks(body))
        return ModelResponse(
            choices=[{"message": {"role": "assistant", "content": body}}],
        )


class CharacterCompletion:
    def __init__(self, body: dict[str, object]) -> None:
        self.body = body
        self.request: CompletionRequest | None = None

    def __call__(self, request: CompletionRequest) -> ModelResponse:
        self.request = request
        body = json.dumps(self.body)
        if request.stream:
            return cast("ModelResponse", _streamed_chunks(body))
        return ModelResponse(
            choices=[{"message": {"role": "assistant", "content": body}}],
        )


def test_campaign_generator_builds_state_from_model_json() -> None:
    completion = CampaignCompletion()
    generator = CampaignGenerator(
        config=NarrativeConfig(
            model="openrouter/moonshotai/kimi-k2.6",
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
        ),
        completion_function=completion,
    )

    state = generator.generate(sample_state().character)

    assert state.current_scene == "A generated opening scene."
    assert len(state.threads) == 3
    assert len(state.npcs) == 0
    assert len(state.hidden_npcs) == 2
    assert state.oracle_tables.event_focus[0] == "thread pressure"
    assert completion.request is not None
    # We deliberately omit `response_format=json_object` because Kimi K2.6
    # reasons for 200-300+s when that flag is set; the system prompt and
    # `extract_json_object` take care of the JSON contract instead.
    assert completion.request.response_format is None
    assert completion.request.reasoning_effort == "high"
    assert completion.request.stream is True


def test_campaign_generator_trims_extra_npcs_from_model_json() -> None:
    completion = CampaignCompletion(npc_count=4)
    generator = CampaignGenerator(
        config=NarrativeConfig(
            model="openrouter/moonshotai/kimi-k2.6",
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
        ),
        completion_function=completion,
    )

    state = generator.generate(sample_state().character)

    assert state.current_scene == "A generated opening scene."
    assert len(state.hidden_npcs) == 3
    assert [npc.name for npc in state.hidden_npcs] == ["NPC 1", "NPC 2", "NPC 3"]


def test_campaign_generator_system_prompt_defers_to_campaign_seed() -> None:
    completion = CampaignCompletion()
    generator = CampaignGenerator(
        config=NarrativeConfig(
            model="openrouter/moonshotai/kimi-k2.6",
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
        ),
        completion_function=completion,
    )
    seed = CampaignSeed(
        preset="Mid 2020s real life romance",
        time_period=CampaignTimePeriod.MODERN,
        tone_grim_noble=CampaignToneGrimNoble.MIXED,
        tone_dark_bright=CampaignToneDarkBright.BRIGHT,
        genres=[CampaignGenre.HEARTH_AND_HOMESTEAD],
        magic_level=CampaignMagicLevel.NONE,
        tech_level=CampaignTechLevel.MODERN,
        stakes_scale=CampaignStakesScale.PERSONAL_LOCAL,
        inspirations="mid 2020s, basically real life",
        restrictions="No supernatural, horror, medieval, plague, relic, or necromantic content.",
    )

    generator.generate(sample_state().character, seed=seed)

    assert completion.request is not None
    system_prompt = completion.request.messages[0]["content"]
    user_prompt = completion.request.messages[1]["content"]
    assert "campaign seed supplied by the user is authoritative" in system_prompt
    assert "Oppressive medieval dark fantasy" not in system_prompt
    assert "Era/technology: modern with modern technology." in user_prompt


def test_campaign_generator_fails_closed_without_a_model() -> None:
    generator = CampaignGenerator(
        config=NarrativeConfig(model="", api_key=None, base_url=None),
    )

    with pytest.raises(CampaignGenerationError, match="configured model"):
        generator.generate(sample_state().character)


def test_campaign_generator_fails_closed_after_invalid_model_output() -> None:
    generator = CampaignGenerator(
        config=NarrativeConfig(
            model="openrouter/moonshotai/kimi-k2.6",
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
            max_retries=0,
        ),
        completion_function=CharacterCompletion({"not": "a campaign"}),
    )

    with pytest.raises(CampaignGenerationError, match="ValidationError"):
        generator.generate(sample_state().character)


def test_streamed_campaign_generation_fails_closed_after_invalid_output() -> None:
    generator = CampaignGenerator(
        config=NarrativeConfig(
            model="openrouter/moonshotai/kimi-k2.6",
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
            max_retries=0,
        ),
        completion_function=CharacterCompletion({"not": "a campaign"}),
    )

    with pytest.raises(CampaignGenerationError, match="ValidationError"):
        list(generator.iter_generate(sample_state().character))


def test_character_quiz_uses_campaign_seed_creative_direction() -> None:
    completion = CharacterCompletion(
        {
            "questions": [
                {
                    "prompt": "What keeps you from asking directly for companionship?",
                    "options": [
                        {"label": "I hide behind work."},
                        {"label": "I assume rejection before trying."},
                        {"label": "I keep choosing the wrong apps."},
                    ],
                },
                {
                    "prompt": "Which ordinary routine reveals your loneliness?",
                    "options": [
                        {"label": "Late grocery runs."},
                        {"label": "Muted group chats."},
                        {"label": "Sunday afternoon walks."},
                    ],
                },
                {
                    "prompt": "What would make a first connection feel real?",
                    "options": [
                        {"label": "A practical kindness."},
                        {"label": "An unforced conversation."},
                        {"label": "Remembering a small detail."},
                    ],
                },
            ],
        },
    )
    generator = CharacterGenerator(
        config=NarrativeConfig(
            model="openrouter/moonshotai/kimi-k2.6",
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
        ),
        completion_function=completion,
    )
    seed = CampaignSeed(
        preset="Mid 2020s real life romance",
        time_period=CampaignTimePeriod.MODERN,
        tone_grim_noble=CampaignToneGrimNoble.MIXED,
        tone_dark_bright=CampaignToneDarkBright.BRIGHT,
        genres=[CampaignGenre.HEARTH_AND_HOMESTEAD],
        magic_level=CampaignMagicLevel.NONE,
        tech_level=CampaignTechLevel.MODERN,
        stakes_scale=CampaignStakesScale.PERSONAL_LOCAL,
        inspirations="mid 2020s, basically real life",
        restrictions="No supernatural, horror, medieval, plague, relic, or necromantic content.",
    )

    quiz = generator.generate_quiz("a lonely software engineer looking for love", seed=seed)

    assert quiz.questions[0].prompt == "What keeps you from asking directly for companionship?"
    assert completion.request is not None
    system_prompt = completion.request.messages[0]["content"]
    assert "Preset: Mid 2020s real life romance." in system_prompt
    assert "Era/technology: modern with modern technology." in system_prompt
    assert "Genre: hearth and homestead. Magic: none. Stakes: personal local." in system_prompt
    assert "Oppressive medieval dark fantasy" not in system_prompt


def test_character_generator_keeps_no_model_fallbacks() -> None:
    generator = CharacterGenerator(
        config=NarrativeConfig(model="", api_key=None, base_url=None),
    )

    templates = generator.generate_templates()
    draft = generator.generate_draft(
        mode=CharacterDraftMode.SCRATCH,
        prompt="A courier looking for her missing brother.",
        template=None,
    )

    assert len(templates) == 4
    assert draft.name == "Custom Wanderer"
    assert draft.epithet == "A courier looking for her missing brother."
