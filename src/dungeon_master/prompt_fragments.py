"""Shared prompt policy blocks and string fragments to reduce duplication."""

JSON_ONLY = "Return only valid JSON."

JSON_ONLY_PERSIST = (
    "Return only valid JSON. The application will persist your JSON as structured state."
)

SEED_AUTHORITY = (
    "The campaign seed supplied by the user is authoritative for genre, era, "
    "technology, magic, tone, stakes, inspirations, and restrictions."
)


def no_invention_rule(allowed_sources: str) -> str:
    """Return the standard no-invention rule parameterized by allowed sources."""
    return f"Never invent new facts beyond the supplied {allowed_sources}."


CONTINUITY_UPDATER_PREAMBLE = (
    "If a final narration response is supplied, treat it as player-visible canon.\n"
    "Only extract durable changes that the narration explicitly establishes.\n"
    "Never let narration-only extraction contradict the resolved oracle outcome or\n"
    "executed backend steps."
)

NO_KEYWORD_TRIGGERS = "Do not use keyword triggers. Judge the whole context."

CAIRN_ALLOWED_ENUMS = (
    "Allowed tags: petty, bulky, weapon, ranged, armor, shield, tool, light, "
    "relic, holy, healing, consumable, supplies, magic, utility\n"
    "Allowed power kinds: none, spellbook, scroll, relic, holy_relic\n"
    "Allowed effects: none, restore_hp, restore_attribute, clear_condition, "
    "enhance_attack, impair_target, force_save, reveal_sign, create_safe_passage, "
    "ward_or_pacify, extraordinary_aid, resurrect\n"
    "Allowed clear conditions: deprived, critically_wounded, doomed, paralyzed, delirious"
)

CAIRN_ITEM_SEMANTICS = (
    "Use Cairn-style item semantics: petty vs bulky, armor bonus, weapon die,\n"
    "uses, equipped state.\n"
    "For limited ammunition/charges/fuel/components, prefer structured\n"
    "`resources` and `attack_costs` over prose. Use `uses` only as a legacy\n"
    "single counter when no structured pool fits."
)


def render_updater_user_prompt(  # noqa: PLR0913
    scene_text: str,
    player_input: str,
    outcome_kind: str,
    outcome_summary: str,
    execution_context: str | None,
    final_narration: str | None,
    domain_state: str | None = None,
    memory_context: str | None = None,
    directives: str | None = None,
    actors: str | None = None,
) -> str:
    """Assemble the shared user-prompt template for the JSON continuity updaters."""
    lines: list[str] = []

    if memory_context:
        lines.extend(
            [
                "Bounded memory context (may be empty):",
                memory_context,
                "",
            ]
        )

    if directives:
        lines.extend(
            [
                "Campaign directives (may be empty):",
                directives,
                "",
            ]
        )

    lines.extend(
        [
            "Current scene:",
            scene_text,
            "",
            "Player input:",
            player_input,
            "",
            "Resolved oracle outcome:",
            f"- kind: {outcome_kind}",
            f"- summary: {outcome_summary}",
            "",
        ]
    )

    lines.append("Executed backend steps (may be empty):")
    if execution_context:
        lines.append(execution_context)
    lines.append("")

    if actors is not None:
        lines.extend(["Current actors:", actors, ""])
    lines.extend(["Final narration response:", final_narration or "", ""])

    if domain_state:
        lines.extend(
            [
                domain_state,
                "",
            ]
        )

    return "\n".join(lines).strip()
