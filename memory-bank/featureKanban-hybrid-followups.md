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
