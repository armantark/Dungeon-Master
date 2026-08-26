from litellm.types.utils import ModelResponse

from dungeon_master.application.updates.inventory import InventoryUpdater
from dungeon_master.domain.models import GameState, InventoryItem, OracleKind, OracleOutcome
from dungeon_master.llm.narration import CompletionRequest, NarrativeConfig
from tests.factories import sample_state


class RecordingInventoryCompletion:
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


class FakeInventoryCairn:
    def __init__(self) -> None:
        self.acquire_calls: list[tuple[str, str | None]] = []
        self.drop_calls: list[tuple[str, str | None]] = []

    def acquire_items(
        self,
        state: GameState,
        *,
        text: str,
        actor_id: str | None = None,
        cancel_token: object | None = None,
    ) -> str:
        del cancel_token
        self.acquire_calls.append((text, actor_id))
        actor_inventory = state.character.inventory
        actor_inventory.append(InventoryItem(name=text.split(" ", maxsplit=1)[0], details=text))
        return f"acquired from narration: {text}"

    def drop_item(
        self,
        state: GameState,
        *,
        item_id: str,
        actor_id: str | None = None,
    ) -> str:
        self.drop_calls.append((item_id, actor_id))
        state.character.inventory = [
            item for item in state.character.inventory if item.id != item_id
        ]
        return f"dropped narrated item {item_id}"


def _updater(payload: str, cairn: FakeInventoryCairn) -> InventoryUpdater:
    return InventoryUpdater(
        cairn=cairn,
        config=NarrativeConfig(model="test-model", api_key=None, base_url=None, max_retries=0),
        completion_function=RecordingInventoryCompletion(payload),
    )


def test_inventory_updater_adds_mundane_worn_item_from_narration() -> None:
    state = sample_state()
    cairn = FakeInventoryCairn()
    updater = _updater(
        """
        {
          "ops": [
            {
              "actor_id": "player",
              "kind": "add_item",
              "item_name": "Fedora",
              "item_text": "Fedora worn on the player's head.",
              "reason": "The narration makes the hat part of the player's outfit."
            }
          ]
        }
        """,
        cairn,
    )
    outcome = OracleOutcome(
        kind=OracleKind.PLAYER_ACTION,
        summary="You keep the hat on despite the drizzle.",
        chaos_factor=state.chaos_factor,
    )

    result = updater.update_inventory(
        state,
        player_input="I keep walking with the hat tilted low.",
        outcome=outcome,
        execution_context="Executed backend steps:\n- Narrative continuation requested.",
        narrative_text="The fedora stays on your head as you head for the arcade awning.",
    )

    assert result.changed is True
    assert cairn.acquire_calls == [("Fedora worn on the player's head.", "player")]
    assert any(item.name == "Fedora" for item in state.character.inventory)


def test_inventory_updater_removes_consumed_item_from_inventory() -> None:
    state = sample_state()
    drink = InventoryItem(name="Soylent Boba", details="Mostly gone already.")
    state.character.inventory.append(drink)
    cairn = FakeInventoryCairn()
    updater = _updater(
        """
        {
          "ops": [
            {
              "actor_id": "player",
              "kind": "remove_item",
              "item_name": "Soylent Boba",
              "item_text": null,
              "reason": "The final narration makes it clear the drink is finished."
            }
          ]
        }
        """,
        cairn,
    )
    outcome = OracleOutcome(
        kind=OracleKind.PLAYER_ACTION,
        summary="You finish the drink.",
        chaos_factor=state.chaos_factor,
    )

    result = updater.update_inventory(
        state,
        player_input="I chug the boba.",
        outcome=outcome,
        execution_context="Executed backend steps:\n- Narrative continuation requested.",
        narrative_text="You drain the soylent boba and crumple the cup.",
    )

    assert result.changed is True
    assert cairn.drop_calls == [(drink.id, "player")]
    assert all(item.name != "Soylent Boba" for item in state.character.inventory)


def test_inventory_updater_skips_add_for_existing_item_variant() -> None:
    state = sample_state()
    cairn = FakeInventoryCairn()
    updater = _updater(
        """
        {
          "ops": [
            {
              "actor_id": "player",
              "kind": "add_item",
              "item_name": "Map",
              "item_text": "Map folded inside the player's jacket.",
              "reason": "The narration refers to the same map already carried."
            }
          ]
        }
        """,
        cairn,
    )
    outcome = OracleOutcome(
        kind=OracleKind.PLAYER_ACTION,
        summary="You double-check the route.",
        chaos_factor=state.chaos_factor,
    )

    result = updater.update_inventory(
        state,
        player_input="I check the map again.",
        outcome=outcome,
        execution_context="Executed backend steps:\n- Inspected carried gear.",
        narrative_text="You smooth the map you already had tucked away.",
    )

    assert result.changed is False
    assert cairn.acquire_calls == []
    assert [item.name for item in state.character.inventory] == ["Test knife", "Test map"]
