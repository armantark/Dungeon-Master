from dungeon_master.llm.prompt_fragments import (
    CAIRN_ALLOWED_ENUMS,
    CAIRN_ITEM_SEMANTICS,
    CONTINUITY_UPDATER_PREAMBLE,
    JSON_ONLY,
    JSON_ONLY_PERSIST,
    NO_KEYWORD_TRIGGERS,
    SEED_AUTHORITY,
    no_invention_rule,
    render_updater_user_prompt,
)


def test_json_only_fragments() -> None:
    assert "Return only valid JSON." in JSON_ONLY
    assert "persist" in JSON_ONLY_PERSIST


def test_seed_authority_fragment() -> None:
    assert "campaign seed supplied by the user is authoritative" in SEED_AUTHORITY


def test_no_invention_rule_parameterized() -> None:
    result = no_invention_rule("player input and oracle outcome")
    assert "Never invent new facts beyond the supplied player input and oracle outcome." in result


def test_continuity_updater_preamble() -> None:
    assert "player-visible canon" in CONTINUITY_UPDATER_PREAMBLE
    assert "Never let narration-only extraction contradict" in CONTINUITY_UPDATER_PREAMBLE


def test_no_keyword_triggers() -> None:
    assert "Do not use keyword triggers." in NO_KEYWORD_TRIGGERS


def test_cairn_enums_and_semantics() -> None:
    assert "Allowed tags: petty, bulky, weapon" in CAIRN_ALLOWED_ENUMS
    assert "petty vs bulky" in CAIRN_ITEM_SEMANTICS
    assert "resources" in CAIRN_ITEM_SEMANTICS


def test_render_updater_user_prompt_full() -> None:
    prompt = render_updater_user_prompt(
        scene_text="A dark room.",
        player_input="I look around.",
        outcome_kind="PLAYER_ACTION",
        outcome_summary="Success",
        execution_context="Did a thing.",
        final_narration="You see nothing.",
        domain_state="Current threads: []",
        memory_context="Previous turns...",
        directives="Do no harm.",
        actors="Player sheet",
    )
    assert "Bounded memory context" in prompt
    assert "Previous turns..." in prompt
    assert "Campaign directives" in prompt
    assert "Do no harm." in prompt
    assert "Current scene:\nA dark room." in prompt
    assert "Player input:\nI look around." in prompt
    assert "Resolved oracle outcome:\n- kind: PLAYER_ACTION\n- summary: Success" in prompt
    assert "Executed backend steps (may be empty):\nDid a thing." in prompt
    assert "Current actors:\nPlayer sheet" in prompt
    assert "Final narration response:\nYou see nothing." in prompt
    assert "Current threads: []" in prompt


def test_render_updater_user_prompt_minimal() -> None:
    prompt = render_updater_user_prompt(
        scene_text="A room.",
        player_input="Look.",
        outcome_kind="RANDOM_EVENT",
        outcome_summary="Failure",
        execution_context=None,
        final_narration=None,
    )
    assert "Current scene:\nA room." in prompt
    assert "Player input:\nLook." in prompt
    assert "Resolved oracle outcome:\n- kind: RANDOM_EVENT\n- summary: Failure" in prompt
    assert "Executed backend steps (may be empty):\n\nFinal narration response" in prompt
    assert "Bounded memory" not in prompt
    assert "Campaign directives" not in prompt
    assert "Current actors" not in prompt
