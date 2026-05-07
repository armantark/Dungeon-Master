from __future__ import annotations

import json
import time
from dataclasses import dataclass
from enum import StrEnum

from pydantic import Field, ValidationError

from dungeon_master.cancel import CancellationToken
from dungeon_master.models import GameState, GameThread, OracleOutcome, StrictModel, ThreadStatus
from dungeon_master.narrative import (
    LITELLM_RETRYABLE_ERRORS,
    CompletionFunction,
    CompletionRequest,
    NarrativeConfig,
    _completion,
    complete_text,
    extract_json_object,
)

THREAD_UPDATER_SYSTEM_PROMPT = """You update the canonical long-running thread list for a solo
tabletop role-playing game after a turn has already resolved.

Return only valid JSON.

Hard rules:
- You may emit 0-2 thread ops total.
- Thread ops may only be: create, update, resolve.
- Only create a thread when the turn introduces a durable unresolved matter
  that should persist beyond the immediate beat.
- Prefer updating an existing thread over creating a near-duplicate.
- Resolve a thread only when the supplied outcome + executed steps actually
  discharge its stakes or close the matter in canon.
- Never delete threads.
- Never invent new facts beyond the supplied player input, oracle outcome,
  executed backend steps, current threads, and memory context.
- For update/resolve, use an exact supplied thread_id from the current threads list.
- Keep thread titles short, concrete, and future-playable.
- Keep stakes focused on what remains at risk if the matter is ignored.
"""

THREAD_UPDATER_USER_PROMPT_TEMPLATE = """Return JSON with this shape:
{
  "ops": [
    {
      "kind": "create | update | resolve",
      "thread_id": "existing id or null",
      "title": "short playable thread title",
      "stakes": "what remains at risk or what worsens if ignored"
    }
  ]
}

Current scene:
<<CURRENT_SCENE>>

Player input:
<<PLAYER_INPUT>>

Resolved oracle outcome:
- kind: <<OUTCOME_KIND>>
- summary: <<OUTCOME_SUMMARY>>

Executed backend steps (may be empty):
<<EXECUTION_CONTEXT>>

Current canonical threads:
<<THREADS_JSON>>

Bounded memory context (may be empty):
<<MEMORY_CONTEXT>>
"""


