# Hybrid Follow-Up Kanban

Captured from the hybrid gap-discovery conversation on 2026-05-06.

This board is intentionally narrower than `memory-bank/featureKanban.md`.
The original board stays untouched for posterity; this file only tracks the
follow-up items the user explicitly approved, accepted in principle, or
deliberately deferred for later.

## Working Rule

- Keep this board grounded in the shipped product. Ideas here should extend the
  existing chat-first, deterministic-canon architecture rather than replace it.

## Ready / Active Candidates

### H-01 Known by Sign, Not Name
- Status: `done`
- Priority: `high`
- Goal: Let recurring figures become player-visible before their true names are
  canonically known, without leaking backend-only names.
- Why:
  The current hidden/visible NPC split fixes spoiler names, but it still leaves
  a binary outcome: either a recurring figure is hidden, or they appear as a
  fully named visible NPC. That misses an important dark-fantasy middle state:
  the player may recognize a recurring figure by sign, wound, relic, habit,
  office, or omen long before they know the person's real name.
- Desired final state:
  - Important recurring figures can surface in the visible roster under a
    descriptor or epithet-like label (for example, "The ash-veiled bellringer"
    or "The split-reliquary woman") before a proper name is granted.
  - A later explicit disclosure can promote that record to a proper name without
    creating a second NPC or leaking the old hidden true name prematurely.
  - The player-visible roster remains strictly constrained by player knowledge:
    knowing someone exists does **not** imply knowing their true name.
- Constraints:
  - Backend-hidden true names must not surface unless the fiction explicitly
    grants them (direct introduction, being told, finding a clue/document,
    divination/fortunetelling, etc.).
  - This should extend the existing F-16 hidden/introduced split rather than
    replace it with an omniscient cast list.
- Candidate backend scope:
  - Add a safe descriptor-based pathway for visible recurring figures that do
    not yet have a player-known proper name.
  - Teach the NPC updater and/or post-narration reveal flow to preserve unnamed
    recurrence without leaking hidden true names.
  - Support a later deterministic or model-authored promotion from descriptor to
    explicitly granted proper name on the same canonical NPC record.
- Backend progress:
  - Landed: `NPC` now carries `player_label` plus `player_label_kind`
    (`proper_name | descriptor`), player-facing prompt/memory/audit paths render
    `display_label()` instead of canonical `name`, and committed narration can
    promote a visible descriptor NPC in-place to a proper-name label.
- Frontend progress:
  - Landed: `web/src/lib/types.ts` mirrors `player_label` /
    `player_label_kind`, `web/src/lib/npcs.ts` exposes
    `npcDisplayLabel()` / `npcKnownByDescriptor()`, and `NPCsPanel.svelte`
    now renders descriptor-visible figures by their safe player-facing label
    with a `known by sign` pip instead of implying the player knows the
    canonical name.
- Candidate frontend scope:
  - Render descriptor-based visible NPCs in the same roster surface as normal
    visible NPCs, but without implying that the descriptor is a true name.
  - Avoid visual language that makes a descriptor look like a backend-authored
    spoiler or GM-only codex entry.
- Decisions:
  - Player knowledge remains the governing rule. The backend may know more than
    the player, but the roster must never outrun canon.

### H-02 Receipt Links for Touched Threads and Visible NPCs
- Status: `done`
- Priority: `medium`
- Goal: Turn receipts into navigable continuity surfaces, not only dice-trust
  surfaces.
- Why:
  The backend now persists `referenced_thread_ids` and `referenced_npc_ids` on
  outcomes, and the frontend already uses those links indirectly for sorting and
  pulse cues in the Inspector. A turn can therefore clearly affect a thread or
  visible NPC without the receipt itself helping the player inspect that change.
- Desired final state:
  - Expanded receipts can surface small thread/NPC pills or links for entities
    the turn touched.
  - Clicking a link opens/focuses the relevant Inspector section instead of
    forcing the player to infer continuity from sort/pulse behavior alone.
  - Hidden NPCs remain protected: only already-visible NPCs may appear as
    player-facing links.
- Constraints:
  - Receipts should stay compact and legible; this is navigation help, not a
    second quest log.
  - No hidden-name leakage. If a touched NPC is not visible, omit the link.
- Candidate frontend scope:
  - Extend `MechanicalReceipt.svelte` to render touched-entity pills in the
    expanded body.
  - Reuse the existing Inspector-open / cross-component navigation patterns
    rather than inventing a new panel.
- Candidate backend scope:
  - Likely none beyond existing `OracleOutcome` linkage fields unless an extra
    "safe visible ids only" helper proves necessary.
- Backend progress:
  - Landed: `GameService` now filters persisted `referenced_npc_ids` down to the
    visible roster before save/receipt time, so frontend receipt links can treat
    outcome NPC ids as player-safe navigation targets.
- Frontend progress:
  - Landed: `MechanicalReceipt.svelte` now renders compact thread / visible-NPC
    pills in the expanded receipt body, and those pills route through a new
    store-level inspector-focus signal so clicking them opens the Inspector,
    reopens the relevant drawer, and highlights the targeted continuity card.
- Follow-up testing harness:
  - Landed: `dungeon-master-fixtures` seeds a dedicated `Fixture Bellringer`
    save that keeps a descriptor-visible NPC, visible-only receipt links, and a
    hidden abbot in one isolated browser-smoke stack, plus a `Fixture Archive`
    save for shelf/archive checks. This means H-01/H-02 can now be exercised on
    demand without mutating the live Vrtanes campaign.

