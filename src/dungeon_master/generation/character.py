from __future__ import annotations

import json
import logging
import time
from collections.abc import Generator
from dataclasses import dataclass

from dungeon_master.cancel import CancellationToken
from dungeon_master.generation.character_fallbacks import (
    _fallback_draft,
    _fallback_quiz,
    _fallback_quizzed_draft,
    _fallback_templates,
    _format_interview,
    _setup_state,
)
from dungeon_master.generation.contracts import (
    GENERATION_ERRORS,
    CharacterDraftMode,
    CharacterDraftResult,
    CharacterGenerationError,
    CharacterQuizResult,
    CharacterTemplatesResult,
    GeneratedCharacter,
    GeneratedCharacterQuiz,
    GeneratedCharacterTemplates,
)
from dungeon_master.generation.direction import render_creative_direction
from dungeon_master.models import (
    CampaignSeed,
    CharacterQuiz,
    CharacterQuizAnswer,
    CharacterSheet,
    GameState,
)
from dungeon_master.narrative import (
    CompletionDelta,
    CompletionFunction,
    CompletionRequest,
    CompletionText,
    NarrativeConfig,
    _completion,
    complete_text,
    extract_json_object,
    iter_text_deltas,
)
from dungeon_master.prompt_fragments import JSON_ONLY, JSON_ONLY_PERSIST, SEED_AUTHORITY

logger = logging.getLogger(__name__)


CHARACTER_SYSTEM_PROMPT = f"""You generate player-character drafts for a solo TTRPG.

{JSON_ONLY_PERSIST}

Creative direction:
- {SEED_AUTHORITY}
<<CREATIVE_DIRECTION>>
- Characters must belong to the supplied setting, era, genre, magic level,
  technology level, and stakes.
- Treat the supplied creative direction as binding.
- Make them playable, pressured, and specific without deciding any future actions.

Design constraints:
- Do not roll dice.
- Do not generate the wider campaign, scene, or oracle tables here.
- Inventory should be concrete, limited, era-appropriate, and practically usable
  in play.
- Do not literalize every symbolic or biographical detail into carried gear.
- Prefer a practical starting bundle appropriate to the setting plus at most one
  or two signature biography-derived items.
"""

CHARACTER_TEMPLATES_USER_PROMPT = """Return JSON with this shape:
{
  "templates": [
    {
      "name": "short character name",
      "archetype": "setting-appropriate role",
      "epithet": "one-line identity pitch",
      "backstory": "2-4 sentence backstory",
      "drive": "what they want right now",
      "flaw": "how they are likely to fail",
      "condition": "immediate physical or spiritual state",
      "inventory": [
        {"name": "item", "details": "why it matters"}
      ]
    }
  ]
}

Return exactly 4 templates.
"""

DRAFT_SCRATCH_PROMPT = """Return JSON for one playable custom character with this shape:
{
  "name": "short character name",
  "archetype": "setting-appropriate role",
  "epithet": "one-line identity pitch",
  "backstory": "2-4 sentence backstory",
  "drive": "what they want right now",
  "flaw": "how they are likely to fail",
  "condition": "immediate physical or spiritual state",
  "inventory": [
    {"name": "item", "details": "why it matters"}
  ]
}

If the user prompt is sparse, fill the gaps with a plausible character who fits the campaign seed.
Return 3-6 practical inventory items.
Most biography should influence backstory, condition, flaw, and abilities rather than
becoming literal inventory objects.
"""

DRAFT_TEMPLATE_PROMPT = """Refine the provided template into a fuller editable draft.
Keep the archetype recognizable, sharpen the backstory, drive, flaw, and
inventory, and return the same JSON shape as above.

Inventory guidance:
- Choose a practical starting loadout that fits the archetype.
- At most one or two items should be directly biography-derived keepsakes or relics.
- Put symbolic or biographical flavor into backstory/condition more than gear.
"""

