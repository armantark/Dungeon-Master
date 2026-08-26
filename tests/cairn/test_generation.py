from dungeon_master.domain.models import (
    CairnAbility,
    CairnItemState,
    CairnItemTag,
    CairnResourceRechargePolicy,
    CampaignGenre,
    CampaignMagicLevel,
    CampaignSeed,
    CampaignStakesScale,
    CampaignTechLevel,
    CampaignTimePeriod,
    CampaignToneDarkBright,
    CampaignToneGrimNoble,
)
from dungeon_master.llm.narration import NarrativeConfig
from dungeon_master.mechanics.engine import (
    CairnEngine,
    GeneratedCairnBackfill,
    GeneratedCairnItemProfile,
)
from tests.cairn.support import (
    RecordingBackfillCompletion,
)
from tests.factories import sample_state


def test_cairn_item_state_normalizes_petty_and_bulky_slots() -> None:
    petty = CairnItemState(tags=[CairnItemTag.PETTY], slots=1)
    bulky = CairnItemState(tags=[CairnItemTag.BULKY], slots=1)
    mixed = CairnItemState(tags=[CairnItemTag.PETTY, CairnItemTag.BULKY], slots=0)

    assert petty.slots == 0
    assert bulky.slots == 2
    assert mixed.slots == 2


def test_generated_backfill_normalizes_zero_weapon_damage_for_non_weapons() -> None:
    generated = GeneratedCairnBackfill.model_validate(
        {
            "skills": ["Road-hardened"],
            "abilities": [],
            "str_score": 10,
            "dex_score": 10,
            "wil_score": 10,
            "max_hp": 3,
            "fatigue": 0,
            "deprived": False,
            "critically_wounded": False,
            "doomed": False,
            "paralyzed": False,
            "delirious": False,
            "dead": False,
            "notes": "Generated from a model payload that used 0 as a placeholder.",
            "inventory": [
                {
                    "name": "Tallow candle",
                    "details": "A tiny light for the ash road.",
                    "tags": ["light", "petty"],
                    "slots": 0,
                    "weapon_damage_die": 0,
                    "armor_bonus": 0,
                    "uses": None,
                    "equipped": False,
                },
                {
                    "name": "Trail rations",
                    "details": "Dried bread and salt fish.",
                    "tags": ["supplies"],
                    "slots": 1,
                    "weapon_damage_die": "0",
                    "armor_bonus": 0,
                    "uses": None,
                    "equipped": False,
                },
            ],
        },
    )

    assert [item.weapon_damage_die for item in generated.inventory] == [None, None]


def test_generated_item_profile_normalizes_slots_from_petty_and_bulky_tags() -> None:
    petty = GeneratedCairnItemProfile.model_validate(
        {
            "name": "Folded phone number",
            "details": "A small note tucked into a pocket.",
            "tags": ["petty", "utility"],
            "slots": 1,
            "weapon_damage_die": None,
            "armor_bonus": 0,
            "uses": None,
            "equipped": False,
        },
    )
    bulky = GeneratedCairnItemProfile.model_validate(
        {
            "name": "Gaming laptop",
            "details": "Heavy enough to matter.",
            "tags": ["tool", "bulky"],
            "slots": 1,
            "weapon_damage_die": None,
            "armor_bonus": 0,
            "uses": None,
            "equipped": False,
        },
    )

    assert petty.slots == 0
    assert bulky.slots == 2


def test_generated_backfill_defaults_missing_weapon_damage_for_weapons() -> None:
    generated = GeneratedCairnBackfill.model_validate(
        {
            "skills": ["Road-hardened"],
            "abilities": [],
            "str_score": 10,
            "dex_score": 10,
            "wil_score": 10,
            "max_hp": 3,
            "fatigue": 0,
            "deprived": False,
            "critically_wounded": False,
            "doomed": False,
            "paralyzed": False,
            "delirious": False,
            "dead": False,
            "notes": "Generated from a model payload that omitted a weapon die.",
            "inventory": [
                {
                    "name": "Notched cudgel",
                    "details": "A heavy pilgrim's club.",
                    "tags": ["weapon"],
                    "slots": 1,
                    "weapon_damage_die": 0,
                    "armor_bonus": 0,
                    "uses": None,
                    "equipped": True,
                },
                {
                    "name": "Trail rations",
                    "details": "Dried bread and salt fish.",
                    "tags": ["supplies"],
                    "slots": 1,
                    "weapon_damage_die": None,
                    "armor_bonus": 0,
                    "uses": None,
                    "equipped": False,
                },
            ],
        },
    )

    assert generated.inventory[0].weapon_damage_die == 6
    assert generated.inventory[1].weapon_damage_die is None


def test_generated_backfill_normalizes_common_llm_enum_slop() -> None:
    generated = GeneratedCairnBackfill.model_validate(
        {
            "skills": ["Zealous guard"],
            "abilities": ["Pain tolerance"],
            "str_score": 12,
            "dex_score": 9,
            "wil_score": 14,
            "max_hp": 4,
            "inventory": [
                {
                    "name": "Martyr's iron pendant",
                    "details": "A crude symbol worn at the throat.",
                    "tags": ["holy_relic", "petty"],
                    "slots": 0,
                    "weapon_damage_die": None,
                    "armor_bonus": 0,
                    "uses": None,
                    "equipped": True,
                    "power": {
                        "kind": "holy_relic",
                        "name": "Witness the wound",
                        "summary": "Bolsters resolve in danger.",
                        "effect": "restore_attribute",
                        "effect_amount": 1,
                        "effect_ability": "wil",
                        "clears_condition": None,
                        "recharge_condition": "",
                        "requires_wil_save_in_danger": False,
                        "adds_fatigue": False,
                        "consumed_on_use": False,
                    },
                },
                {
                    "name": "Iron mace",
                    "details": "A practical weapon.",
                    "tags": ["weapon"],
                    "slots": 2,
                    "weapon_damage_die": 8,
                    "armor_bonus": 0,
                    "uses": None,
                    "equipped": True,
                },
            ],
        },
    )

    relic = generated.inventory[0]
    assert relic.tags == [CairnItemTag.HOLY, CairnItemTag.RELIC, CairnItemTag.PETTY]
    assert relic.power.effect_ability == CairnAbility.WIL


