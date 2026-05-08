from __future__ import annotations

import json
import time
from dataclasses import dataclass
from enum import StrEnum

from pydantic import Field, ValidationError

from dungeon_master.cancel import CancellationToken
from dungeon_master.models import (
    NPC,
    GameState,
    NPCPlayerLabelKind,
    NPCStatus,
    OracleOutcome,
    StrictModel,
)
from dungeon_master.narrative import (
    LITELLM_RETRYABLE_ERRORS,
    CompletionFunction,
    CompletionRequest,
    NarrativeConfig,
    _completion,
    complete_text,
    extract_json_object,
)

NPC_UPDATER_SYSTEM_PROMPT = """You update the canonical recurring NPC cast for a solo
tabletop role-playing game after a turn has already resolved.

Return only valid JSON.

Hard rules:
- You may emit 0-2 NPC ops total.
- NPC ops may only be: create, update, retire.
- Only create an NPC when the turn introduces or clarifies a recurring person
  who should remain in the campaign cast beyond the immediate beat.
- `name` is the backend canonical identity. It may stay hidden from the player.
- `player_label` is the safe player-facing label if the NPC is visible.
- `player_label_kind` must be `proper_name` or `descriptor`.
- Do NOT reveal or invent a proper-name `player_label` unless the supplied
  context explicitly grants that name to the player (direct introduction,
  being told, a clue, divination/fortunetelling, etc.).
- If the player should know the figure only by signs, office, clothing, scars,
  or some other non-name identifier, set `player_label_kind="descriptor"` and
  use that descriptor as `player_label`.
- Prefer updating an existing NPC over creating a near-duplicate.
- Retire an NPC only when the supplied outcome + executed steps make them leave
  the active cast, become irrelevant to the current recurring roster, or die in
  a way that should stop them appearing as an active NPC.
- Never delete NPCs.
- Never invent new facts beyond the supplied player input, oracle outcome,
  executed backend steps, current NPC list, and memory context.
- For update/retire, use an exact supplied npc_id from the current NPC list.
- Keep NPC names stable and concise; do not overwrite a name unless the new
  supplied name is clearly the same person or a better canonical rendering.
- Use role/disposition to reflect promotion, allegiance shifts, suspicion,
  wounds, revealed identity, or social changes.
- `player_visible=true` means the NPC should appear in the player's visible
  recurring roster now.
- `player_visible=false` means the NPC remains backend-only hidden cast.
"""

NPC_UPDATER_USER_PROMPT_TEMPLATE = """Return JSON with this shape:
{
  "ops": [
    {
      "kind": "create | update | retire",
      "npc_id": "existing id or null",
      "name": "backend canonical npc identity",
      "player_label": "safe player-facing label or null to keep the current one",
      "player_label_kind": "proper_name | descriptor | null to keep the current kind",
      "role": "short role or function",
      "disposition": "short disposition toward the player or current situation",
      "player_visible": true
    }
  ]
}

Current scene:
<<CURRENT_SCENE>>

Campaign directives (may be empty):
<<DIRECTIVES>>

Player input:
<<PLAYER_INPUT>>

Resolved oracle outcome:
- kind: <<OUTCOME_KIND>>
- summary: <<OUTCOME_SUMMARY>>

Executed backend steps (may be empty):
<<EXECUTION_CONTEXT>>

Current canonical NPCs:
<<NPCS_JSON>>

Bounded memory context (may be empty):
<<MEMORY_CONTEXT>>
"""

LEGACY_NPC_REPAIR_SYSTEM_PROMPT = """You are repairing the recurring NPC roster for an
already-running solo tabletop RPG save after a schema change.

Return only valid JSON.

Goal:
- `introduced` = recurring people the player has clearly encountered or would
  clearly know from committed narration/current scene/player context.
- `hidden` = recurring off-stage or secret figures the backend may track for
  continuity but the player should not see in the visible roster yet.

Hard rules:
- Return 0-4 `introduced` NPCs and 0-4 `hidden` NPCs.
- Prefer reusing existing seeded NPC names when they still fit.
- You may replace bad opener-seed NPCs if the committed context clearly points
  at better recurring figures.
- `name` is canonical backend identity; `player_label` is what the player sees.
- Do NOT surface a proper-name `player_label` in `introduced` unless the
  committed context explicitly grants that name to the player. If the recurring
  figure is clearly important but still unnamed in canon, prefer a descriptor
  `player_label` and mark `player_label_kind="descriptor"` rather than leaking
  a backend-only true name.
- Do not output duplicate names across the two lists.
- If no recurring introduced figure is justified yet, `introduced` may be empty.
"""

