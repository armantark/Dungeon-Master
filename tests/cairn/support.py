from litellm.types.utils import ModelResponse

from dungeon_master.llm.completion import CompletionRequest
from dungeon_master.models import (
    CairnCharacterState,
    CairnItemState,
    CairnItemTag,
    CairnMechanicsSource,
    EncounterState,
    EnemyCombatant,
    GameState,
    InventoryItem,
    PartyMember,
)
from dungeon_master.narrative import NarrativeConfig
from tests.factories import sample_state


def _ready_state() -> GameState:
    state = sample_state()
    state.character.cairn = CairnCharacterState(
        source=CairnMechanicsSource.EXPLICIT,
        str_score=12,
        dex_score=12,
        wil_score=10,
        max_str_score=12,
        max_dex_score=12,
        max_wil_score=10,
        hp=4,
        max_hp=4,
    )
    weapon = state.character.inventory[0]
    weapon.cairn = CairnItemState(
        source=CairnMechanicsSource.EXPLICIT,
        tags=[CairnItemTag.WEAPON],
        weapon_damage_die=6,
        equipped=True,
    )
    return state


def _active_encounter_state(*, player_dex: int, enemy_dex: int) -> GameState:
    state = _ready_state()
    state.character.cairn.dex_score = player_dex
    state.character.cairn.max_dex_score = player_dex
    state.encounter = EncounterState(
        active=True,
        round_number=2,
        combatants=[
            EnemyCombatant(
                name="Abbey ghoul",
                hp=4,
                max_hp=4,
                dex_score=enemy_dex,
            ),
        ],
    )
    return state


def _companion_state() -> GameState:
    state = _ready_state()
    companion = PartyMember(
        sheet=state.character.model_copy(deep=True),
        loyalty="Paid through the next dawn.",
    )
    companion.sheet.name = "Brother Sava"
    companion.sheet.inventory = [
        InventoryItem(
            name="Sava's spear",
            details="A hireling's ashwood spear.",
            cairn=CairnItemState(
                source=CairnMechanicsSource.EXPLICIT,
                tags=[CairnItemTag.WEAPON],
                weapon_damage_die=8,
                equipped=True,
            ),
        ),
        InventoryItem(
            name="Shared rope",
            details="Twenty-five feet of knotted rope.",
            cairn=CairnItemState(source=CairnMechanicsSource.EXPLICIT, slots=1),
        ),
    ]
    companion.sheet.cairn = CairnCharacterState(
        source=CairnMechanicsSource.EXPLICIT,
        str_score=10,
        dex_score=18,
        wil_score=9,
        max_str_score=10,
        max_dex_score=18,
        max_wil_score=9,
        hp=3,
        max_hp=3,
    )
    state.party_members.append(companion)
    return state


class RecordingAcquisitionCompletion:
    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.messages: list[dict[str, str]] | None = None

    def __call__(self, request: CompletionRequest) -> ModelResponse:
        self.messages = request.messages
        del request

        def _stream() -> list[dict[str, object]]:
            return [
                {
                    "choices": [
                        {
                            "delta": {
                                "content": self.payload,
                            },
                        },
                    ],
                },
            ]

        return _stream()  # type: ignore[return-value]


class RecordingBackfillCompletion(RecordingAcquisitionCompletion):
    def __call__(self, request: CompletionRequest) -> ModelResponse:
        self.messages = request.messages
        del request
        return ModelResponse(choices=[{"message": {"content": self.payload}}])


def _usable_test_config() -> NarrativeConfig:
    return NarrativeConfig(model="test-model", api_key=None, base_url=None)