## Icebox

### H-08 Cancel-to-Edit and Roll Finality
- Status: `icebox`
- Priority: `medium`
- Goal: Let the player stop an in-flight turn and recover the submitted text for
  editing, with an explicit policy for rolls that were already revealed.
- Current behavior:
  - Backend cancellation is atomic and discard-only. Partial prose, queued
    events, the working state, turn checkpoint, memory update, and any resolved
    roll are not committed.
  - Resubmitting the action creates a new plan and roll, so repeated cancellation
    can be used for save scumming.
  - The frontend clears the Composer after a user cancellation instead of
    restoring the submitted text as an editable draft.
- Design decision required:
  - Before mechanics resolve, cancellation can safely restore the editable
    draft because no outcome has been shown.
  - After mechanics resolve, unrestricted action editing conflicts with roll
    finality: the roll belongs to the resolved action and may not even use the
    same mechanic after an edit. Decide whether Stop continues to discard the
    attempt, locks the revealed mechanics and only stops/regenerates prose, or
    records abandoned attempts as part of an anti-save-scumming policy.
- Constraint: Do not partially commit a roll without a recoverable transaction
  design; canonical state, event history, checkpoints, and memory must remain
  mutually consistent.
- Revisit trigger: Before the next active-play UX pass.

### H-07 Evidence-Gated Retrieval and Prompt-Cache Audit
- Status: `icebox`
- Priority: `low`
- Goal: Measure whether vector retrieval or deliberate prompt caching would
  improve long-campaign recall, latency, or cost before adding either system.
- Current baseline:
  - `memory.json` already provides narrow structured retrieval over scene,
    thread, NPC, location, fact, open-loop, and callback records without an
    embedding index.
  - LiteLLM calls currently declare no explicit prompt-cache controls, and
    application telemetry records total prompt/completion tokens but not cache
    reads, so provider-side cache effectiveness is unproven.
- Evaluation:
  - Build a fixed long-campaign recall set and measure misses from the current
    structured retriever before testing vector or hybrid retrieval.
  - Add per-route cache-read, cost, and latency telemetry before rearranging
    prompts or opting into provider-specific cache controls.
  - Adopt vector retrieval only for demonstrated recall gaps; it remains a
    non-canonical recall aid and must never override typed campaign state.
- Revisit trigger: Sustained long-campaign recall failures or measured model
  spend/latency high enough for caching work to matter.

### H-06 Human-DM Open-Endedness Pass
- Status: `icebox`
- Priority: `low`
- Goal: Run a focused pass that makes play more open-ended and emergent like a
  human DM without giving model output direct authority over campaign state.
- Constraint: Preserve the typed commit boundary; explore broader proposals and
  novel compositions rather than arbitrary model-authored mutations.
- Companion audit: Apply the deletion test to planner, reviewer, updater, and
  operation seams before adding capability; remove complexity that is not
  earning mechanical depth, reliability, or player-visible emergence.
- Revisit trigger: Only when the user explicitly returns to this design goal.

### H-05 Capability-Specialized Model Evaluation
- Status: `icebox`
- Priority: `low`
- Goal: Evaluate a reasoning-strong model for typed/non-narrative work separately
  from a prose-specialized model selected for genuine narrative creativity.
- Why:
  Coding and reasoning benchmark optimization may not correlate with voice,
  specificity, surprise, or sustained scene-writing quality. The existing typed
  `LLMProfiles` and runtime presets already separate structured and narration
  capabilities, so this is primarily a model-selection and evaluation question,
  not a request for another runtime agentic node.
- Revisit trigger:
  Only when the user returns to active play or model-quality work. Compare models
  on a fixed scene corpus for prose quality, continuity obedience, contrived
  consequences, latency, and cost before changing the configured model.

### H-03 Narrative-Embedded Action Affordances
- Status: `icebox`
- Priority: `low`
- Goal: Explore whether action affordances could appear graphically inline with
  the narration itself, rather than only above the Composer or in the Inspector.
- Why:
  The early-mechanics-feedback idea was not compelling in its original form,
  because the player still cannot act before the narration is done. A more
  interesting long-shot idea is to embed action affordances into the flow of the
  prose itself.
- Desired final state:
  - The narration could, in principle, expose a small inline affordance or
    visual anchor for a next-step action in a way that feels native to the text.
  - The affordance would still preserve the chat-first contract instead of
    becoming a parallel action UI.
- Risks / reasons this is iceboxed:
  - Likely complex to route cleanly through the LLM and still keep deterministic
    canonical state separate from prose rendering.
  - Could easily become brittle or aesthetically noisy if the text/structure
    contract is not unusually disciplined.
  - Not urgent compared with clearer, lower-risk follow-ups.

## Later / Deferred Carryover

### H-04 Campaign Setting Seed
- Status: `later`
- Priority: `medium`
- Goal: Preserve the existing F-15 idea as a consciously deferred creation-time
  primitive rather than an immediate retrofit target.
- Why:
  The user explicitly wants this held until the next fresh campaign rather than
  landed into the current Vrtanes run.
- Decision:
  - Revisit only when the user is actually about to start a new campaign.
  - Keep the old `featureKanban.md` entry as the full design source of truth;
    this board only records the defer decision for the current moment.
