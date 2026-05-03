import json

from litellm.types.utils import ModelResponse

from dungeon_master.campaign import CampaignGenerator
from dungeon_master.narrative import CompletionRequest, NarrativeConfig
from tests.factories import sample_state


class CampaignCompletion:
    def __init__(self) -> None:
        self.request: CompletionRequest | None = None

    def __call__(self, request: CompletionRequest) -> ModelResponse:
        self.request = request
        payload = {
            "current_scene": "A generated opening scene.",
            "setting_notes": "Generated setting notes.",
            "threads": [
                {"title": "Thread one", "stakes": "Stakes one."},
                {"title": "Thread two", "stakes": "Stakes two."},
                {"title": "Thread three", "stakes": "Stakes three."},
            ],
            "npcs": [
                {"name": "NPC One", "role": "Role one", "disposition": "watchful"},
                {"name": "NPC Two", "role": "Role two", "disposition": "wary"},
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
        return ModelResponse(
            choices=[{"message": {"role": "assistant", "content": json.dumps(payload)}}],
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
    assert len(state.npcs) == 2
    assert state.oracle_tables.event_focus[0] == "thread pressure"
    assert completion.request is not None
    assert completion.request.response_format == {"type": "json_object"}
    assert completion.request.reasoning_effort == "high"
