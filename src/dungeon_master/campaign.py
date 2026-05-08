from __future__ import annotations

import json
import logging
import time
from collections.abc import Generator
from dataclasses import dataclass
from enum import StrEnum

from pydantic import Field, ValidationError

from dungeon_master.cancel import CancellationToken
from dungeon_master.models import (
    NPC,
    CampaignStatus,
    CharacterQuiz,
    CharacterQuizAnswer,
    CharacterQuizOption,
    CharacterQuizQuestion,
    CharacterSheet,
    GameState,
    GameThread,
    InventoryItem,
    OracleTables,
    StrictModel,
)
from dungeon_master.narrative import (
    LITELLM_RETRYABLE_ERRORS,
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

logger = logging.getLogger(__name__)

SETTING_DIRECTION = """Oppressive medieval dark fantasy, adjacent to Berserk, Dark Souls,
and Fear & Hunger. No copied characters, locations, factions, or lore.
Avoid heroic power fantasy, modern slang, cozy safety, and generic tavern openings."""

CHARACTER_SYSTEM_PROMPT = f"""You generate player-character drafts for a solo dark-fantasy TTRPG.

Return only valid JSON. The application will persist your JSON as structured state.

Creative direction:
- {SETTING_DIRECTION}
- Characters must be archetypal to this setting: including but not limited to
  scarred pilgrims, failed squires,
  gutter mystics, plague-haunted hunters, relic smugglers, deserters, grave-robbers,
  and other desperate medieval survivors.
- Make them playable, pressured, and specific without deciding any future actions.

Design constraints:
- Do not roll dice.
- Do not generate the wider campaign, scene, or oracle tables here.
- Inventory should be concrete, grimy, limited, and practically usable in play.
- Do not literalize every body-horror or biographical detail into carried gear.
- Prefer a practical starting bundle (weapon, clothing/armor, light, supplies, tools)
  plus at most one or two signature biography-derived items.
"""

CHARACTER_TEMPLATES_USER_PROMPT = """Return JSON with this shape:
{
  "templates": [
    {
      "name": "short character name",
      "archetype": "archetypal dark-fantasy role",
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
  "archetype": "archetypal dark-fantasy role",
  "epithet": "one-line identity pitch",
  "backstory": "2-4 sentence backstory",
  "drive": "what they want right now",
  "flaw": "how they are likely to fail",
  "condition": "immediate physical or spiritual state",
  "inventory": [
    {"name": "item", "details": "why it matters"}
  ]
}

If the user prompt is sparse, fill the gaps with a plausible archetypal survivor.
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
- Put grotesque or symbolic flavor into backstory/condition more than gear.
"""

# Quiz path: the player gives a one-line concept, the LLM designs a
# personalized 4-6 question interview, the player answers, and ONLY THEN
# do we draft the character. The interview exists because a single
# free-text concept lets the LLM hide behind generic survivors; forcing
# specific committed answers makes the resulting draft impossible to
# write generically.
CHARACTER_QUIZ_SYSTEM_PROMPT = f"""You design a 4-6 question interview that helps a
player commit to a specific dark-fantasy character.

Return only valid JSON.

Setting:
- {SETTING_DIRECTION}

Question constraints:
- Every question must serve the player's stated character concept.
- Questions are short and answerable in one sentence.
- Ideas: The body / condition, what was lost or done, what is carried,
  who or what is hunting them, and what sin they keep committing.
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
  "archetype": "archetypal dark-fantasy role consistent with the concept",
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
"""

CAMPAIGN_SYSTEM_PROMPT = """You generate the initial world state for a solo TTRPG after the player
character has already been chosen.

Return only valid JSON. The application will persist your JSON as state, so be specific.

Creative direction:
- Oppressive medieval dark fantasy, with a mood adjacent to Berserk, Dark Souls, and Fear & Hunger.
- No copied characters, named locations, factions, or lore from those works.
- Avoid heroic power fantasy, modern slang, cozy safety, and generic tavern openings.
- The world must feel built around the supplied character, their gear, their drive, and their flaw.

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

Return 1-3 threads and as many NPCs to fit the story as needed.
"""


class CharacterDraftMode(StrEnum):
    SCRATCH = "scratch"
    TEMPLATE = "template"


class GeneratedThread(StrictModel):
    title: str = Field(min_length=1)
    stakes: str = Field(min_length=1)


class GeneratedNPC(StrictModel):
    name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    disposition: str = Field(min_length=1)


class GeneratedInventoryItem(StrictModel):
    name: str = Field(min_length=1)
    details: str = Field(min_length=1)


class GeneratedCharacter(StrictModel):
    name: str = Field(min_length=1)
    archetype: str = Field(min_length=1)
    epithet: str = Field(min_length=1)
    backstory: str = Field(min_length=1)
    drive: str = Field(min_length=1)
    flaw: str = Field(min_length=1)
    condition: str = Field(min_length=1)
    inventory: list[GeneratedInventoryItem] = Field(min_length=2, max_length=6)

    def to_character_sheet(self) -> CharacterSheet:
        return CharacterSheet(
            name=self.name,
            archetype=self.archetype,
            epithet=self.epithet,
            backstory=self.backstory,
            drive=self.drive,
            flaw=self.flaw,
            condition=self.condition,
            inventory=[
                InventoryItem(name=item.name, details=item.details) for item in self.inventory
            ],
        )


class GeneratedCharacterTemplates(StrictModel):
    templates: list[GeneratedCharacter] = Field(min_length=4, max_length=4)


class GeneratedQuizOption(StrictModel):
    label: str = Field(min_length=1)


class GeneratedQuizQuestion(StrictModel):
    prompt: str = Field(min_length=1)
    options: list[GeneratedQuizOption] = Field(min_length=2, max_length=6)


class GeneratedCharacterQuiz(StrictModel):
    questions: list[GeneratedQuizQuestion] = Field(min_length=3, max_length=6)

    def to_quiz(self, concept: str) -> CharacterQuiz:
        return CharacterQuiz(
            concept=concept,
            questions=[
                CharacterQuizQuestion(
                    prompt=question.prompt,
                    options=[
                        CharacterQuizOption(label=option.label) for option in question.options
                    ],
                )
                for question in self.questions
            ],
        )


@dataclass(frozen=True)
class CharacterTemplatesResult:
    templates: list[CharacterSheet]
    thinking: str = ""


@dataclass(frozen=True)
class CharacterQuizResult:
    quiz: CharacterQuiz
    thinking: str = ""


@dataclass(frozen=True)
class CharacterDraftResult:
    draft: CharacterSheet
    thinking: str = ""


@dataclass(frozen=True)
class CampaignWorldResult:
    state: GameState
    thinking: str = ""


class GeneratedCampaignWorld(StrictModel):
    current_scene: str = Field(min_length=1)
    setting_notes: str = Field(min_length=1)
    threads: list[GeneratedThread] = Field(min_length=3, max_length=3)
    npcs: list[GeneratedNPC] = Field(min_length=2, max_length=2)
    oracle_tables: OracleTables

    def to_game_state(self, character: CharacterSheet) -> GameState:
        return GameState(
            current_scene=self.current_scene,
            setting_notes=self.setting_notes,
            player_notes=character.backstory,
            npc_roster_version=2,
            character=character,
            campaign_status=CampaignStatus.ACTIVE,
            threads=[
                GameThread(title=thread.title, stakes=thread.stakes) for thread in self.threads
            ],
            hidden_npcs=[
                NPC(name=npc.name, role=npc.role, disposition=npc.disposition)
                for npc in self.npcs
            ],
            oracle_tables=self.oracle_tables,
        )


class CharacterGenerationError(ValueError):
    pass


class CampaignGenerationError(ValueError):
    pass


GENERATION_ERRORS = (
    CharacterGenerationError,
    CampaignGenerationError,
    ValidationError,
    json.JSONDecodeError,
    *LITELLM_RETRYABLE_ERRORS,
)


def _placeholder_tables() -> OracleTables:
    return OracleTables(
        event_focus=[
            "the price of survival",
            "an inherited burden",
            "a path gone wrong",
            "a relic with a will",
            "a witness to blasphemy",
            "the shape of hunger",
        ],
        event_actions=[
            "beg",
            "bleed",
            "conceal",
            "drag",
            "excavate",
            "forsake",
            "guard",
            "stain",
        ],
        event_tones=[
            "bitter",
            "cold",
            "drowned",
            "foul",
            "hollow",
            "ruined",
            "solemn",
            "starving",
        ],
        event_subjects=[
            "a bell",
            "a debt",
            "a gate",
            "a hand",
            "a relic",
            "a road",
            "a wound",
            "old blood",
        ],
    )


def _fallback_templates() -> list[CharacterSheet]:
    return [
        CharacterSheet(
            name="Mara of the Ash Steps",
            archetype="Relic smuggler",
            epithet="A runner who learned to hide sacred things inside profane cargo.",
            backstory=(
                "You carried condemned relics through quarantine roads for men too holy "
                "to be seen touching them. When the last convoy was butchered, you kept "
                "the route-marks, the debt, and the habit of sleeping with one eye open."
            ),
            drive="Sell or consecrate the relic before its owners catch up.",
            flaw="Trusts bargains more than people.",
            condition="Slept badly, left shoulder inflamed from an old pike wound.",
            inventory=[
                InventoryItem(name="Wax-wrapped reliquary", details="Valuable, cursed, or both."),
                InventoryItem(name="Bone-handled knife", details="Short, quiet, serviceable."),
                InventoryItem(name="Pilgrim's satchel", details="Smells of pitch and damp linen."),
            ],
        ),
        CharacterSheet(
            name="Brother Cenn",
            archetype="Failed monastic healer",
            epithet="A novice who learned surgery from plague pits instead of saints.",
            backstory=(
                "You were meant to preserve the dying long enough for absolution, but "
                "the abbey ran out of both mercy and clean cloth. The order cast you out "
                "with your saw and your shame when the wrong corpse sat up."
            ),
            drive="Reach holy ground before the thing you awakened reaches you.",
            flaw="Believes every wound can still be corrected by his hand.",
            condition="Feverish, overcaffeinated on bitter herb-water, knuckles cracked.",
            inventory=[
                InventoryItem(
                    name="Anatomical saw",
                    details="Cleaned often, never clean.",
                ),
                InventoryItem(
                    name="Roll of stained bandages",
                    details="Half medicine, half superstition.",
                ),
                InventoryItem(
                    name="Prayer book missing pages",
                    details="The omissions matter.",
                ),
            ],
        ),
        CharacterSheet(
            name="Ives Red-Mask",
            archetype="Deserter scout",
            epithet="A fugitive outrider who knows which roads remember blood.",
            backstory=(
                "You ran when the bone-grinders stopped and the officers began feeding "
                "men into their own engines to keep the line moving. Since then you have "
                "lived by mapping bad terrain and leaving before the carrion birds settle."
            ),
            drive="Cross the frontier before military debt is converted into holy debt.",
            flaw="Leaves too early and abandons allies before certainty exists.",
            condition="Underslept, wind-burned, right knee unstable on descents.",
            inventory=[
                InventoryItem(
                    name="Rusted short spear",
                    details="Balanced well enough for one throw.",
                ),
                InventoryItem(
                    name="Storm-dark cloak",
                    details="Keeps the silhouette human-shaped.",
                ),
                InventoryItem(
                    name="Charcoal route scraps",
                    details="Only you can read them quickly.",
                ),
            ],
        ),
        CharacterSheet(
            name="Yselle",
            archetype="Gutter mystic",
            epithet="A back-alley visionary who confuses revelation with infection.",
            backstory=(
                "People used to pay for your visions until too many of them came true "
                "with teeth in them. Now you travel because staying anywhere long enough "
                "to be believed is worse than starving on the road."
            ),
            drive="Find the source of the voice that has started finishing your prayers.",
            flaw="Mistakes dread for destiny.",
            condition="Shaking from fasting, pupils blown wide by sleepless visions.",
            inventory=[
                InventoryItem(
                    name="Tallow shrine-kit",
                    details="Candles, nails, and threadbare icons.",
                ),
                InventoryItem(
                    name="Jar of black salt",
                    details="For thresholds and panic.",
                ),
                InventoryItem(
                    name="Cracked bell",
                    details="Rings without being struck on bad nights.",
                ),
            ],
        ),
    ]


def _fallback_quiz(concept: str) -> CharacterQuiz:
    """Build the static interview, used only when the LLM is not configured.

    Phrased generically because the whole point of the LLM path is to
    tailor the questions to the concept. If we ever lean on this, the
    answers should still be playable signal for `_fallback_draft`.
    """
    return CharacterQuiz(
        concept=concept,
        questions=[
            CharacterQuizQuestion(
                prompt="What does your body carry into the first scene?",
                options=[
                    CharacterQuizOption(label="A wound someone refused to dress."),
                    CharacterQuizOption(label="A festering thing you cannot show."),
                    CharacterQuizOption(label="An old discipline that survived your faith."),
                    CharacterQuizOption(label="Hunger that has stopped feeling like hunger."),
                ],
            ),
            CharacterQuizQuestion(
                prompt="What did you take from the place that broke you?",
                options=[
                    CharacterQuizOption(label="A relic you should not be holding."),
                    CharacterQuizOption(label="A name you can no longer say aloud."),
                    CharacterQuizOption(label="A debt written into your skin."),
                    CharacterQuizOption(label="Only the road, and the habit of leaving."),
                ],
            ),
            CharacterQuizQuestion(
                prompt="Who is still looking for you?",
                options=[
                    CharacterQuizOption(label="An order that does not forgive desertion."),
                    CharacterQuizOption(label="Something dead that finishes your prayers."),
                    CharacterQuizOption(label="A creditor with a writ and no patience."),
                    CharacterQuizOption(label="Family who no longer recognize the word mercy."),
                ],
            ),
            CharacterQuizQuestion(
                prompt="What sin will you not stop committing?",
                options=[
                    CharacterQuizOption(label="Mercy at the wrong moment."),
                    CharacterQuizOption(label="Bargains with things that do not honor them."),
                    CharacterQuizOption(label="Hope, which keeps you stupid."),
                    CharacterQuizOption(label="Theft, which keeps you fed."),
                ],
            ),
        ],
    )


def _format_interview(answers: list[CharacterQuizAnswer]) -> str:
    """Render quiz answers as a tight Q/A block for the draft prompt."""
    if not answers:
        return "(none — the player skipped the interview)"
    lines: list[str] = []
    for index, answer in enumerate(answers, start=1):
        marker = " (player wrote their own)" if answer.is_other else ""
        lines.append(f"Q{index}: {answer.prompt}")
        lines.append(f"A{index}{marker}: {answer.value}")
    return "\n".join(lines)


def _fallback_draft(
    *,
    mode: CharacterDraftMode,
    prompt: str | None,
    template: CharacterSheet | None,
) -> CharacterSheet:
    if template is not None:
        return template.model_copy(deep=True)

    prompt_text = (prompt or "").strip()
    if mode == CharacterDraftMode.SCRATCH and prompt_text:
        return CharacterSheet(
            name="Custom Wanderer",
            archetype="Player-defined survivor",
            epithet=prompt_text,
            backstory=prompt_text,
            drive="Turn a scrap of intent into a survivable life.",
            flaw="Undefined edges hide danger.",
            condition="Unproven, unsteady, still becoming.",
            inventory=[
                InventoryItem(name="Travel rags", details="Enough to count as clothing."),
                InventoryItem(name="Makeshift tool", details="Useful until it breaks."),
            ],
        )

    return CharacterSheet(
        name="Unnamed wanderer",
        archetype="Player-defined survivor",
        epithet="A figure not yet pinned down by the world's cruelty.",
        backstory="You have not committed the whole story yet.",
        drive="Survive long enough to become specific.",
        flaw="Too unfinished to trust your own instincts.",
        condition="Unrecorded.",
        inventory=[
            InventoryItem(name="Poor bundle", details="Everything not yet decided."),
            InventoryItem(name="Walking staff", details="Tool, crutch, warning."),
        ],
    )


def _fallback_quizzed_draft(
    *,
    concept: str,
    answers: list[CharacterQuizAnswer],
    final_note: str | None,
) -> CharacterSheet:
    """Synthesize a draft from raw answers when the LLM call fails.

    The draft is intentionally honest about being unedited so the player
    realizes they should rewrite it before finalizing — silently producing
    polished-looking fiction here was the bug that motivated the warning
    surfaced from `CharacterGenerator.generate_quizzed_draft`.
    """
    # Magic indices: the assist quiz asks about condition, drive, then later
    # the recurring sin (flaw) in roughly that order, so we map answers
    # positionally when we cannot ask the LLM to weave them in. These are
    # local conventions for the fallback only, not protocol.
    drive_index = 1
    flaw_index = 3

    interview = _format_interview(answers) if answers else ""
    backstory_parts = [concept.strip(), interview, (final_note or "").strip()]
    backstory = "\n\n".join(part for part in backstory_parts if part)
    drive = (
        answers[drive_index].value
        if len(answers) > drive_index
        else "Pin the concept to a survivable life."
    )
    flaw = (
        answers[flaw_index].value
        if len(answers) > flaw_index
        else "Pulled toward the same mistake."
    )
    condition = answers[0].value if answers else "Marked by what has happened so far."
    return CharacterSheet(
        name="Unnamed wanderer",
        archetype="Player-defined survivor",
        epithet=concept[:160] or "A figure shaped by the answers above.",
        backstory=backstory or concept,
        drive=drive,
        flaw=flaw,
        condition=condition,
        inventory=[
            InventoryItem(
                name="Carried from the answers above",
                details="Replace this with what your interview implied you would carry.",
            ),
            InventoryItem(
                name="Unclaimed kit",
                details="The LLM draft did not arrive; rewrite this list before finalizing.",
            ),
        ],
    )


def _setup_state(*, configured: bool) -> GameState:
    setting = (
        "Choose who enters the world before the world is generated."
        if configured
        else "Add OPENROUTER_API_KEY to .env to enable AI-driven character and campaign generation."
    )
    return GameState(
        current_scene="Character creation stands before the first scene.",
        setting_notes=setting,
        player_notes="No finalized character yet.",
        npc_roster_version=2,
        campaign_status=CampaignStatus.CHARACTER_CREATION,
        character=CharacterSheet(
            name="Unnamed wanderer",
            archetype="Unchosen",
            epithet="No identity has been sealed into the ledger yet.",
            backstory="No backstory finalized yet.",
            drive="Choose a life before the world answers it.",
            flaw="Undefined.",
            condition="Unrecorded.",
            inventory=[],
        ),
        oracle_tables=_placeholder_tables(),
    )


@dataclass(frozen=True)
class CharacterGenerator:
    config: NarrativeConfig
    completion_function: CompletionFunction = _completion

    @classmethod
    def from_env(cls) -> CharacterGenerator:
        return cls(config=NarrativeConfig.from_env())

    def setup_state(self) -> GameState:
        return _setup_state(configured=self.config.is_usable())

    def generate_templates(self) -> list[CharacterSheet]:
        return self.generate_templates_result().templates

    def generate_templates_result(self) -> CharacterTemplatesResult:
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
                {"role": "system", "content": CHARACTER_SYSTEM_PROMPT},
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
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterTemplatesResult]:
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
                {"role": "system", "content": CHARACTER_SYSTEM_PROMPT},
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

    def generate_quiz(self, concept: str) -> CharacterQuiz:
        return self.generate_quiz_result(concept).quiz

    def generate_quiz_result(self, concept: str) -> CharacterQuizResult:
        """Produce an interview tailored to the player's concept.

        On any LLM failure we return the static fallback quiz so the
        player can still proceed, but we log loud enough that the
        backend operator can see why their concept didn't customize.
        """
        cleaned = concept.strip()
        if not cleaned or not self.config.is_usable():
            return CharacterQuizResult(quiz=_fallback_quiz(cleaned or "An unspecified survivor."))

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
                {"role": "system", "content": CHARACTER_QUIZ_SYSTEM_PROMPT},
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
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterQuizResult]:
        cleaned = concept.strip()
        if not cleaned or not self.config.is_usable():
            fallback = CharacterQuizResult(
                quiz=_fallback_quiz(cleaned or "An unspecified survivor."),
            )
            yield CompletionDelta(content=json.dumps({"quiz": fallback.quiz.model_dump()}))
            return fallback

        user_prompt = CHARACTER_QUIZ_USER_PROMPT_TEMPLATE.replace("<<CONCEPT>>", cleaned)
        quiz_profile = self.config.profiles.character_quiz
        request = CompletionRequest(
            model=self.config.model,
            messages=[
                {"role": "system", "content": CHARACTER_QUIZ_SYSTEM_PROMPT},
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
    ) -> CharacterSheet:
        return self.generate_quizzed_draft_result(
            concept=concept,
            answers=answers,
            final_note=final_note,
        ).draft

    def generate_quizzed_draft_result(
        self,
        *,
        concept: str,
        answers: list[CharacterQuizAnswer],
        final_note: str | None,
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
        user_prompt = (
            DRAFT_FROM_QUIZ_PROMPT.replace("<<CONCEPT>>", cleaned_concept)
            .replace("<<INTERVIEW>>", interview_block)
            .replace("<<FINAL_NOTE>>", cleaned_note or "(none)")
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
                {"role": "system", "content": CHARACTER_SYSTEM_PROMPT},
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
        user_prompt = (
            DRAFT_FROM_QUIZ_PROMPT.replace("<<CONCEPT>>", cleaned_concept)
            .replace("<<INTERVIEW>>", interview_block)
            .replace("<<FINAL_NOTE>>", cleaned_note or "(none)")
        )
        quizzed_draft_profile = self.config.profiles.quizzed_character_draft
        request = CompletionRequest(
            model=self.config.model,
            messages=[
                {"role": "system", "content": CHARACTER_SYSTEM_PROMPT},
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
    ) -> CharacterSheet:
        return self.generate_draft_result(mode=mode, prompt=prompt, template=template).draft

    def generate_draft_result(
        self,
        *,
        mode: CharacterDraftMode,
        prompt: str | None,
        template: CharacterSheet | None,
    ) -> CharacterDraftResult:
        if not self.config.is_usable():
            return CharacterDraftResult(
                draft=_fallback_draft(mode=mode, prompt=prompt, template=template),
            )

        template_json = (
            template.model_dump_json(indent=2)
            if template is not None
            else "No template provided."
        )
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
                {"role": "system", "content": CHARACTER_SYSTEM_PROMPT},
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
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CharacterDraftResult]:
        if not self.config.is_usable():
            fallback = CharacterDraftResult(
                draft=_fallback_draft(mode=mode, prompt=prompt, template=template),
            )
            yield CompletionDelta(content=fallback.draft.model_dump_json())
            return fallback

        template_json = (
            template.model_dump_json(indent=2)
            if template is not None
            else "No template provided."
        )
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
                {"role": "system", "content": CHARACTER_SYSTEM_PROMPT},
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


@dataclass(frozen=True)
class CampaignGenerator:
    config: NarrativeConfig
    completion_function: CompletionFunction = _completion

    @classmethod
    def from_env(cls) -> CampaignGenerator:
        return cls(config=NarrativeConfig.from_env())

    def generate(self, character: CharacterSheet) -> GameState:
        return self.generate_result(character).state

    def generate_result(self, character: CharacterSheet) -> CampaignWorldResult:
        if not self.config.is_usable():
            return CampaignWorldResult(state=self._configuration_required_state(character))

        campaign_profile = self.config.profiles.campaign_world
        request = CompletionRequest(
            model=self.config.model,
            messages=[
                {"role": "system", "content": CAMPAIGN_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": CAMPAIGN_USER_PROMPT_TEMPLATE.replace(
                        "<<CHARACTER_JSON>>",
                        character.model_dump_json(indent=2),
                    ),
                },
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
                return CampaignWorldResult(
                    state=generated.to_game_state(character),
                    thinking=completed.thinking,
                )
            except GENERATION_ERRORS as exc:
                last_error = exc
                if attempt < self.config.max_retries:
                    time.sleep(0.4 * (attempt + 1))

        return CampaignWorldResult(
            state=self._configuration_required_state(character, last_error),
        )

    def iter_generate(
        self,
        character: CharacterSheet,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> Generator[CompletionDelta, None, CampaignWorldResult]:
        if not self.config.is_usable():
            fallback = CampaignWorldResult(state=self._configuration_required_state(character))
            yield CompletionDelta(content=json.dumps(fallback.state.model_dump(mode="json")))
            return fallback

        campaign_profile = self.config.profiles.campaign_world
        request = CompletionRequest(
            model=self.config.model,
            messages=[
                {"role": "system", "content": CAMPAIGN_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": CAMPAIGN_USER_PROMPT_TEMPLATE.replace(
                        "<<CHARACTER_JSON>>",
                        character.model_dump_json(indent=2),
                    ),
                },
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
                return CampaignWorldResult(
                    state=generated.to_game_state(character),
                    thinking="".join(thinking_parts).strip(),
                )
            except GENERATION_ERRORS as exc:
                last_error = exc
                if attempt < self.config.max_retries:
                    time.sleep(0.4 * (attempt + 1))

        fallback = CampaignWorldResult(
            state=self._configuration_required_state(character, last_error),
        )
        yield CompletionDelta(content=json.dumps(fallback.state.model_dump(mode="json")))
        return fallback

    def _openrouter_headers(self) -> dict[str, str] | None:
        if not self.config.model.startswith("openrouter/"):
            return None
        headers: dict[str, str] = {}
        if self.config.site_url is not None:
            headers["HTTP-Referer"] = self.config.site_url
        if self.config.app_name is not None:
            headers["X-Title"] = self.config.app_name
        return headers or None

    def _configuration_required_state(
        self,
        character: CharacterSheet,
        error: Exception | None = None,
    ) -> GameState:
        note = (
            "No campaign fiction has been generated yet. Add OPENROUTER_API_KEY "
            "to .env, then try again."
            if error is None
            else (
                "Campaign generation failed, so this placeholder world was produced instead. "
                f"Last error: {error}"
            )
        )
        return GameState(
            current_scene="The world has not finished taking shape around the chosen character.",
            setting_notes=note,
            player_notes=character.backstory,
            npc_roster_version=2,
            character=character,
            campaign_status=CampaignStatus.ACTIVE,
            threads=[
                GameThread(
                    title="Begin proper campaign generation.",
                    stakes="The world is still generic until a valid generation succeeds.",
                ),
                GameThread(
                    title="Carry the character into a real opening scene.",
                    stakes="Without a real opening, play remains a placeholder exercise.",
                ),
                GameThread(
                    title="Replace placeholder oracle tables.",
                    stakes="Events will feel thin until the generated word banks arrive.",
                ),
            ],
            hidden_npcs=[
                NPC(
                    name="Unfinished World",
                    role="Placeholder witness",
                    disposition="Waiting for a stable generation to take form.",
                ),
                NPC(
                    name="The Missing Scene",
                    role="Placeholder absence",
                    disposition="Presses on the edges of every sentence.",
                ),
            ],
            oracle_tables=_placeholder_tables(),
        )
