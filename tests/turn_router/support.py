from litellm.types.utils import ModelResponse

from dungeon_master.narrative import CompletionRequest


class RecordingRouterCompletion:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] | None = None
        self.request: CompletionRequest | None = None

    def __call__(self, request: CompletionRequest) -> ModelResponse:
        self.request = request
        self.messages = request.messages

        def _stream() -> list[dict[str, object]]:
            return [
                {
                    "choices": [
                        {
                            "delta": {
                                "content": (
                                    '{"route":"player_action","text":"I listen at the abbey door.",'
                                    '"ops":[{"kind":"narrate","text":"I listen at the abbey door.",'
                                    '"likelihood":null,"ability":null,"target_name":null,'
                                    '"stance":null,"rest_kind":null,"item_name":null,'
                                    '"equipped":null,"harm_amount":null,"harm_source":null,'
                                    '"armor_applies":null,"in_combat":null}]}'
                                ),
                            },
                        },
                    ],
                },
            ]

        return _stream()  # type: ignore[return-value]


class BrokenRouterCompletion:
    def __call__(self, request: CompletionRequest) -> ModelResponse:
        del request
        return []  # type: ignore[return-value]


class RepairingRouterCompletion:
    def __init__(self) -> None:
        self.requests: list[CompletionRequest] = []

    def __call__(self, request: CompletionRequest) -> ModelResponse:
        self.requests.append(request)

        def _stream(content: str) -> list[dict[str, object]]:
            return [{"choices": [{"delta": {"content": content}}]}]

        if request.trace_route == "turn_router.repair":
            return _stream(
                '{"route":"player_action","text":"I listen at the abbey door.",'
                '"ops":[{"kind":"narrate","text":"I listen at the abbey door.",'
                '"likelihood":null,"ability":null,"target_name":null,'
                '"stance":null,"rest_kind":null,"item_name":null,'
                '"equipped":null,"harm_amount":null,"harm_source":null,'
                '"armor_applies":null,"in_combat":null}]}',
            )  # type: ignore[return-value]
        return _stream("not json")  # type: ignore[return-value]


class CombatReviewRouterCompletion:
    def __init__(self, *, review_allows: bool) -> None:
        self.review_allows = review_allows
        self.requests: list[CompletionRequest] = []

    def __call__(self, request: CompletionRequest) -> ModelResponse:
        self.requests.append(request)

        def _stream(content: str) -> list[dict[str, object]]:
            return [{"choices": [{"delta": {"content": content}}]}]

        if request.trace_route == "turn_router.combat_review":
            return _stream(
                '{"allow_combat_mechanics":'
                f"{str(self.review_allows).lower()},"
                '"reason":"structured review verdict"}',
            )  # type: ignore[return-value]
        return _stream(
            '{"route":"attack","text":"I swing my cudgel at the abbey ghoul.",'
            '"ops":[{"kind":"attack","text":"I swing my cudgel at the abbey ghoul.",'
            '"likelihood":null,"ability":null,"target_name":"Abbey ghoul",'
            '"stance":"normal","rest_kind":null,"item_name":null,'
            '"equipped":null,"harm_amount":null,"harm_source":null,'
            '"armor_applies":null,"in_combat":null}]}',
        )  # type: ignore[return-value]


class SaveReviewRouterCompletion:
    def __init__(self, *, review_allows: bool) -> None:
        self.review_allows = review_allows
        self.requests: list[CompletionRequest] = []

    def __call__(self, request: CompletionRequest) -> ModelResponse:
        self.requests.append(request)

        def _stream(content: str) -> list[dict[str, object]]:
            return [{"choices": [{"delta": {"content": content}}]}]

        if request.trace_route == "turn_router.save_review":
            return _stream(
                '{"allow_save_mechanics":'
                f"{str(self.review_allows).lower()},"
                '"reason":"structured save review verdict"}',
            )  # type: ignore[return-value]
        return _stream(
            '{"route":"save","text":"I keep the persona going.",'
            '"ops":[{"kind":"save","text":"I keep the persona going.",'
            '"likelihood":null,"ability":"WIL","target_name":null,'
            '"stance":null,"rest_kind":null,"item_name":null,'
            '"equipped":null,"harm_amount":null,"harm_source":null,'
            '"armor_applies":null,"in_combat":null}]}',
        )  # type: ignore[return-value]