LEGACY_NPC_REPAIR_USER_PROMPT_TEMPLATE = """Return JSON with this shape:
{
  "introduced": [
    {
      "name": "backend canonical name",
      "player_label": "safe player-facing label",
      "player_label_kind": "proper_name | descriptor",
      "role": "role",
      "disposition": "disposition"
    }
  ],
  "hidden": [
    {
      "name": "backend canonical name",
      "player_label": "optional future-facing label or null",
      "player_label_kind": "proper_name | descriptor | null",
      "role": "role",
      "disposition": "disposition"
    }
  ]
}

Current scene:
<<CURRENT_SCENE>>

Campaign directives (may be empty):
<<DIRECTIVES>>

Setting notes:
<<SETTING_NOTES>>

Player notes:
<<PLAYER_NOTES>>

Existing seeded NPCs:
<<EXISTING_NPCS>>

Recent committed transcript excerpts:
<<RECENT_TRANSCRIPT>>

Bounded memory context (may be empty):
<<MEMORY_CONTEXT>>
"""


class NPCUpdateKind(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    RETIRE = "retire"


class GeneratedNPCUpdateOp(StrictModel):
    kind: NPCUpdateKind
    npc_id: str | None = None
    name: str = Field(min_length=1, max_length=160)
    player_label: str | None = Field(default=None, max_length=160)
    player_label_kind: NPCPlayerLabelKind | None = None
    role: str = Field(default="", max_length=160)
    disposition: str = Field(default="", max_length=160)
    player_visible: bool = True


class GeneratedNPCUpdateBatch(StrictModel):
    ops: list[GeneratedNPCUpdateOp] = Field(default_factory=list, max_length=2)


class GeneratedLegacyRosterNPC(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    player_label: str | None = Field(default=None, max_length=160)
    player_label_kind: NPCPlayerLabelKind | None = None
    role: str = Field(default="", max_length=160)
    disposition: str = Field(default="", max_length=160)


class GeneratedLegacyNPCRepair(StrictModel):
    introduced: list[GeneratedLegacyRosterNPC] = Field(default_factory=list, max_length=4)
    hidden: list[GeneratedLegacyRosterNPC] = Field(default_factory=list, max_length=4)


@dataclass(frozen=True)
class NPCUpdateResult:
    touched_npc_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class LegacyNPCRosterRepairResult:
    introduced_npcs: tuple[NPC, ...] = ()
    hidden_npcs: tuple[NPC, ...] = ()


class EmptyNPCUpdateContentError(ValueError):
    pass


def _raise_empty_npc_update_content_error() -> None:
    message = "NPC updater returned empty content."
    raise EmptyNPCUpdateContentError(message)


class NPCUpdater:
    def __init__(
        self,
        *,
        config: NarrativeConfig | None = None,
        completion_function: CompletionFunction = _completion,
    ) -> None:
        self._config = config or NarrativeConfig.from_env()
        self._completion = completion_function

    def update_npcs(  # noqa: PLR0913
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None = None,
        memory_context: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> NPCUpdateResult:
        if not self._config.is_usable():
            return NPCUpdateResult()

        prompt = self._build_prompt(
            state,
            player_input=player_input,
            outcome=outcome,
            execution_context=execution_context,
            memory_context=memory_context,
        )
        update_profile = self._config.profiles.npc_updater
        request = CompletionRequest(
            model=self._config.model,
            messages=[
                {"role": "system", "content": NPC_UPDATER_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=update_profile.temperature,
            max_tokens=update_profile.max_tokens,
            timeout=self._config.timeout_seconds,
            stream=True,
            api_key=self._config.api_key,
            base_url=self._config.base_url,
            reasoning_effort=update_profile.reasoning_effort,
            reasoning=update_profile.reasoning(default_exclude=self._config.exclude_reasoning),
            extra_headers=self._openrouter_headers(),
            response_format=None,
            cancel_token=cancel_token,
            trace_route="npc_updater.apply",
            trace_profile="npc_updater",
        )

        try:
            payload = self._complete_json(request)
            generated = GeneratedNPCUpdateBatch.model_validate_json(extract_json_object(payload))
        except ValueError:
            return NPCUpdateResult()
        return self._apply_generated_updates(state, generated)

    def reseed_legacy_roster(
        self,
        state: GameState,
        *,
        memory_context: str | None = None,
        cancel_token: CancellationToken | None = None,
        use_model: bool = False,
    ) -> LegacyNPCRosterRepairResult:
        if not use_model or not self._config.is_usable():
            return self._fallback_legacy_roster(state)

        prompt = self._build_legacy_repair_prompt(state, memory_context=memory_context)
        repair_profile = self._config.profiles.legacy_npc_repair
        request = CompletionRequest(
            model=self._config.model,
            messages=[
                {"role": "system", "content": LEGACY_NPC_REPAIR_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=repair_profile.temperature,
            max_tokens=repair_profile.max_tokens,
            timeout=self._config.timeout_seconds,
            stream=True,
            api_key=self._config.api_key,
            base_url=self._config.base_url,
            reasoning_effort=repair_profile.reasoning_effort,
            reasoning=repair_profile.reasoning(default_exclude=self._config.exclude_reasoning),
            extra_headers=self._openrouter_headers(),
            response_format=None,
            cancel_token=cancel_token,
            trace_route="npc_updater.legacy_repair",
            trace_profile="legacy_npc_repair",
        )
        try:
            payload = self._complete_json(request)
            generated = GeneratedLegacyNPCRepair.model_validate_json(
                extract_json_object(payload),
            )
            return self._legacy_result_from_generated(state, generated)
        except ValueError:
            return self._fallback_legacy_roster(state)

    def _build_prompt(
        self,
        state: GameState,
        *,
        player_input: str,
        outcome: OracleOutcome,
        execution_context: str | None,
        memory_context: str | None,
    ) -> str:
        introduced_ids = {npc.id for npc in state.npcs}
        npcs_json = json.dumps(
            [
                {
                    "id": npc.id,
                    "name": npc.name,
                    "player_label": npc.display_label(),
                    "player_label_kind": npc.player_label_kind.value,
                    "role": npc.role,
                    "disposition": npc.disposition,
                    "status": npc.status.value,
                    "player_visible": npc.id in introduced_ids,
                }
                for npc in state.all_npcs()
            ],
            indent=2,
        )
        return (
            NPC_UPDATER_USER_PROMPT_TEMPLATE.replace("<<CURRENT_SCENE>>", state.current_scene)
            .replace("<<DIRECTIVES>>", self._directives_prompt_block(state))
            .replace("<<PLAYER_INPUT>>", player_input.strip())
            .replace("<<OUTCOME_KIND>>", outcome.kind.value)
            .replace("<<OUTCOME_SUMMARY>>", outcome.summary)
            .replace("<<EXECUTION_CONTEXT>>", execution_context or "(none)")
            .replace("<<NPCS_JSON>>", npcs_json)
            .replace("<<MEMORY_CONTEXT>>", memory_context or "(none)")
        )

    def _build_legacy_repair_prompt(
        self,
        state: GameState,
        *,
        memory_context: str | None,
    ) -> str:
        visible_ids = {npc.id for npc in state.npcs}
        existing_npcs = "\n".join(
            _legacy_roster_line(npc, player_visible=npc.id in visible_ids)
            for npc in state.all_npcs()
        ) or "(none)"
        return (
            LEGACY_NPC_REPAIR_USER_PROMPT_TEMPLATE.replace("<<CURRENT_SCENE>>", state.current_scene)
            .replace("<<DIRECTIVES>>", self._directives_prompt_block(state))
            .replace("<<SETTING_NOTES>>", state.setting_notes)
            .replace("<<PLAYER_NOTES>>", state.player_notes)
            .replace("<<EXISTING_NPCS>>", existing_npcs)
            .replace("<<RECENT_TRANSCRIPT>>", self._recent_transcript_excerpt(state))
            .replace("<<MEMORY_CONTEXT>>", memory_context or "(none)")
        )

    def _complete_json(self, request: CompletionRequest) -> str:
        last_error: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            try:
                completed = complete_text(request, self._completion)
                content_json = completed.content
                if not content_json:
                    _raise_empty_npc_update_content_error()
            except (
                *LITELLM_RETRYABLE_ERRORS,
                ValidationError,
                json.JSONDecodeError,
                EmptyNPCUpdateContentError,
                ValueError,
            ) as exc:
                last_error = exc
                if attempt < self._config.max_retries:
                    time.sleep(0.4 * (attempt + 1))
            else:
                return content_json
        message = str(last_error) if last_error else "NPC update failed."
        raise ValueError(message)

    def _apply_generated_updates(  # noqa: C901
        self,
        state: GameState,
        generated: GeneratedNPCUpdateBatch,
    ) -> NPCUpdateResult:
        npcs_by_id = {npc.id: npc for npc in state.all_npcs()}
        name_index = {_name_key(npc.name): npc.id for npc in state.all_npcs()}
        touched_ids: list[str] = []

        for op in generated.ops:
            name = op.name.strip()
            role = op.role.strip()
            disposition = op.disposition.strip()

            if op.kind == NPCUpdateKind.CREATE:
                existing_id = name_index.get(_name_key(name))
                if existing_id is not None:
                    existing = npcs_by_id[existing_id]
                    existing.status = NPCStatus.ACTIVE
                    if role:
                        existing.role = role
                    if disposition:
                        existing.disposition = disposition
                    (
                        existing.player_label,
                        existing.player_label_kind,
                    ) = self._resolved_player_identity(
                        current=existing,
                        canonical_name=existing.name,
                        proposed_player_label=op.player_label,
                        proposed_player_label_kind=op.player_label_kind,
                        role=role,
                    )
                    self._place_npc(state, existing, player_visible=op.player_visible)
                    touched_ids.append(existing_id)
                    continue
                player_label, player_label_kind = self._resolved_player_identity(
                    current=None,
                    canonical_name=name,
                    proposed_player_label=op.player_label,
                    proposed_player_label_kind=op.player_label_kind,
                    role=role,
                )
                created = NPC(
                    name=name,
                    role=role,
                    disposition=disposition or "unknown",
                    player_label=player_label,
                    player_label_kind=player_label_kind,
                )
                self._place_npc(state, created, player_visible=op.player_visible)
                npcs_by_id[created.id] = created
                name_index[_name_key(created.name)] = created.id
                touched_ids.append(created.id)
                continue

            if op.npc_id is None:
                continue
            npc = npcs_by_id.get(op.npc_id)
            if npc is None:
                continue

            resolved_name = self._safe_npc_name(
                proposed=name,
                current=npc,
                name_index=name_index,
            )
            prior_key = _name_key(npc.name)
            npc.name = resolved_name
            if role:
                npc.role = role
            if disposition:
                npc.disposition = disposition
            (
                npc.player_label,
                npc.player_label_kind,
            ) = self._resolved_player_identity(
                current=npc,
                canonical_name=resolved_name,
                proposed_player_label=op.player_label,
                proposed_player_label_kind=op.player_label_kind,
                role=role,
            )
            if prior_key != _name_key(npc.name):
                name_index.pop(prior_key, None)
                name_index[_name_key(npc.name)] = npc.id
            if op.kind == NPCUpdateKind.RETIRE:
                npc.status = NPCStatus.RETIRED
            else:
                npc.status = NPCStatus.ACTIVE
            self._place_npc(state, npc, player_visible=op.player_visible)
            touched_ids.append(npc.id)

        return NPCUpdateResult(touched_npc_ids=tuple(_dedupe_preserve_order(touched_ids)))

    def _legacy_result_from_generated(
        self,
        state: GameState,
        generated: GeneratedLegacyNPCRepair,
    ) -> LegacyNPCRosterRepairResult:
        introduced: list[NPC] = []
        hidden: list[NPC] = []
        existing_by_name = {
            _name_key(npc.name): npc.model_copy(deep=True)
            for npc in state.all_npcs()
        }
        seen_names: set[str] = set()
        for candidate in generated.introduced:
            key = _name_key(candidate.name)
            if key in seen_names:
                continue
            seen_names.add(key)
            npc = existing_by_name.get(key, NPC(name=candidate.name.strip()))
            npc.name = candidate.name.strip()
            npc.role = candidate.role.strip()
            npc.disposition = candidate.disposition.strip() or "unknown"
            npc.player_label, npc.player_label_kind = self._resolved_player_identity(
                current=npc,
                canonical_name=npc.name,
                proposed_player_label=candidate.player_label,
                proposed_player_label_kind=candidate.player_label_kind,
                role=npc.role,
            )
            introduced.append(npc)
        for candidate in generated.hidden:
            key = _name_key(candidate.name)
            if key in seen_names:
                continue
            seen_names.add(key)
            npc = existing_by_name.get(key, NPC(name=candidate.name.strip()))
            npc.name = candidate.name.strip()
            npc.role = candidate.role.strip()
            npc.disposition = candidate.disposition.strip() or "unknown"
            npc.player_label, npc.player_label_kind = self._resolved_player_identity(
                current=npc,
                canonical_name=npc.name,
                proposed_player_label=candidate.player_label,
                proposed_player_label_kind=candidate.player_label_kind,
                role=npc.role,
            )
            hidden.append(npc)
        return LegacyNPCRosterRepairResult(
            introduced_npcs=tuple(introduced),
            hidden_npcs=tuple(hidden),
        )

    def _fallback_legacy_roster(self, state: GameState) -> LegacyNPCRosterRepairResult:
        transcript = self._recent_transcript_excerpt(state).lower()
        introduced: list[NPC] = []
        hidden: list[NPC] = []
        for npc in state.npcs:
            clone = npc.model_copy(deep=True)
            if _name_key(clone.name) and _name_key(clone.name) in transcript:
                introduced.append(clone)
            else:
                hidden.append(clone)
        hidden.extend(npc.model_copy(deep=True) for npc in state.hidden_npcs)
        return LegacyNPCRosterRepairResult(
            introduced_npcs=tuple(_dedupe_npcs_by_name(introduced)),
            hidden_npcs=tuple(_dedupe_npcs_by_name(hidden)),
        )

    def _recent_transcript_excerpt(self, state: GameState) -> str:
        chunks: list[str] = [state.current_scene, state.player_notes]
        chunks.extend(event.content for event in state.action_log[-8:])
        chunks.extend(outcome.summary for outcome in state.oracle_history[-5:])
        return "\n".join(chunk for chunk in chunks if chunk.strip())

    def _directives_prompt_block(self, state: GameState) -> str:
        lines: list[str] = []
        if state.directives.world_guidance.strip():
            lines.append(f"World guidance: {state.directives.world_guidance.strip()}")
        if state.directives.play_guidance.strip():
            lines.append(f"Play guidance: {state.directives.play_guidance.strip()}")
        return "\n".join(lines) or "(none)"

    def _place_npc(self, state: GameState, npc: NPC, *, player_visible: bool) -> None:
        if player_visible:
            state.hidden_npcs = [
                existing for existing in state.hidden_npcs if existing.id != npc.id
            ]
            if not any(existing.id == npc.id for existing in state.npcs):
                state.npcs.append(npc)
        else:
            state.npcs = [existing for existing in state.npcs if existing.id != npc.id]
            if not any(existing.id == npc.id for existing in state.hidden_npcs):
                state.hidden_npcs.append(npc)

    def _safe_npc_name(
        self,
        *,
        proposed: str,
        current: NPC,
        name_index: dict[str, str],
    ) -> str:
        proposed_key = _name_key(proposed)
        owner_id = name_index.get(proposed_key)
        if owner_id is not None and owner_id != current.id:
            return current.name
        return proposed

    def _resolved_player_identity(
        self,
        *,
        current: NPC | None,
        canonical_name: str,
        proposed_player_label: str | None,
        proposed_player_label_kind: NPCPlayerLabelKind | None,
        role: str,
    ) -> tuple[str, NPCPlayerLabelKind]:
        label_kind = proposed_player_label_kind or (
            current.player_label_kind if current is not None else NPCPlayerLabelKind.PROPER_NAME
        )
        cleaned_label = _clean_optional_text(proposed_player_label)
        if cleaned_label is not None:
            return cleaned_label, label_kind
        if label_kind == NPCPlayerLabelKind.PROPER_NAME:
            return canonical_name, label_kind
        if current is not None and current.player_label_kind == NPCPlayerLabelKind.DESCRIPTOR:
            existing_label = _clean_optional_text(current.player_label)
            if existing_label is not None:
                return existing_label, label_kind
        fallback_label = _clean_optional_text(role)
        if fallback_label is not None:
            return fallback_label, label_kind
        return "Unnamed recurring figure", label_kind

    def _openrouter_headers(self) -> dict[str, str] | None:
        if not self._config.model.startswith("openrouter/"):
            return None
        headers: dict[str, str] = {}
        if self._config.site_url is not None:
            headers["HTTP-Referer"] = self._config.site_url
        if self._config.app_name is not None:
            headers["X-Title"] = self._config.app_name
        return headers or None


def _name_key(name: str) -> str:
    return " ".join(name.lower().split())


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _legacy_roster_line(npc: NPC, *, player_visible: bool) -> str:
    visibility = "visible" if player_visible else "hidden"
    return (
        f"- canonical: {npc.name}; player label: {npc.display_label()}"
        f" ({npc.player_label_kind.value}); visibility: {visibility}; "
        f"role: {npc.role or 'no role'}; disposition: {npc.disposition}"
    )


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _dedupe_npcs_by_name(values: list[NPC]) -> list[NPC]:
    seen: set[str] = set()
    ordered: list[NPC] = []
    for value in values:
        key = _name_key(value.name)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(value)
    return ordered