# Quiz path: the player gives a one-line concept, the LLM designs a
# personalized 4-6 question interview, the player answers, and ONLY THEN
# do we draft the character. The interview exists because a single
# free-text concept lets the LLM hide behind generic survivors; forcing
# specific committed answers makes the resulting draft impossible to
# write generically.
CHARACTER_QUIZ_SYSTEM_PROMPT = f"""You design a 4-6 question interview that helps a
player commit to a specific character for this campaign.

{JSON_ONLY}

Creative direction:
- {SEED_AUTHORITY}
<<CREATIVE_DIRECTION>>
- Treat the supplied creative direction as binding.

Question constraints:
- Every question must serve the player's stated character concept.
- Questions are short and answerable in one sentence.
- Ask about pressures that fit the campaign seed: relationships, obligations,
  habits, secrets, losses, responsibilities, fears, desires, and what the
  character keeps choosing despite the cost.
  Do not ask about combat stats, classes, or skill points.
- Each question gets 3-5 multiple-choice options. Each option is a
  one-line sentence the character could plausibly think or say.
- Do NOT include any "other" / "something else" / "write your own" option.
  The application appends that path itself; if you include it, it duplicates.
- Options must be specific, sensory, and grounded in the supplied concept.
"""

CHARACTER_QUIZ_USER_PROMPT_TEMPLATE = """Return JSON with this shape:
{
  "questions": [
    {
      "prompt": "one-line question, no preamble",
      "options": [
        {"label": "first concrete option, <=18 words"},
        {"label": "second concrete option"}
      ]
    }
  ]
}

Return between 4 and 6 questions. Each question must have 3 to 5 options.

The player's character concept:
<<CONCEPT>>

Treat that concept as fixed canon and generate questions that PRESSURE
the player into making the concept specific and consequential.
"""

DRAFT_FROM_QUIZ_PROMPT = """Return JSON for one playable custom character with this shape:
{
  "name": "short character name appropriate to the player's concept",
  "archetype": "setting-appropriate role consistent with the concept",
  "epithet": "one-line identity pitch grounded in the answers below",
  "backstory": "2-4 sentence backstory that uses the concrete details below",
  "drive": "what they want right now",
  "flaw": "how they are likely to fail",
  "condition": "immediate physical or spiritual state",
  "inventory": [
    {"name": "item", "details": "why it matters and which answer it traces to"}
  ]
}

Hard rules:
- Do NOT contradict any of the player's interview answers.
- Do NOT invent religion, geography, magic system, or culture details that
  conflict with the supplied concept (e.g. if the concept names a real-world
  religious or cultural tradition, honor it; do not generic-fantasy it).
- Let the interview answers primarily shape stats, condition, abilities, and flaw.
- Inventory should be a practical starting bundle that fits the character profile.
- At most one or two items may be directly biography-derived signature pieces.
- Do NOT convert every symbolic, bodily, or traumatic detail into a carried object.
- Return 3-6 inventory items.

Player concept:
<<CONCEPT>>

Player interview:
<<INTERVIEW>>

Final note from the player (optional, may be empty):
<<FINAL_NOTE>>

Campaign creative direction:
<<CREATIVE_DIRECTION>>
"""