class ThreadUpdateKind(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    RESOLVE = "resolve"


class GeneratedThreadUpdateOp(StrictModel):
    kind: ThreadUpdateKind
    thread_id: str | None = None
    title: str = Field(min_length=1, max_length=160)
    stakes: str = Field(default="", max_length=320)


class GeneratedThreadUpdateBatch(StrictModel):
    ops: list[GeneratedThreadUpdateOp] = Field(default_factory=list, max_length=2)


@dataclass(frozen=True)
class ThreadUpdateResult:
    touched_thread_ids: tuple[str, ...] = ()


class EmptyThreadUpdateContentError(ValueError):
    pass


def _raise_empty_thread_update_content_error() -> None:
    message = "Thread updater returned empty content."
    raise EmptyThreadUpdateContentError(message)


class ThreadUpdater:
    def __init__(
        self,
        *,
        config: NarrativeConfig | None = None,
        completion_function: CompletionFunction = _completion,
    ) -> None:
        self._config = config or NarrativeConfig.from_env()
        self._completion = completion_function

    def update_threads(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None = None,
        memory_context: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> ThreadUpdateResult:
        if not self._config.is_usable():
            return ThreadUpdateResult()

        prompt = self._build_prompt(
            state,
            player_input=player_input,
            outcome=outcome,
            execution_context=execution_context,
            memory_context=memory_context,
        )
        request = CompletionRequest(
            model=self._config.model,
            messages=[
                {"role": "system", "content": THREAD_UPDATER_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=max(self._config.max_tokens, 1800),
            timeout=self._config.timeout_seconds,
            stream=True,
            api_key=self._config.api_key,
            base_url=self._config.base_url,
            reasoning_effort="low",
            reasoning={
                "max_tokens": 700,
                "exclude": self._config.exclude_reasoning,
            },
            extra_headers=self._openrouter_headers(),
            response_format=None,
            cancel_token=cancel_token,
        )

        try:
            payload = self._complete_json(request)
            generated = GeneratedThreadUpdateBatch.model_validate_json(extract_json_object(payload))
        except ValueError:
            return ThreadUpdateResult()
        return self._apply_generated_updates(state, generated)

    def _build_prompt(
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None,
        memory_context: str | None,
    ) -> str:
        threads_json = json.dumps(
            [
                {
                    "id": thread.id,
                    "title": thread.title,
                    "status": thread.status.value,
                    "stakes": thread.stakes,
                }
                for thread in state.threads
            ],
            indent=2,
        )
        return (
            THREAD_UPDATER_USER_PROMPT_TEMPLATE.replace("<<CURRENT_SCENE>>", state.current_scene)
            .replace("<<PLAYER_INPUT>>", player_input.strip())
            .replace("<<OUTCOME_KIND>>", outcome.kind.value)
            .replace("<<OUTCOME_SUMMARY>>", outcome.summary)
            .replace("<<EXECUTION_CONTEXT>>", execution_context or "(none)")
            .replace("<<THREADS_JSON>>", threads_json)
            .replace("<<MEMORY_CONTEXT>>", memory_context or "(none)")
        )

    def _complete_json(self, request: CompletionRequest) -> str:
        last_error: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            try:
                completed = complete_text(request, self._completion)
                content_json = completed.content
                if not content_json:
                    _raise_empty_thread_update_content_error()
            except (
                *LITELLM_RETRYABLE_ERRORS,
                ValidationError,
                json.JSONDecodeError,
                EmptyThreadUpdateContentError,
                ValueError,
            ) as exc:
                last_error = exc
                if attempt < self._config.max_retries:
                    time.sleep(0.4 * (attempt + 1))
            else:
                return content_json
        message = str(last_error) if last_error else "Thread update failed."
        raise ValueError(message)

    def _apply_generated_updates(
        self,
        state: GameState,
        generated: GeneratedThreadUpdateBatch,
    ) -> ThreadUpdateResult:
        threads_by_id = {thread.id: thread for thread in state.threads}
        title_index = {_title_key(thread.title): thread.id for thread in state.threads}
        touched_ids: list[str] = []

        for op in generated.ops:
            title = op.title.strip()
            stakes = op.stakes.strip()

            if op.kind == ThreadUpdateKind.CREATE:
                existing_id = title_index.get(_title_key(title))
                if existing_id is not None:
                    touched_ids.append(existing_id)
                    continue
                created = GameThread(title=title, stakes=stakes)
                state.threads.append(created)
                threads_by_id[created.id] = created
                title_index[_title_key(created.title)] = created.id
                touched_ids.append(created.id)
                continue

            if op.thread_id is None:
                continue
            thread = threads_by_id.get(op.thread_id)
            if thread is None:
                continue

            resolved_title = self._safe_thread_title(
                proposed=title,
                current=thread,
                title_index=title_index,
            )
            prior_key = _title_key(thread.title)
            thread.title = resolved_title
            thread.stakes = stakes or thread.stakes
            if prior_key != _title_key(thread.title):
                title_index.pop(prior_key, None)
                title_index[_title_key(thread.title)] = thread.id
            if op.kind == ThreadUpdateKind.RESOLVE:
                thread.status = ThreadStatus.RESOLVED
            touched_ids.append(thread.id)

        return ThreadUpdateResult(touched_thread_ids=tuple(_dedupe_preserve_order(touched_ids)))

    def _safe_thread_title(
        self,
        *,
        proposed: str,
        current: GameThread,
        title_index: dict[str, str],
    ) -> str:
        proposed_key = _title_key(proposed)
        owner_id = title_index.get(proposed_key)
        if owner_id is not None and owner_id != current.id:
            return current.title
        return proposed

    def _openrouter_headers(self) -> dict[str, str] | None:
        if not self._config.model.startswith("openrouter/"):
            return None
        headers: dict[str, str] = {}
        if self._config.site_url is not None:
            headers["HTTP-Referer"] = self._config.site_url
        if self._config.app_name is not None:
            headers["X-Title"] = self._config.app_name
        return headers or None


def _title_key(title: str) -> str:
    return " ".join(title.lower().split())


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered
