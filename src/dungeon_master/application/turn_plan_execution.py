from __future__ import annotations

import json

from pydantic import ValidationError

from dungeon_master.application.cancellation import CancellationToken
from dungeon_master.application.service_models import (
    MIN_COORDINATED_ATTACK_PARTICIPANTS,
    PLAYER_ACTOR_ALIASES,
    RECENT_NPC_CONTEXT_LIMIT,
    RECENT_RECRUITMENT_SCENE_CONTEXT_LIMIT,
    RECRUITMENT_RESOLVER_SYSTEM_PROMPT,
    ClarificationPrompt,
    ExecutedTurn,
    GuardedYesNoOutcome,
    RecruitmentResolution,
    ServiceActor,
)
from dungeon_master.application.service_ports import CairnPort, CapabilityOracleGuardPort
from dungeon_master.config import LLMRuntimeBundle
from dungeon_master.domain.models import (
    NPC,
    AttackStance,
    CairnResolution,
    CairnRestKind,
    CairnSurvivalAction,
    CairnTimeAdvance,
    CharacterSheet,
    GameState,
    Likelihood,
    NPCStatus,
    OracleKind,
    OracleOutcome,
    PartyMember,
    SceneStatus,
)
from dungeon_master.llm.narration import (
    LITELLM_RETRYABLE_ERRORS,
    CompletionRequest,
    NarrativeConfig,
    _completion,
    complete_text,
    extract_json_object,
)
from dungeon_master.llm.planning import PlannedTurnOp, PlannedTurnOpKind, TurnPlan
from dungeon_master.mechanics.engine import AttackActor, SurvivalUpdate
from dungeon_master.mechanics.oracle import OracleEngine


class TurnPlanExecutor:
    """Resolve a typed turn plan without reaching through the service facade."""

    def __init__(
        self,
        *,
        cairn: CairnPort,
        oracle: OracleEngine,
        capability_oracle_guard: CapabilityOracleGuardPort,
        llm_runtime: LLMRuntimeBundle,
    ) -> None:
        self._cairn = cairn
        self._oracle = oracle
        self._capability_oracle_guard = capability_oracle_guard
        self._llm_runtime = llm_runtime

    def resolve_yes_no(
        self,
        state: GameState,
        *,
        question: str,
        likelihood: Likelihood,
        cancel_token: CancellationToken | None = None,
    ) -> GuardedYesNoOutcome:
        guarded = self._capability_oracle_guard.guard_yes_no(
            state,
            question=question,
            requested_likelihood=likelihood,
            cancel_token=cancel_token,
        )
        if guarded.outcome is not None:
            return GuardedYesNoOutcome(
                outcome=guarded.outcome,
                execution_context=guarded.execution_summary,
            )
        resolved_likelihood = guarded.likelihood or likelihood
        outcome = self._oracle.ask_yes_no(state, question, resolved_likelihood)
        return GuardedYesNoOutcome(
            outcome=outcome,
            execution_context=guarded.execution_summary,
        )

    def apply_scene_transition(
        self,
        state: GameState,
        expected_scene: str,
        status: SceneStatus,
    ) -> None:
        previous_label = state.current_scene
        previous_status = state.scene_status
        next_label = self._scene_text(expected_scene, status)
        state.scene_status = status
        state.current_scene = next_label
        if (
            _normalize_scene_label(previous_label) != _normalize_scene_label(next_label)
            or previous_status != status
        ):
            state.scene_number += 1

    def execute(  # noqa: PLR0912, PLR0915, C901
        self,
        state: GameState,
        plan: TurnPlan,
        *,
        cancel_token: CancellationToken | None = None,
    ) -> ExecutedTurn:
        step_summaries: list[str] = []
        primary_outcome: OracleOutcome | None = None
        oracle_title: str | None = None
        survival_update: SurvivalUpdate | None = None

        for op in plan.ops:
            if op.kind == PlannedTurnOpKind.INSPECT_INVENTORY:
                step_summaries.append(self._inspect_inventory_summary(state))
                continue

            if op.kind == PlannedTurnOpKind.SEARCH_SCENE:
                step_summaries.append(self._search_scene_summary(op.text))
                continue

            if op.kind == PlannedTurnOpKind.ACQUIRE_ITEM:
                actor = self._character_for_actor_name(state, op.actor_name)
                step_summaries.append(
                    self._cairn.acquire_items(
                        state,
                        text=op.text,
                        actor_id=None if actor.is_player else actor.id,
                        cancel_token=cancel_token,
                    ),
                )
                continue

            if op.kind == PlannedTurnOpKind.USE_ITEM and op.item_name is not None:
                actor = self._character_for_actor_name(state, op.actor_name)
                item_id = self.require_item_id_from_name(actor.sheet, op.item_name)
                item_outcome = self._cairn.use_item(
                    state,
                    item_id=item_id,
                    intent=op.text,
                    actor_id=None if actor.is_player else actor.id,
                )
                if primary_outcome is None:
                    primary_outcome = item_outcome
                    oracle_title = "Item use"
                step_summaries.append(item_outcome.summary)
                continue

            if op.kind == PlannedTurnOpKind.DROP_ITEM and op.item_name is not None:
                actor = self._character_for_actor_name(state, op.actor_name)
                item_id = self.require_item_id_from_name(actor.sheet, op.item_name)
                step_summaries.append(
                    self._cairn.drop_item(
                        state,
                        item_id=item_id,
                        actor_id=None if actor.is_player else actor.id,
                    ),
                )
                continue

            if op.kind == PlannedTurnOpKind.TRANSFER_ITEM and op.item_name is not None:
                step_summaries.append(
                    self._transfer_item_between_actors(
                        state,
                        item_name=op.item_name,
                        source_actor_name=op.source_actor_name,
                        target_actor_name=op.target_actor_name,
                    ),
                )
                continue

            if op.kind == PlannedTurnOpKind.RECRUIT_NPC and op.npc_name is not None:
                step_summaries.append(
                    self._recruit_npc_to_party(
                        state,
                        npc_name=op.npc_name,
                        player_input=plan.text,
                        cancel_token=cancel_token,
                    ),
                )
                continue

            if op.kind == PlannedTurnOpKind.EQUIP and op.item_name is not None:
                actor = self._character_for_actor_name(state, op.actor_name)
                item_id = self.require_item_id_from_name(actor.sheet, op.item_name)
                equipped = True if op.equipped is None else op.equipped
                self._cairn.set_item_equipped(
                    state,
                    item_id=item_id,
                    equipped=equipped,
                    actor_id=None if actor.is_player else actor.id,
                )
                actor_context = "" if actor.is_player else f" for {actor.name}"
                step_summaries.append(
                    f"Equipment updated{actor_context}: {op.item_name} "
                    f"{'equipped' if equipped else 'unequipped'}.",
                )
                continue

            if op.kind == PlannedTurnOpKind.YES_NO:
                likelihood = op.likelihood or Likelihood.EVEN
                guarded = self.resolve_yes_no(
                    state,
                    question=op.text,
                    likelihood=likelihood,
                    cancel_token=cancel_token,
                )
                primary_outcome = guarded.outcome
                oracle_title = "Oracle answer"
                step_summaries.append(f"Oracle resolved: {primary_outcome.summary}")
                if guarded.execution_context is not None:
                    step_summaries.append(guarded.execution_context)
                continue

            if op.kind == PlannedTurnOpKind.RANDOM_EVENT:
                primary_outcome = self._oracle.generate_random_event(state)
                oracle_title = "Random event"
                step_summaries.append(f"Oracle resolved: {primary_outcome.summary}")
                continue

            if op.kind == PlannedTurnOpKind.SCENE_CHECK:
                primary_outcome = self._oracle.check_scene(state, op.text)
                if primary_outcome.scene_status is not None:
                    self.apply_scene_transition(state, op.text, primary_outcome.scene_status)
                oracle_title = "Scene check"
                step_summaries.append(f"Scene resolved: {primary_outcome.summary}")
                continue

            if op.kind == PlannedTurnOpKind.SAVE and op.ability is not None:
                actor = self._character_for_actor_name(state, op.actor_name)
                primary_outcome = self._cairn.resolve_save(
                    state,
                    op.ability,
                    op.text,
                    actor_id=None if actor.is_player else actor.id,
                )
                oracle_title = "Cairn save"
                step_summaries.append(f"Save resolved: {primary_outcome.summary}")
                continue

            if op.kind == PlannedTurnOpKind.BEGIN_ENCOUNTER and op.target_name is not None:
                primary_outcome = self._cairn.begin_encounter(
                    state,
                    target_name=op.target_name,
                    text=op.text,
                    cancel_token=cancel_token,
                )
                oracle_title = "Encounter started"
                step_summaries.append(f"Encounter started: {primary_outcome.summary}")
                continue

            if op.kind == PlannedTurnOpKind.ATTACK and op.target_name is not None:
                actor = self._character_for_actor_name(state, op.actor_name)
                primary_outcome = self._cairn.resolve_attack(
                    state,
                    target_name=op.target_name,
                    target_armor=0,
                    weapon_item_id=self.item_id_from_name(actor.sheet, op.item_name),
                    stance=op.stance or AttackStance.NORMAL,
                    actor_id=None if actor.is_player else actor.id,
                    cancel_token=cancel_token,
                )
                oracle_title = "Attack resolution"
                step_summaries.append(f"Attack resolved: {primary_outcome.summary}")
                continue

            if op.kind == PlannedTurnOpKind.COORDINATED_ATTACK and op.target_name is not None:
                participants = self._coordinated_attack_participants(state, op)
                primary_outcome = self._cairn.resolve_coordinated_attack(
                    state,
                    target_name=op.target_name,
                    target_armor=0,
                    participants=participants,
                    cancel_token=cancel_token,
                )
                oracle_title = "Coordinated attack"
                step_summaries.append(f"Coordinated attack resolved: {primary_outcome.summary}")
                continue

            if (
                op.kind == PlannedTurnOpKind.SETUP_ADVANTAGE
                and op.target_name is not None
                and op.advantage_payoff is not None
            ):
                actor = self._character_for_actor_name(state, op.actor_name)
                primary_outcome = self._cairn.setup_advantage(
                    state,
                    target_name=op.target_name,
                    setup=op.text,
                    payoff=op.advantage_payoff,
                    actor_id=None if actor.is_player else actor.id,
                    cancel_token=cancel_token,
                )
                oracle_title = "Advantage setup"
                step_summaries.append(f"Advantage setup resolved: {primary_outcome.summary}")
                continue

            if op.kind == PlannedTurnOpKind.HARM:
                actor = self._character_for_actor_name(state, op.actor_name)
                primary_outcome = self._cairn.suffer_harm(
                    state,
                    amount=op.harm_amount or 1,
                    source=op.harm_source or op.text,
                    in_combat=op.in_combat if op.in_combat is not None else True,
                    armor_applies=(op.armor_applies if op.armor_applies is not None else True),
                    actor_id=None if actor.is_player else actor.id,
                )
                oracle_title = "Harm resolution"
                step_summaries.append(f"Harm resolved: {primary_outcome.summary}")
                continue

            if op.kind == PlannedTurnOpKind.ENEMY_OPENER:
                primary_outcome = self._cairn.resolve_enemy_opener(
                    state,
                    source=op.harm_source or op.target_name or op.text,
                    text=op.text,
                    cancel_token=cancel_token,
                )
                oracle_title = "Ambush resolution"
                step_summaries.append(f"Ambush resolved: {primary_outcome.summary}")
                continue

            if op.kind == PlannedTurnOpKind.RECOVERY and op.rest_kind is not None:
                actor = self._character_for_actor_name(state, op.actor_name)
                survival_update = self.advance_survival_for_rest(
                    state,
                    kind=op.rest_kind,
                    actor=actor,
                    time_advance=plan.time_advance,
                    actions=plan.survival_actions,
                )
                if survival_update is not None:
                    step_summaries.append(survival_update.summary)
                primary_outcome = self._cairn.recover(
                    state,
                    op.rest_kind,
                    actor_id=None if actor.is_player else actor.id,
                )
                oracle_title = "Recovery"
                step_summaries.append(f"Recovery resolved: {primary_outcome.summary}")
                continue

            if op.kind == PlannedTurnOpKind.RETREAT:
                primary_outcome = self._cairn.resolve_retreat(state, op.text)
                oracle_title = "Retreat resolution"
                step_summaries.append(f"Retreat resolved: {primary_outcome.summary}")
                continue

        if survival_update is None:
            survival_update = self._advance_survival_for_plan(state, plan=plan)
            if survival_update is not None:
                step_summaries.append(survival_update.summary)
        if primary_outcome is None:
            summary = self._player_action_plan_summary(step_summaries)
            primary_outcome = OracleOutcome(
                kind=OracleKind.PLAYER_ACTION,
                summary=summary,
                chaos_factor=state.chaos_factor,
            )
        if survival_update is not None:
            primary_outcome.cairn = self.merge_cairn_resolution(
                primary_outcome.cairn,
                survival_update.resolution,
            )
        execution_context = self.format_execution_context(step_summaries)
        return ExecutedTurn(
            outcome=primary_outcome,
            oracle_title=oracle_title,
            execution_context=execution_context,
        )

    def is_recon_lookup(self, plan: TurnPlan) -> bool:
        return any(op.kind == PlannedTurnOpKind.SEARCH_SCENE for op in plan.ops) and all(
            op.kind in (PlannedTurnOpKind.SEARCH_SCENE, PlannedTurnOpKind.NARRATE)
            for op in plan.ops
        )

    def clarification_prompt(self, plan: TurnPlan) -> ClarificationPrompt | None:
        for op in plan.ops:
            if op.kind == PlannedTurnOpKind.CLARIFY:
                return ClarificationPrompt(question=op.text)
        return None

    def _inspect_inventory_summary(self, state: GameState) -> str:
        inventory = state.character.inventory
        names = ", ".join(item.name for item in inventory) if inventory else "nothing"
        return (
            f"Checked carried gear ({state.character.cairn.slots_used}/"
            f"{state.character.cairn.slots_total} slots): {names}."
        )

    def _transfer_item_between_actors(
        self,
        state: GameState,
        *,
        item_name: str,
        source_actor_name: str | None,
        target_actor_name: str | None,
    ) -> str:
        source = self._character_for_actor_name(state, source_actor_name)
        target = self._character_for_actor_name(state, target_actor_name)
        item_id = self.require_item_id_from_name(source.sheet, item_name)
        return self._cairn.transfer_item(
            state,
            item_id=item_id,
            source_actor_id=None if source.is_player else source.id,
            target_actor_id=None if target.is_player else target.id,
        )

    def _recruit_npc_to_party(
        self,
        state: GameState,
        *,
        npc_name: str,
        player_input: str,
        cancel_token: CancellationToken | None,
    ) -> str:
        npc = self._require_visible_npc_for_recruitment(
            state,
            npc_name=npc_name,
            player_input=player_input,
            cancel_token=cancel_token,
        )
        if any(member.npc_id == npc.id and member.active for member in state.party_members):
            message = f"{npc.display_label()} is already in the party."
            raise ValueError(message)
        authored = CharacterSheet(
            name=npc.display_label(),
            archetype=npc.role or "Companion",
            epithet=npc.disposition,
            backstory=(
                f"{npc.display_label()} was recruited from the current NPC roster. "
                f"Role: {npc.role or 'unknown'}. Disposition: {npc.disposition}.\n\n"
                "Recent player-visible context for this recruit:\n"
                + self._recent_visible_context_for_npc(state, npc)
            ),
            drive="Survive with the party and honor the terms of recruitment.",
            flaw="Has loyalties and limits beyond the player character's control.",
            condition="Able to travel.",
        )
        sheet = self._cairn.backfill_companion_sheet(
            state,
            authored,
            cancel_token=cancel_token,
        )
        member = PartyMember(
            sheet=sheet,
            npc_id=npc.id,
            loyalty=npc.disposition,
            notes=f"Recruited from visible NPC roster entry {npc.id}.",
        )
        state.party_members.append(member)
        npc.status = NPCStatus.RETIRED
        return f"Recruited {member.display_label()} into the party."

    def _require_visible_npc_for_recruitment(
        self,
        state: GameState,
        *,
        npc_name: str,
        player_input: str,
        cancel_token: CancellationToken | None,
    ) -> NPC:
        npc = self._visible_npc_by_name(state, npc_name)
        if npc is not None:
            return npc
        npc = self._resolve_recruitment_npc_with_model(
            state,
            npc_name=npc_name,
            player_input=player_input,
            cancel_token=cancel_token,
        )
        if npc is not None:
            return npc
        message = f"Unknown visible NPC: {npc_name}"
        raise ValueError(message)

    def _resolve_recruitment_npc_with_model(
        self,
        state: GameState,
        *,
        npc_name: str,
        player_input: str,
        cancel_token: CancellationToken | None,
    ) -> NPC | None:
        config = self._llm_runtime.structured
        if not config.is_usable():
            return None
        active_npcs = [npc for npc in state.npcs if npc.status == NPCStatus.ACTIVE]
        if not active_npcs:
            return None
        payload = {
            "planner_npc_name": npc_name,
            "player_turn": player_input,
            "current_scene": state.current_scene,
            "visible_npcs": [
                {
                    "npc_id": npc.id,
                    "display_label": npc.display_label(),
                    "canonical_name": npc.name,
                    "player_label_kind": npc.player_label_kind.value,
                    "role": npc.role,
                    "disposition": npc.disposition,
                }
                for npc in active_npcs
            ],
            "recent_visible_transcript": self._recent_recruitment_context(state),
        }
        profile = config.profiles.recruitment_resolver
        request = CompletionRequest(
            model=config.model,
            messages=[
                {"role": "system", "content": RECRUITMENT_RESOLVER_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload)},
            ],
            temperature=profile.temperature,
            max_tokens=profile.max_tokens,
            timeout=config.timeout_seconds,
            stream=True,
            api_key=config.api_key,
            base_url=config.base_url,
            reasoning_effort=profile.reasoning_effort,
            reasoning=profile.reasoning(default_exclude=config.exclude_reasoning),
            extra_headers=self._openrouter_headers(config),
            response_format=None,
            cancel_token=cancel_token,
            trace_route="service.recruitment_resolver",
            trace_profile="recruitment_resolver",
        )
        try:
            completed = complete_text(request, _completion)
            parsed = RecruitmentResolution.model_validate_json(
                extract_json_object(completed.content),
            )
        except (
            *LITELLM_RETRYABLE_ERRORS,
            ValidationError,
            json.JSONDecodeError,
            ValueError,
        ):
            return None
        if parsed.npc_id is None:
            return None
        return next((npc for npc in active_npcs if npc.id == parsed.npc_id), None)

    def _recent_recruitment_context(self, state: GameState) -> str:
        snippets: list[str] = []
        for event in reversed(state.action_log):
            content = event.content.strip()
            if not content:
                continue
            snippets.append(f"- {event.title}: {self._clip_context_line(content, 420)}")
            if len(snippets) >= RECENT_RECRUITMENT_SCENE_CONTEXT_LIMIT:
                break
        if not snippets:
            return "(No recent visible transcript context.)"
        return "\n".join(reversed(snippets))

    def _openrouter_headers(self, config: NarrativeConfig) -> dict[str, str] | None:
        if not config.model.startswith("openrouter/"):
            return None
        headers: dict[str, str] = {}
        if config.site_url is not None:
            headers["HTTP-Referer"] = config.site_url
        if config.app_name is not None:
            headers["X-Title"] = config.app_name
        return headers or None

    def _recent_visible_context_for_npc(self, state: GameState, npc: NPC) -> str:
        labels = {
            npc.display_label().strip().lower(),
            npc.name.strip().lower(),
        }
        labels.discard("")
        direct_snippets: list[str] = []
        recent_snippets: list[str] = []
        for event in reversed(state.action_log):
            content = event.content.strip()
            if not content:
                continue
            snippet = f"- {event.title}: {self._clip_context_line(content, 420)}"
            if len(recent_snippets) < RECENT_RECRUITMENT_SCENE_CONTEXT_LIMIT:
                recent_snippets.append(snippet)
            lowered = content.lower()
            if (
                len(direct_snippets) < RECENT_NPC_CONTEXT_LIMIT
                and labels
                and any(label in lowered for label in labels)
            ):
                direct_snippets.append(snippet)
            if (
                len(direct_snippets) >= RECENT_NPC_CONTEXT_LIMIT
                and len(recent_snippets) >= RECENT_RECRUITMENT_SCENE_CONTEXT_LIMIT
            ):
                break
        sections: list[str] = []
        if direct_snippets:
            sections.append("Direct mentions:\n" + "\n".join(reversed(direct_snippets)))
        direct_snippet_set = set(direct_snippets)
        unmatched_recent_snippets = [
            snippet for snippet in reversed(recent_snippets) if snippet not in direct_snippet_set
        ]
        if not unmatched_recent_snippets:
            unmatched_recent_snippets = list(reversed(recent_snippets))
        if unmatched_recent_snippets:
            sections.append(
                "Recent visible transcript window:\n" + "\n".join(unmatched_recent_snippets)
            )
        if sections:
            return "\n\n".join(sections)
        return "(No recent visible transcript context found for this recruit.)"

    def _clip_context_line(self, text: str, limit: int) -> str:
        compact = " ".join(text.split())
        if len(compact) <= limit:
            return compact
        return compact[: limit - 3].rstrip() + "..."

    def _require_visible_npc_by_name(self, state: GameState, npc_name: str) -> NPC:
        npc = self._visible_npc_by_name(state, npc_name)
        if npc is not None:
            return npc
        message = f"Unknown visible NPC: {npc_name}"
        raise ValueError(message)

    def _visible_npc_by_name(self, state: GameState, npc_name: str) -> NPC | None:
        cleaned = npc_name.strip().lower()
        for npc in state.npcs:
            label = npc.display_label()
            candidates = {npc.id.lower(), npc.name.lower(), label.lower()}
            if cleaned in candidates or cleaned in label.lower() or label.lower() in cleaned:
                if npc.status != NPCStatus.ACTIVE:
                    message = f"NPC is not active: {label}"
                    raise ValueError(message)
                return npc
        return None

    def _character_for_actor_name(
        self,
        state: GameState,
        actor_name: str | None,
    ) -> ServiceActor:
        cleaned = (actor_name or "").strip().lower()
        if (
            not cleaned
            or cleaned in PLAYER_ACTOR_ALIASES
            or cleaned == state.character.name.lower()
        ):
            return ServiceActor(
                id="player",
                name=state.character.name,
                sheet=state.character,
                is_player=True,
            )
        for member in state.party_members:
            label = member.display_label()
            label_lower = label.lower()
            sheet_name = member.sheet.name.lower()
            if cleaned in {member.id.lower(), label_lower, sheet_name}:
                return ServiceActor(
                    id=member.id,
                    name=label,
                    sheet=member.sheet,
                    is_player=False,
                )
            if cleaned in label_lower or label_lower in cleaned:
                return ServiceActor(
                    id=member.id,
                    name=label,
                    sheet=member.sheet,
                    is_player=False,
                )
        message = f"Unknown party actor: {actor_name}"
        raise ValueError(message)

    def _coordinated_attack_participants(
        self,
        state: GameState,
        op: PlannedTurnOp,
    ) -> tuple[AttackActor, ...]:
        lead = self._character_for_actor_name(state, op.actor_name)
        participants: list[ServiceActor] = [lead]
        seen_ids = {lead.id}
        for name in op.supporting_actor_names:
            actor = self._character_for_actor_name(state, name)
            if actor.id in seen_ids:
                continue
            participants.append(actor)
            seen_ids.add(actor.id)
        if len(participants) < MIN_COORDINATED_ATTACK_PARTICIPANTS:
            message = "Coordinated attack requires the player and at least one party member."
            raise ValueError(message)
        return tuple(
            AttackActor(
                id=None if actor.is_player else actor.id,
                name=actor.name,
                sheet=actor.sheet,
                weapon_item_id=self.item_id_from_name(actor.sheet, op.item_name),
                stance=op.stance or AttackStance.NORMAL,
            )
            for actor in participants
        )

    def _rest_survival_defaults(
        self,
        kind: CairnRestKind,
    ) -> tuple[CairnTimeAdvance, tuple[CairnSurvivalAction, ...], int]:
        if kind == CairnRestKind.BREATHER:
            return (CairnTimeAdvance.BRIEF, (), 0)
        if kind == CairnRestKind.FULL_REST:
            return (
                CairnTimeAdvance.OVERNIGHT,
                (CairnSurvivalAction.EAT, CairnSurvivalAction.SLEEP),
                0,
            )
        return (
            CairnTimeAdvance.OVERNIGHT,
            (CairnSurvivalAction.EAT, CairnSurvivalAction.SLEEP),
            6,
        )

    def advance_survival_for_rest(
        self,
        state: GameState,
        *,
        kind: CairnRestKind,
        actor: ServiceActor | None = None,
        time_advance: CairnTimeAdvance | None = None,
        actions: tuple[CairnSurvivalAction, ...] = (),
    ) -> SurvivalUpdate | None:
        default_time_advance, default_actions, extra_days = self._rest_survival_defaults(kind)
        resolved_time_advance = (
            default_time_advance
            if time_advance is None
            or (time_advance == CairnTimeAdvance.NONE and kind != CairnRestKind.BREATHER)
            else time_advance
        )
        resolved_actions = actions or default_actions
        if (
            resolved_time_advance in (CairnTimeAdvance.NONE, CairnTimeAdvance.BRIEF)
            and not resolved_actions
            and extra_days == 0
        ):
            return None
        actor_id = None if actor is None or actor.is_player else actor.id
        return self._cairn.advance_survival_clock(
            state,
            time_advance=resolved_time_advance,
            actions=resolved_actions,
            actor_id=actor_id,
            extra_days=extra_days,
        )

    def _advance_survival_for_plan(
        self,
        state: GameState,
        *,
        plan: TurnPlan,
    ) -> SurvivalUpdate | None:
        if (
            plan.time_advance in (CairnTimeAdvance.NONE, CairnTimeAdvance.BRIEF)
            and not plan.survival_actions
        ):
            return None
        return self._cairn.advance_survival_clock(
            state,
            time_advance=plan.time_advance,
            actions=plan.survival_actions,
        )

    def merge_cairn_resolution(
        self,
        base: CairnResolution | None,
        update: CairnResolution,
    ) -> CairnResolution:
        if base is None:
            return update
        merged = base.model_dump()
        merged.update(update.model_dump(exclude_none=True, exclude_defaults=True))
        if base.resource_deltas or update.resource_deltas:
            merged["resource_deltas"] = [*base.resource_deltas, *update.resource_deltas]
        return CairnResolution.model_validate(merged)

    def _search_scene_summary(self, step_text: str) -> str:
        return (
            f"Surveyed the immediate scene from the current vantage without advancing: {step_text}."
        )

    def _player_action_plan_summary(self, step_summaries: list[str]) -> str:
        if not step_summaries:
            return "Narrative continuation requested without an oracle roll."
        if len(step_summaries) == 1:
            return step_summaries[0]
        return "Plan executed without an oracle roll: " + " ".join(step_summaries)

    def format_execution_context(self, step_summaries: list[str]) -> str | None:
        if not step_summaries:
            return None
        return "Executed backend steps:\n" + "\n".join(f"- {summary}" for summary in step_summaries)

    def _scene_text(self, expected_scene: str, status: SceneStatus) -> str:
        if status == SceneStatus.EXPECTED:
            return expected_scene
        if status == SceneStatus.ALTERED:
            return f"Altered: {expected_scene}"
        return f"Interrupted before: {expected_scene}"

    def item_id_from_name(
        self,
        character: CharacterSheet,
        item_name: str | None,
    ) -> str | None:
        if item_name is None:
            return None
        cleaned = item_name.strip().lower()
        if not cleaned:
            return None
        min_token_length = 3
        cleaned_tokens = {token for token in cleaned.split() if len(token) >= min_token_length}
        best_id: str | None = None
        best_score = 0
        for item in character.inventory:
            name = item.name.lower()
            if cleaned == name or cleaned in name or name in cleaned:
                return item.id
            name_tokens = {token for token in name.split() if len(token) >= min_token_length}
            if not cleaned_tokens or not name_tokens:
                continue
            overlap = len(cleaned_tokens & name_tokens)
            if overlap > best_score:
                best_score = overlap
                best_id = item.id
        return best_id

    def require_item_id_from_name(self, character: CharacterSheet, item_name: str) -> str:
        item_id = self.item_id_from_name(character, item_name)
        if item_id is not None:
            return item_id
        message = f"Unknown inventory item: {item_name}"
        raise ValueError(message)


def _normalize_scene_label(text: str) -> str:
    normalized = text.strip().lower()
    if normalized.startswith("altered:"):
        return normalized.removeprefix("altered:").strip()
    if normalized.startswith("interrupted before:"):
        return normalized.removeprefix("interrupted before:").strip()
    return normalized
