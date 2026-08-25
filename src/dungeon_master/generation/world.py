from __future__ import annotations

import time
from collections.abc import Generator
from dataclasses import dataclass

from dungeon_master.cancel import CancellationToken
from dungeon_master.generation.contracts import (
    GENERATION_ERRORS,
    CampaignGenerationError,
    CampaignWorldResult,
    GeneratedCampaignWorld,
)
from dungeon_master.generation.direction import (
    render_creative_direction,
    render_danger_guidance,
)
from dungeon_master.models import CampaignSeed, CharacterSheet, GameState
from dungeon_master.narrative import (
    CompletionDelta,
    CompletionFunction,
    CompletionRequest,
    NarrativeConfig,
    _completion,
    complete_text,
    extract_json_object,
    iter_text_deltas,
)
from dungeon_master.prompt_fragments import JSON_ONLY_PERSIST, SEED_AUTHORITY

CAMPAIGN_SYSTEM_PROMPT = f"""You generate the initial world state for a solo TTRPG after the player
character has already been chosen.

{JSON_ONLY_PERSIST}

Creative direction:
- {SEED_AUTHORITY}
- The world must feel built around the supplied character, their gear, their
  drive, and their flaw while staying inside the seed.

Design constraints:
- Do not roll dice.
- Do not resolve any scene.
- Create content that can evolve through oracle prompts and later narration.
- Keep threads open-ended and playable.
- Oracle table entries should be evocative fragments, not full plot outcomes.
"""

CAMPAIGN_USER_PROMPT_TEMPLATE = """Create a fresh campaign opening as JSON with this shape:
{
  "current_scene": "one immediate opening scene, 1 sentence",
  "setting_notes": "dense setting bible seed, 2-4 sentences",
  "threads": [
    {"title": "open thread", "stakes": "what worsens if ignored"}
  ],
  "npcs": [
    {"name": "name", "role": "role", "disposition": "disposition"}
  ],
  "oracle_tables": {
    "event_focus": ["6-12 abstract focus phrases"],
    "event_actions": ["8-16 vivid verbs"],
    "event_tones": ["8-16 tonal adjectives"],
    "event_subjects": ["8-16 concrete subjects"]
  }
}

The finalized player character is:
<<CHARACTER_JSON>>

Return 1-3 threads and 0-3 NPCs. If more people matter, fold them into
`setting_notes` rather than adding extra `npcs` entries.
"""

MODEL_REQUIRED_MESSAGE = "Campaign generation requires a configured model."


def _campaign_generation_error(last_error: Exception | None) -> CampaignGenerationError:
    message = (
        f"{type(last_error).__name__}: {last_error!r}"
        if last_error is not None
        else "Campaign generation failed."
    )
    return CampaignGenerationError(message)


