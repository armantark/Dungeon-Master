from __future__ import annotations

from dungeon_master.domain.models import (
    CampaignSeed,
    CampaignStatus,
    CharacterQuiz,
    CharacterQuizAnswer,
    CharacterQuizOption,
    CharacterQuizQuestion,
    CharacterSheet,
    GameState,
    InventoryItem,
    OracleTables,
)
from dungeon_master.generation.contracts import CharacterDraftMode


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
                prompt="What pressure do you carry into the first scene?",
                options=[
                    CharacterQuizOption(label="A private fear you keep managing alone."),
                    CharacterQuizOption(label="An obligation that shapes your daily choices."),
                    CharacterQuizOption(label="A habit that protects you and limits you."),
                    CharacterQuizOption(label="A longing you are tired of explaining away."),
                ],
            ),
            CharacterQuizQuestion(
                prompt="What did you bring from the life that shaped you?",
                options=[
                    CharacterQuizOption(label="A keepsake whose meaning is hard to admit."),
                    CharacterQuizOption(label="A skill you learned for practical reasons."),
                    CharacterQuizOption(label="A memory that changes how you trust people."),
                    CharacterQuizOption(label="A routine that keeps your life from drifting."),
                ],
            ),
            CharacterQuizQuestion(
                prompt="Who or what still has a claim on your attention?",
                options=[
                    CharacterQuizOption(label="Family expectations I have not settled."),
                    CharacterQuizOption(label="Work that expands to fill every quiet hour."),
                    CharacterQuizOption(label="A friendship I let become awkward."),
                    CharacterQuizOption(label="An old attachment I keep comparing against."),
                ],
            ),
            CharacterQuizQuestion(
                prompt="What pattern do you keep repeating despite the cost?",
                options=[
                    CharacterQuizOption(label="I wait for certainty before acting."),
                    CharacterQuizOption(label="I over-explain when I feel exposed."),
                    CharacterQuizOption(label="I choose solitude and call it discernment."),
                    CharacterQuizOption(label="I test people instead of asking plainly."),
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


def _setup_state(*, configured: bool, seed: CampaignSeed) -> GameState:
    setting = (
        "Choose who enters the world before the world is generated."
        if configured
        else (
            "Add a Gemini or OpenRouter API key in the app settings or .env "
            "to enable AI-driven character and campaign generation."
        )
    )
    return GameState(
        current_scene="Character creation stands before the first scene.",
        setting_notes=setting,
        player_notes="No finalized character yet.",
        campaign_seed=seed,
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