@dataclass(frozen=True)
class CharacterGenerator:
    config: NarrativeConfig
    completion_function: CompletionFunction = _completion

    @classmethod
    def from_env(cls) -> CharacterGenerator:
        return cls(config=NarrativeConfig.from_env())

    def setup_state(self, seed: CampaignSeed | None = None) -> GameState:
        return _setup_state(configured=self.config.is_usable(), seed=seed or CampaignSeed())

    def generate_templates(self, seed: CampaignSeed | None = None) -> list[CharacterSheet]:
        return self.generate_templates_result(seed=seed).templates

    def generate_templates_result(
        self,
        seed: CampaignSeed | None = None,
    ) -> CharacterTemplatesResult:
        campaign_seed = seed or CampaignSeed()
        if not self.config.is_usable():
            return CharacterTemplatesResult(templates=_fallback_templates())

        # Why medium reasoning + 12000 max_tokens for character work:
        # Kimi K2.6 Thinking *always* burns 2-3k reasoning tokens
        # regardless of the requested `effort` (the "Thinking" variant
        # ignores low/medium settings to a large degree). On `high` it
        # regularly used the entire 2000-token budget thinking and
        # produced no content at all (finish_reason=length, content=None);
        # on `medium` it would generate JSON but truncate mid-string at
        # ~5-8k. Character creation does not need deep narrative
        # reasoning the way scene/event synthesis does, so we cap at
        # `medium`; the 12000 budget guarantees the JSON always closes
        # cleanly even after the model thinks aggressively.
        templates_profile = self.config.profiles.character_templates
        request = CompletionRequest(
            model=self.config.model,
            messages=[
                {
                    "role": "system",
                    "content": self._character_system_prompt(campaign_seed),
                },
                {"role": "user", "content": CHARACTER_TEMPLATES_USER_PROMPT},
            ],
            temperature=templates_profile.temperature,
            max_tokens=templates_profile.max_tokens,
            timeout=self.config.timeout_seconds,
            stream=True,
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            reasoning_effort=templates_profile.reasoning_effort,
            reasoning=templates_profile.reasoning(default_exclude=self.config.exclude_reasoning),
            extra_headers=self._openrouter_headers(),
            response_format=None,
            trace_route="character.templates",
            trace_profile="character_templates",
        )
        try:
            completed = self._complete_json(request)
            payload = completed.content
            parsed = GeneratedCharacterTemplates.model_validate_json(extract_json_object(payload))
            return CharacterTemplatesResult(
                templates=[template.to_character_sheet() for template in parsed.templates],
                thinking=completed.thinking,
            )
        except GENERATION_ERRORS:
            logger.exception("Character template generation fell back.")
            return CharacterTemplatesResult(templates=_fallback_templates())

    def iter_generate_templates(
        self,
        *,
        seed: CampaignSeed | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterTemplatesResult]:
        campaign_seed = seed or CampaignSeed()
        if not self.config.is_usable():
            fallback = CharacterTemplatesResult(templates=_fallback_templates())
            yield CompletionDelta(
                content=json.dumps(
                    {"templates": [template.model_dump() for template in fallback.templates]},
                ),
            )
            return fallback

        templates_profile = self.config.profiles.character_templates
        request = CompletionRequest(
            model=self.config.model,
            messages=[
                {
                    "role": "system",
                    "content": self._character_system_prompt(campaign_seed),
                },
                {"role": "user", "content": CHARACTER_TEMPLATES_USER_PROMPT},
            ],
            temperature=templates_profile.temperature,
            max_tokens=templates_profile.max_tokens,
            timeout=self.config.timeout_seconds,
            stream=True,
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            reasoning_effort=templates_profile.reasoning_effort,
            reasoning=templates_profile.reasoning(default_exclude=self.config.exclude_reasoning),
            extra_headers=self._openrouter_headers(),
            response_format=None,
            cancel_token=cancel_token,
            trace_route="character.templates",
            trace_profile="character_templates",
        )
        try:
            completed = yield from self._iter_json(request)
            payload_json = extract_json_object(completed.content)
            parsed = GeneratedCharacterTemplates.model_validate_json(payload_json)
            return CharacterTemplatesResult(
                templates=[template.to_character_sheet() for template in parsed.templates],
                thinking=completed.thinking,
            )
        except GENERATION_ERRORS:
            logger.exception("Character template generation fell back.")
            fallback = CharacterTemplatesResult(templates=_fallback_templates())
            yield CompletionDelta(
                content=json.dumps(
                    {"templates": [template.model_dump() for template in fallback.templates]},
                ),
            )
            return fallback

    def _character_system_prompt(self, seed: CampaignSeed) -> str:
        return CHARACTER_SYSTEM_PROMPT.replace(
            "<<CREATIVE_DIRECTION>>",
            render_creative_direction(seed),
        )

    def _character_quiz_system_prompt(self, seed: CampaignSeed) -> str:
        return CHARACTER_QUIZ_SYSTEM_PROMPT.replace(
            "<<CREATIVE_DIRECTION>>",
            render_creative_direction(seed),
        )

    def generate_quiz(self, concept: str, seed: CampaignSeed | None = None) -> CharacterQuiz:
        return self.generate_quiz_result(concept, seed=seed).quiz

    def generate_quiz_result(
        self,
        concept: str,
        seed: CampaignSeed | None = None,
    ) -> CharacterQuizResult:
        """Produce an interview tailored to the player's concept.

        On any LLM failure we return the static fallback quiz so the
        player can still proceed, but we log loud enough that the
        backend operator can see why their concept didn't customize.
        """
        cleaned = concept.strip()
        if not cleaned or not self.config.is_usable():
            return CharacterQuizResult(quiz=_fallback_quiz(cleaned or "An unspecified survivor."))

        campaign_seed = seed or CampaignSeed()
        user_prompt = CHARACTER_QUIZ_USER_PROMPT_TEMPLATE.replace("<<CONCEPT>>", cleaned)
        # Quiz generation is structured authoring (fixed JSON shape,
        # short one-line strings). See `generate_templates` above for
        # why we cap reasoning and use a 12000-token budget — Kimi
        # K2.6 Thinking does not actually obey low/medium reasoning
        # caps, so the budget must absorb its always-on thinking
        # without leaving the JSON truncated.
        quiz_profile = self.config.profiles.character_quiz
        request = CompletionRequest(
            model=self.config.model,
            messages=[
                {
                    "role": "system",
                    "content": self._character_quiz_system_prompt(campaign_seed),
                },
                {"role": "user", "content": user_prompt},
            ],
            temperature=quiz_profile.temperature,
            max_tokens=quiz_profile.max_tokens,
            timeout=self.config.timeout_seconds,
            stream=True,
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            reasoning_effort=quiz_profile.reasoning_effort,
            reasoning=quiz_profile.reasoning(default_exclude=self.config.exclude_reasoning),
            extra_headers=self._openrouter_headers(),
            response_format=None,
            trace_route="character.quiz",
            trace_profile="character_quiz",
        )
        try:
            completed = self._complete_json(request)
            payload_json = extract_json_object(completed.content)
            quiz = GeneratedCharacterQuiz.model_validate_json(payload_json).to_quiz(cleaned)
            return CharacterQuizResult(quiz=quiz, thinking=completed.thinking)
        except GENERATION_ERRORS:
            logger.exception("Character quiz generation fell back to static questions.")
            return CharacterQuizResult(quiz=_fallback_quiz(cleaned))

    def iter_generate_quiz(
        self,
        concept: str,
        *,
        seed: CampaignSeed | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterQuizResult]:
        cleaned = concept.strip()
        if not cleaned or not self.config.is_usable():
            fallback = CharacterQuizResult(
                quiz=_fallback_quiz(cleaned or "An unspecified survivor."),
            )
            yield CompletionDelta(content=json.dumps({"quiz": fallback.quiz.model_dump()}))
            return fallback

        campaign_seed = seed or CampaignSeed()
        user_prompt = CHARACTER_QUIZ_USER_PROMPT_TEMPLATE.replace("<<CONCEPT>>", cleaned)
        quiz_profile = self.config.profiles.character_quiz
        request = CompletionRequest(
            model=self.config.model,
            messages=[
                {
                    "role": "system",
                    "content": self._character_quiz_system_prompt(campaign_seed),
                },
                {"role": "user", "content": user_prompt},
            ],
            temperature=quiz_profile.temperature,
            max_tokens=quiz_profile.max_tokens,
            timeout=self.config.timeout_seconds,
            stream=True,
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            reasoning_effort=quiz_profile.reasoning_effort,
            reasoning=quiz_profile.reasoning(default_exclude=self.config.exclude_reasoning),
            extra_headers=self._openrouter_headers(),
            response_format=None,
            cancel_token=cancel_token,
            trace_route="character.quiz",
            trace_profile="character_quiz",
        )
        try:
            completed = yield from self._iter_json(request)
            payload_json = extract_json_object(completed.content)
            quiz = GeneratedCharacterQuiz.model_validate_json(payload_json).to_quiz(cleaned)
            return CharacterQuizResult(quiz=quiz, thinking=completed.thinking)
        except GENERATION_ERRORS:
            logger.exception("Character quiz generation fell back to static questions.")
            fallback = CharacterQuizResult(quiz=_fallback_quiz(cleaned))
            yield CompletionDelta(content=json.dumps({"quiz": fallback.quiz.model_dump()}))
            return fallback

    def generate_quizzed_draft(
        self,
        *,
        concept: str,
        answers: list[CharacterQuizAnswer],
        final_note: str | None,
        seed: CampaignSeed | None = None,
    ) -> CharacterSheet:
        return self.generate_quizzed_draft_result(
            concept=concept,
            answers=answers,
            final_note=final_note,
            seed=seed,
        ).draft

    def generate_quizzed_draft_result(
        self,
        *,
        concept: str,
        answers: list[CharacterQuizAnswer],
        final_note: str | None,
        seed: CampaignSeed | None = None,
    ) -> CharacterDraftResult:
        """Draft a character using the concept + interview answers.

        This is the one-shot path the assist UI uses after the quiz.
        Concept and answers together give the LLM enough specificity
        that the resulting JSON should be tightly tailored.
        """
        cleaned_concept = concept.strip() or "An unspecified survivor."
        cleaned_note = (final_note or "").strip()

        if not self.config.is_usable():
            return CharacterDraftResult(
                draft=_fallback_quizzed_draft(
                    concept=cleaned_concept,
                    answers=answers,
                    final_note=cleaned_note,
                ),
            )

        interview_block = _format_interview(answers)
        campaign_seed = seed or CampaignSeed()
        user_prompt = (
            DRAFT_FROM_QUIZ_PROMPT.replace("<<CONCEPT>>", cleaned_concept)
            .replace("<<INTERVIEW>>", interview_block)
            .replace("<<FINAL_NOTE>>", cleaned_note or "(none)")
            .replace("<<CREATIVE_DIRECTION>>", render_creative_direction(campaign_seed))
        )
        # Drafting from a quiz benefits more from creativity than from
        # reasoning depth, and the answers already supply most of the
        # specificity. Medium reasoning + generous max_tokens. See the
        # `generate_quiz` and `generate_templates` notes on why we never
        # use `high` here — the model's thinking starves the actual JSON.
        quizzed_draft_profile = self.config.profiles.quizzed_character_draft
        request = CompletionRequest(
            model=self.config.model,
            messages=[
                {"role": "system", "content": self._character_system_prompt(campaign_seed)},
                {"role": "user", "content": user_prompt},
            ],
            temperature=quizzed_draft_profile.temperature,
            max_tokens=quizzed_draft_profile.max_tokens,
            timeout=self.config.timeout_seconds,
            stream=True,
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            reasoning_effort=quizzed_draft_profile.reasoning_effort,
            reasoning=quizzed_draft_profile.reasoning(
                default_exclude=self.config.exclude_reasoning,
            ),
            extra_headers=self._openrouter_headers(),
            response_format=None,
            trace_route="character.draft.quizzed",
            trace_profile="quizzed_character_draft",
        )
        try:
            completed = self._complete_json(request)
            payload_json = extract_json_object(completed.content)
            draft = GeneratedCharacter.model_validate_json(payload_json).to_character_sheet()
            return CharacterDraftResult(draft=draft, thinking=completed.thinking)
        except GENERATION_ERRORS:
            logger.exception("Quizzed draft generation fell back.")
            return CharacterDraftResult(
                draft=_fallback_quizzed_draft(
                    concept=cleaned_concept,
                    answers=answers,
                    final_note=cleaned_note,
                ),
            )

    def iter_generate_quizzed_draft(
        self,
        *,
        concept: str,
        answers: list[CharacterQuizAnswer],
        final_note: str | None,
        cancel_token: CancellationToken | None = None,
        seed: CampaignSeed | None = None,
    ) -> Generator[CompletionDelta, None, CharacterDraftResult]:
        cleaned_concept = concept.strip() or "An unspecified survivor."
        cleaned_note = (final_note or "").strip()
        if not self.config.is_usable():
            fallback = CharacterDraftResult(
                draft=_fallback_quizzed_draft(
                    concept=cleaned_concept,
                    answers=answers,
                    final_note=cleaned_note,
                ),
            )
            yield CompletionDelta(content=fallback.draft.model_dump_json())
            return fallback

        interview_block = _format_interview(answers)
        campaign_seed = seed or CampaignSeed()
        user_prompt = (
            DRAFT_FROM_QUIZ_PROMPT.replace("<<CONCEPT>>", cleaned_concept)
            .replace("<<INTERVIEW>>", interview_block)
            .replace("<<FINAL_NOTE>>", cleaned_note or "(none)")
            .replace("<<CREATIVE_DIRECTION>>", render_creative_direction(campaign_seed))
        )
        quizzed_draft_profile = self.config.profiles.quizzed_character_draft
        request = CompletionRequest(
            model=self.config.model,
            messages=[
                {"role": "system", "content": self._character_system_prompt(campaign_seed)},
                {"role": "user", "content": user_prompt},
            ],
            temperature=quizzed_draft_profile.temperature,
            max_tokens=quizzed_draft_profile.max_tokens,
            timeout=self.config.timeout_seconds,
            stream=True,
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            reasoning_effort=quizzed_draft_profile.reasoning_effort,
            reasoning=quizzed_draft_profile.reasoning(
                default_exclude=self.config.exclude_reasoning,
            ),
            extra_headers=self._openrouter_headers(),
            response_format=None,
            cancel_token=cancel_token,
            trace_route="character.draft.quizzed",
            trace_profile="quizzed_character_draft",
        )
        try:
            completed = yield from self._iter_json(request)
            payload_json = extract_json_object(completed.content)
            draft = GeneratedCharacter.model_validate_json(payload_json).to_character_sheet()
            return CharacterDraftResult(draft=draft, thinking=completed.thinking)
        except GENERATION_ERRORS:
            logger.exception("Quizzed draft generation fell back.")
            fallback = CharacterDraftResult(
                draft=_fallback_quizzed_draft(
                    concept=cleaned_concept,
                    answers=answers,
                    final_note=cleaned_note,
                ),
            )
            yield CompletionDelta(content=fallback.draft.model_dump_json())
            return fallback

    def generate_draft(
        self,
        *,
        mode: CharacterDraftMode,
        prompt: str | None,
        template: CharacterSheet | None,
        seed: CampaignSeed | None = None,
    ) -> CharacterSheet:
        return self.generate_draft_result(
            mode=mode,
            prompt=prompt,
            template=template,
            seed=seed,
        ).draft

    def generate_draft_result(
        self,
        *,
        mode: CharacterDraftMode,
        prompt: str | None,
        template: CharacterSheet | None,
        seed: CampaignSeed | None = None,
    ) -> CharacterDraftResult:
        if not self.config.is_usable():
            return CharacterDraftResult(
                draft=_fallback_draft(mode=mode, prompt=prompt, template=template),
            )

        template_json = (
            template.model_dump_json(indent=2) if template is not None else "No template provided."
        )
        campaign_seed = seed or CampaignSeed()
        user_prompt = (
            f"{DRAFT_SCRATCH_PROMPT}\n\nUser prompt:\n{prompt or 'No extra guidance supplied.'}"
            if mode == CharacterDraftMode.SCRATCH
            else (
                f"{DRAFT_TEMPLATE_PROMPT}\n\nTemplate JSON:\n"
                f"{template_json}\n\n"
                f"Extra guidance:\n{prompt or 'None.'}"
            )
        )
        # See `generate_templates` for the medium-reasoning rationale.
        draft_profile = self.config.profiles.character_draft
        request = CompletionRequest(
            model=self.config.model,
            messages=[
                {"role": "system", "content": self._character_system_prompt(campaign_seed)},
                {"role": "user", "content": user_prompt},
            ],
            temperature=draft_profile.temperature,
            max_tokens=draft_profile.max_tokens,
            timeout=self.config.timeout_seconds,
            stream=True,
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            reasoning_effort=draft_profile.reasoning_effort,
            reasoning=draft_profile.reasoning(default_exclude=self.config.exclude_reasoning),
            extra_headers=self._openrouter_headers(),
            response_format=None,
            trace_route="character.draft",
            trace_profile="character_draft",
        )
        try:
            completed = self._complete_json(request)
            payload_json = extract_json_object(completed.content)
            draft = GeneratedCharacter.model_validate_json(payload_json).to_character_sheet()
            return CharacterDraftResult(draft=draft, thinking=completed.thinking)
        except GENERATION_ERRORS:
            logger.exception("Character draft generation fell back.")
            return CharacterDraftResult(
                draft=_fallback_draft(mode=mode, prompt=prompt, template=template),
            )

    def iter_generate_draft(
        self,
        *,
        mode: CharacterDraftMode,
        prompt: str | None,
        template: CharacterSheet | None,
        seed: CampaignSeed | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterDraftResult]:
        if not self.config.is_usable():
            fallback = CharacterDraftResult(
                draft=_fallback_draft(mode=mode, prompt=prompt, template=template),
            )
            yield CompletionDelta(content=fallback.draft.model_dump_json())
            return fallback

        template_json = (
            template.model_dump_json(indent=2) if template is not None else "No template provided."
        )
        campaign_seed = seed or CampaignSeed()
        user_prompt = (
            f"{DRAFT_SCRATCH_PROMPT}\n\nUser prompt:\n{prompt or 'No extra guidance supplied.'}"
            if mode == CharacterDraftMode.SCRATCH
            else (
                f"{DRAFT_TEMPLATE_PROMPT}\n\nTemplate JSON:\n"
                f"{template_json}\n\n"
                f"Extra guidance:\n{prompt or 'None.'}"
            )
        )
        draft_profile = self.config.profiles.character_draft
        request = CompletionRequest(
            model=self.config.model,
            messages=[
                {"role": "system", "content": self._character_system_prompt(campaign_seed)},
                {"role": "user", "content": user_prompt},
            ],
            temperature=draft_profile.temperature,
            max_tokens=draft_profile.max_tokens,
            timeout=self.config.timeout_seconds,
            stream=True,
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            reasoning_effort=draft_profile.reasoning_effort,
            reasoning=draft_profile.reasoning(default_exclude=self.config.exclude_reasoning),
            extra_headers=self._openrouter_headers(),
            response_format=None,
            cancel_token=cancel_token,
            trace_route="character.draft",
            trace_profile="character_draft",
        )
        try:
            completed = yield from self._iter_json(request)
            payload_json = extract_json_object(completed.content)
            draft = GeneratedCharacter.model_validate_json(payload_json).to_character_sheet()
            return CharacterDraftResult(draft=draft, thinking=completed.thinking)
        except GENERATION_ERRORS:
            logger.exception("Character draft generation fell back.")
            fallback = CharacterDraftResult(
                draft=_fallback_draft(mode=mode, prompt=prompt, template=template),
            )
            yield CompletionDelta(content=fallback.draft.model_dump_json())
            return fallback

    def _complete_json(self, request: CompletionRequest) -> CompletionText:
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                completed = complete_text(request, self.completion_function)
                if not completed.content:
                    raise CharacterGenerationError
            except GENERATION_ERRORS as exc:
                last_error = exc
                if attempt < self.config.max_retries:
                    time.sleep(0.4 * (attempt + 1))
            else:
                return completed
        # Chain via `from last_error` so the surrounding logger.exception
        # call captures the underlying LiteLLM/Pydantic exception. Without
        # this the chain is lost when the last error type is one that
        # carries an empty `str()` (some litellm exceptions do that and
        # only reveal context in their `__cause__`/repr).
        message = (
            f"{type(last_error).__name__}: {last_error!r}"
            if last_error is not None
            else "Character generation failed."
        )
        raise CharacterGenerationError(message) from last_error

    def _iter_json(
        self,
        request: CompletionRequest,
    ) -> Generator[CompletionDelta, None, CompletionText]:
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
                    raise CharacterGenerationError
                return CompletionText(
                    content=content,
                    thinking="".join(thinking_parts).strip(),
                )
            except GENERATION_ERRORS as exc:
                last_error = exc
                if attempt < self.config.max_retries:
                    time.sleep(0.4 * (attempt + 1))

        message = (
            f"{type(last_error).__name__}: {last_error!r}"
            if last_error is not None
            else "Character generation failed."
        )
        raise CharacterGenerationError(message) from last_error

    def _openrouter_headers(self) -> dict[str, str] | None:
        if not self.config.model.startswith("openrouter/"):
            return None
        headers: dict[str, str] = {}
        if self.config.site_url is not None:
            headers["HTTP-Referer"] = self.config.site_url
        if self.config.app_name is not None:
            headers["X-Title"] = self.config.app_name
        return headers or None
