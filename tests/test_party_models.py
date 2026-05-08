from dungeon_master.models import (
    CairnCharacterState,
    CairnMechanicsSource,
    CharacterSheet,
    GameState,
    PartyMember,
    PartyMemberKind,
)
from tests.factories import sample_state


def test_game_state_accepts_legacy_payload_without_party_members() -> None:
    state = sample_state()
    payload = state.model_dump(mode="json")
    payload.pop("party_members")

    restored = GameState.model_validate(payload)

    assert restored.party_members == []
    assert [sheet.name for sheet in restored.party_sheets()] == ["Test Wanderer"]


def test_party_member_wraps_character_sheet_for_cairn_state() -> None:
    state = sample_state()
    companion = PartyMember(
        kind=PartyMemberKind.HIRELING,
        sheet=CharacterSheet(
            name="Brother Sava",
            archetype="Lantern bearer",
            inventory=[],
            cairn=CairnCharacterState(
                source=CairnMechanicsSource.EXPLICIT,
                hp=3,
                max_hp=3,
                str_score=9,
                dex_score=11,
                wil_score=12,
                max_str_score=9,
                max_dex_score=11,
                max_wil_score=12,
            ),
        ),
        npc_id="npc_sava",
        loyalty="Paid through the next dawn.",
    )
    state.party_members.append(companion)

    assert state.party_members[0].display_label() == "Brother Sava"
    assert state.party_members[0].sheet.cairn.hp == 3
    assert [sheet.name for sheet in state.party_sheets()] == ["Test Wanderer", "Brother Sava"]


def test_inactive_party_member_is_not_in_active_party_sheets() -> None:
    state = sample_state()
    state.party_members.append(
        PartyMember(
            active=False,
            sheet=CharacterSheet(name="Dismissed guide"),
        ),
    )

    assert [sheet.name for sheet in state.party_sheets()] == ["Test Wanderer"]