@dataclass(frozen=True)
class CampaignGenerator:
    config: NarrativeConfig
    completion_function: CompletionFunction = _completion

    @classmethod
    def from_env(cls) -> CampaignGenerator:
        return cls(config=NarrativeConfig.from_env())

    def generate(self, character: CharacterSheet, seed: CampaignSeed | None = None) -> GameState:
        return self.generate_result(character, seed=seed).state

    def generate_result(
        self,
        character: CharacterSheet,
        seed: CampaignSeed | None = None,
    ) -> CampaignWorldResult:
        campaign_seed = seed or CampaignSeed()
        if not self.config.is_usable():
            raise CampaignGenerationError(MODEL_REQUIRED_MESSAGE)

        campaign_profile = self.config.profiles.campaign_world
        user_prompt = (
            CAMPAIGN_USER_PROMPT_TEMPLATE.replace(
                "<<CHARACTER_JSON>>",
                character.model_dump_json(indent=2),
            )
            + "\n\nCreative direction:\n"
            + render_creative_direction(campaign_seed)
            + "\n\nDanger guidance:\n"
            + render_danger_guidance(campaign_seed.danger_profile)
        )
        request = CompletionRequest(
            model=self.config.model,
            messages=[
                {"role": "system", "content": CAMPAIGN_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            # Same Kimi K2.6 Thinking budget rationale as the character
            # generators above: this model always burns ~2-3k tokens
            # thinking regardless of `effort`, so the budget must leave
            # ample headroom for the JSON. We keep `high` here because
            # campaign generation is the one place where deeper reasoning
            # actually pays off — threads, NPCs, and oracle word banks
            # all benefit from cross-referencing the character.
            temperature=campaign_profile.temperature,
            max_tokens=campaign_profile.max_tokens,
            timeout=self.config.timeout_seconds,
            stream=True,
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            reasoning_effort=campaign_profile.reasoning_effort,
            reasoning=campaign_profile.reasoning(default_exclude=self.config.exclude_reasoning),
            extra_headers=self._openrouter_headers(),
            response_format=None,
            trace_route="campaign.world",
            trace_profile="campaign_world",
        )

        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                completed = complete_text(request, self.completion_function)
                if not completed.content:
                    raise CampaignGenerationError
                payload_json = extract_json_object(completed.content)
                generated = GeneratedCampaignWorld.model_validate_json(payload_json)
                state = generated.to_game_state(character)
                state.campaign_seed = campaign_seed
                return CampaignWorldResult(
                    state=state,
                    thinking=completed.thinking,
                )
            except GENERATION_ERRORS as exc:
                last_error = exc
                if attempt < self.config.max_retries:
                    time.sleep(0.4 * (attempt + 1))

        raise _campaign_generation_error(last_error) from last_error

    def iter_generate(
        self,
        character: CharacterSheet,
        *,
        seed: CampaignSeed | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CampaignWorldResult]:
        campaign_seed = seed or CampaignSeed()
        if not self.config.is_usable():
            raise CampaignGenerationError(MODEL_REQUIRED_MESSAGE)

        campaign_profile = self.config.profiles.campaign_world
        user_prompt = (
            CAMPAIGN_USER_PROMPT_TEMPLATE.replace(
                "<<CHARACTER_JSON>>",
                character.model_dump_json(indent=2),
            )
            + "\n\nCreative direction:\n"
            + render_creative_direction(campaign_seed)
            + "\n\nDanger guidance:\n"
            + render_danger_guidance(campaign_seed.danger_profile)
        )
        request = CompletionRequest(
            model=self.config.model,
            messages=[
                {"role": "system", "content": CAMPAIGN_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=campaign_profile.temperature,
            max_tokens=campaign_profile.max_tokens,
            timeout=self.config.timeout_seconds,
            stream=True,
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            reasoning_effort=campaign_profile.reasoning_effort,
            reasoning=campaign_profile.reasoning(default_exclude=self.config.exclude_reasoning),
            extra_headers=self._openrouter_headers(),
            response_format=None,
            cancel_token=cancel_token,
            trace_route="campaign.world",
            trace_profile="campaign_world",
        )

        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            content_parts: list[str] = []
            thinking_parts: list[str] = []
            try:
                for delta in iter_text_deltas(request, self.completion_function):
                    if delta.content:
                        content_parts.append(delta.content)
                    if delta.thinking:
                        thinking_parts.append(delta.thinking)
                    yield delta
                content = "".join(content_parts)
                if not content:
                    raise CampaignGenerationError
                generated = GeneratedCampaignWorld.model_validate_json(extract_json_object(content))
                state = generated.to_game_state(character)
                state.campaign_seed = campaign_seed
                return CampaignWorldResult(
                    state=state,
                    thinking="".join(thinking_parts).strip(),
                )
            except GENERATION_ERRORS as exc:
                last_error = exc
                if attempt < self.config.max_retries:
                    time.sleep(0.4 * (attempt + 1))

        raise _campaign_generation_error(last_error) from last_error

    def _openrouter_headers(self) -> dict[str, str] | None:
        if not self.config.model.startswith("openrouter/"):
            return None
        headers: dict[str, str] = {}
        if self.config.site_url is not None:
            headers["HTTP-Referer"] = self.config.site_url
        if self.config.app_name is not None:
            headers["X-Title"] = self.config.app_name
        return headers or None