def test_generated_backfill_normalizes_resource_recharge_policy_synonyms() -> None:
    generated = GeneratedCairnBackfill.model_validate(
        {
            "skills": ["Terminally online"],
            "abilities": ["Knows obscure forums"],
            "str_score": 8,
            "dex_score": 9,
            "wil_score": 10,
            "max_hp": 2,
            "inventory": [
                {
                    "name": "MLP jar",
                    "details": "Need I say more?",
                    "tags": ["petty"],
                    "slots": 0,
                    "weapon_damage_die": None,
                    "armor_bonus": 0,
                    "uses": None,
                    "equipped": False,
                    "resources": [
                        {
                            "label": "Psychic damage",
                            "kind": "custom",
                            "current": 1,
                            "max": 1,
                            "recharge_policy": "per_rest",
                        },
                    ],
                },
                {
                    "name": "Laptop",
                    "details": "Covered in Cheeto dust.",
                    "tags": ["tool"],
                    "slots": 1,
                    "weapon_damage_die": None,
                    "armor_bonus": 0,
                    "uses": None,
                    "equipped": False,
                },
            ],
        },
    )

    assert (
        generated.inventory[0].resources[0].recharge_policy == CairnResourceRechargePolicy.ON_REST
    )


def test_backfill_prompt_preserves_visible_authored_gear() -> None:
    state = sample_state()
    authored = state.character.model_copy(
        update={
            "name": "Test Companion",
            "backstory": (
                "Recent player-visible context for this recruit:\n"
                "- Narrative response: The companion keeps a rusted wood-axe ready."
            ),
        },
        deep=True,
    )
    payload = GeneratedCairnBackfill(
        skills=["Keep watch"],
        abilities=["Hold a doorway"],
        str_score=10,
        dex_score=11,
        wil_score=9,
        max_hp=3,
        inventory=[
            GeneratedCairnItemProfile(
                name="Rusted wood-axe",
                details="The weapon already surfaced in play.",
                tags=[CairnItemTag.WEAPON],
                slots=1,
                weapon_damage_die=6,
                armor_bonus=0,
                uses=None,
                equipped=True,
            ),
            GeneratedCairnItemProfile(
                name="Threadbare shawl",
                details="A poor cloak against ash-cold air.",
                tags=[CairnItemTag.PETTY],
                slots=0,
                weapon_damage_die=None,
                armor_bonus=0,
                uses=None,
                equipped=False,
            ),
        ],
    ).model_dump_json()
    completion = RecordingBackfillCompletion(payload)
    engine = CairnEngine(
        config=NarrativeConfig(model="test-model", api_key="test-key", base_url=None),
        completion_function=completion,
    )

    sheet = engine.backfill_companion_sheet(state, authored)

    assert completion.messages is not None
    system_prompt = " ".join(completion.messages[0]["content"].split())
    user_prompt = " ".join(completion.messages[1]["content"].split())
    assert "concrete visible gear already established in play" in system_prompt
    assert "Preserve concrete carried gear named in the authored character context" in user_prompt
    assert "rusted wood-axe" in user_prompt
    assert sheet.inventory[0].name == "Rusted wood-axe"
    assert sheet.cairn.primary_weapon_item_id == sheet.inventory[0].id


def test_backfill_prompt_uses_campaign_seed_as_setting_authority() -> None:
    state = sample_state()
    state.campaign_seed = CampaignSeed(
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
    payload = GeneratedCairnBackfill(
        skills=["Awkward small talk"],
        abilities=["Finds obscure forum threads"],
        str_score=8,
        dex_score=9,
        wil_score=10,
        max_hp=2,
        inventory=[
            GeneratedCairnItemProfile(
                name="Laptop",
                details="A mundane laptop.",
                tags=[CairnItemTag.TOOL],
                slots=1,
                weapon_damage_die=None,
                armor_bonus=0,
                uses=None,
                equipped=False,
            ),
            GeneratedCairnItemProfile(
                name="Phone",
                details="A mundane smartphone.",
                tags=[CairnItemTag.UTILITY],
                slots=0,
                weapon_damage_die=None,
                armor_bonus=0,
                uses=None,
                equipped=False,
            ),
        ],
    ).model_dump_json()
    completion = RecordingBackfillCompletion(payload)
    engine = CairnEngine(
        config=NarrativeConfig(model="test-model", api_key="test-key", base_url=None),
        completion_function=completion,
    )

    engine.ensure_character_state(state, allow_backfill=True)

    assert completion.messages is not None
    system_prompt = completion.messages[0]["content"]
    user_prompt = completion.messages[1]["content"]
    assert "campaign seed supplied in the user prompt is authoritative" in system_prompt
    assert "fiction-first dark-fantasy character" not in system_prompt
    assert "Era/technology: modern with modern technology." in user_prompt
    assert "No supernatural, horror, medieval" in user_prompt
