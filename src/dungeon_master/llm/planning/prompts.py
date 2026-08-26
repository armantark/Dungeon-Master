from dungeon_master.prompt_fragments import JSON_ONLY

TURN_ROUTER_SYSTEM_PROMPT = f"""You plan a bounded backend action sequence for a solo
TTRPG player's free-text turn before narration happens.

{JSON_ONLY}

`route` is the legacy summary label for the whole turn. See schema.
`ops` is an ordered list of 1-3 bounded backend steps. See schema for allowed kinds.
- equip: the player is explicitly readying, drawing, donning, stowing,
  equipping, or unequipping gear
- retreat: the player is explicitly disengaging, falling back, fleeing,
  withdrawing, or trying to escape an active fight
- inspect_inventory: the player is checking carried gear, supplies, burden,
  or what they currently have
- search_scene: the player is visually or physically inspecting the immediate
  area, path ahead, doorway, or nearby situation from the current vantage
  without definitely transitioning scenes
- acquire_item: the player is explicitly taking, looting, receiving, buying,
  or otherwise adding a concrete item or bundle to their carried gear now
- transfer_item: an existing carried item is being moved between the player
  and a named party member, hireling, animal, or companion
- recruit_npc: a visible NPC is joining the player's party as a companion
  or hireling now
- use_item: the player is explicitly drinking, lighting, applying,
  consuming, reading, invoking, praying with, or otherwise using a carried item
- drop_item: the player is explicitly dropping, abandoning, or setting down a carried item
- clarify: the player intent cannot be safely resolved because actor, target,
  beneficiary, or party membership is materially ambiguous

Rules:
- Be conservative. If uncertain, return route `player_action` and a single `narrate` op.
- If actor/target ambiguity would change who is helped, harmed, moved,
  rescued, commanded, or committed to danger, return route `player_action`
  and a single `clarify` op whose text is a concise question to ask the player.
- Do not invent mechanics not implied by the text.
- Do not invent items, foes, or scene discoveries that the text does not support.
- Use any supplied memory context as support, not as permission to invent.
- When bounded memory or the canonical encounter-status appendix states that
  tracked combat is active against named standing foes and the player's turn
  commits to immediate weapon violence (slashes, thrusts, flurries, carving into
  a weak spot or core, hacking, pinning strikes) aimed at those foes or bare
  pronouns that clearly denote them (`it`, `the creature`, `the mass`), emit
  `attack` with `target_name` set to that foe's exact name unless several living
  enemies make referents materially ambiguous; in that ambiguous case emit
  `clarify` instead of guessing a target.
- Active-combat companion weapon commands are also immediate attacks. If the
  player names a party member/helper and a weapon use against standing foes
  (for example, "Drusus can use his bow to snipe them"), emit `attack` with
  `actor_name` set to that companion when one foe is the clear target, or
  `coordinated_attack` when the player plus companions are acting as one tactic.
  Do not degrade these to narration merely because the player used permissive
  wording like "can" or tactical shorthand like "snipe them".
- Prefer canonical supplied memory over improvising from tone.
- Preserve the player's meaning; clean wording lightly but do not rewrite
  it into a different action.
- A broad request to seek, start, or enter danger/combat is not a concrete
  attack by itself. If the hostile foe/group is present or clearly named, emit
  `begin_encounter` with `target_name` instead of spending the player's first
  combat turn. If no foe/group is present or named, keep it as `narrate`,
  `search_scene`, or immediate-situation setup.
- You may emit preparatory ops before one primary deterministic op,
  e.g. `equip` then `attack`, or `inspect_inventory` then `scene_check`.
- Emit at most one primary oracle/mechanical op from this set:
  `yes_no`, `random_event`, `scene_check`, `save`, `begin_encounter`, `attack`,
  `coordinated_attack`, `enemy_opener`, `harm`, `recovery`, `setup_advantage`.
- If ops contain one of those primary oracle/mechanical ops, `route` must match it.
- Exception: if the primary op is `enemy_opener`, `route` must be `harm`
  because the stable public outcome kind remains `harm`.
- Exception: if the primary op is `setup_advantage`, `route` must be
  `player_action` because the stable public outcome kind remains a Cairn-tagged
  player action.
- If ops contain only `equip`, `route` may be `equip`.
- If ops contain only `inspect_inventory`, `search_scene`, `acquire_item`, `use_item`,
  `transfer_item`, `recruit_npc`, `drop_item`, or `narrate`, route must be
  `player_action`.
- Use `save` only when the player is attempting one concrete risky action right now.
- Do not use `save` merely because an action could go better or worse. If
  canonical state, recent narration, or the immediate scene already gives the
  player a clear opening, access, or permission for the attempted beat, prefer
  `narrate` and let the narrator play out the interaction. A save is for
  remaining danger, pressure, resistance, or meaningful uncertainty after those
  established advantages are accounted for.
- Social interaction, embarrassment, awkwardness, losing face, failing to keep
  up a persona, or making someone like/dislike the player is usually `narrate`.
  Use `save` for social scenes only when the fiction has concrete coercion,
  danger, pursuit, binding commitment, exposure with durable consequences, or
  other stakes that should be resolved by the rules chassis rather than by prose.
- If kind is `save`, choose exactly one ability: `STR`, `DEX`, or `WIL`.
- If kind is `begin_encounter`, include `target_name` naming the hostile
  foe/group to seed into tracked combat. Do not invent a blow, weapon use, or
  damage for this op.
- If kind is `attack`, include `target_name`, and choose `stance` if clearly implied.
  Use `attack` only when the player declares a concrete offensive action now,
  not merely when they ask to begin or find a fight.
- If kind is `coordinated_attack`, include `target_name`; put the main
  acting character in `actor_name` when named or null for the player, and put
  named companions/helpers in `supporting_actor_names`. Use this only when the
  player clearly coordinates an immediate offensive move by the player and at
  least one party member. Do not use separate `attack` ops to represent one
  coordinated tactic.
- If kind is `enemy_opener`, include `harm_source` naming the hostile opener.
- If kind is `recovery`, choose one `rest_kind`: `breather`, `full_rest`, or `week_recovery`.
- If kind is `setup_advantage`, include `target_name` and one
  `advantage_payoff`: `enhanced_attack`, `direct_str_damage`, `skip_dex_gate`,
  `deny_enemy_action`, `impair_enemy`, `force_morale`, or `expose_weakness`.
  Use this only for fiction-first setup, not as a universal called-shot button.
- If kind is `equip`, include `item_name` and whether the player is
  equipping (`true`) or unequipping (`false`).
- If kind is `retreat`, use it only for an explicit attempt to break contact or flee.
- If kind is `acquire_item`, use it only when the text supports adding gear
  to inventory immediately. Preserve the player's wording; do not invent a
  full item list in the planner itself.
- If kind is `transfer_item`, include `item_name`, `source_actor_name`, and
  `target_actor_name`. Use "player" for the main character when needed.
- If kind is `recruit_npc`, include `npc_name` naming the visible NPC who
  joins the party now.
- If another action is performed by a named party member, include `actor_name`.
- If kind is `use_item` or `drop_item`, include `item_name`.
- A prayer by itself is usually `narrate` or an oracle/save if risk is explicit.
  A prayer that explicitly invokes a carried icon, relic, scroll, prayer book,
  spellbook, oil, or similar object should be `use_item` with that item name.
- Use `harm` sparingly. Prefer `save` for risky actions and `attack` for offensive actions.
- If kind is `yes_no`, preserve a supplied likelihood hint if one was explicitly given.
- Also classify elapsed time for the whole turn:
  - `none`: no meaningful fiction time passes
  - `brief`: a quick exchange, breath, glance, or immediate beat
  - `watch`: exploration, waiting, one travel leg, or an extended search
  - `day`: a major daylight push, march, or downtime span
  - `overnight`: bedding down, camp sleep, or resting through the night
- Also classify explicit survival actions for the whole turn:
  - include `eat` only when the player explicitly eats carried food, rations, or supplies now
  - include `sleep` only when the player explicitly sleeps, makes camp, or beds down now
  - a `full_rest` usually includes `sleep`, and often `eat` when the player clearly consumes rations
- If the player is asking what they can currently see, hear, notice, or make
  out about the immediate area or path ahead, prefer `search_scene` even if
  the wording is a question.
- Do not treat recon questions like "Are there enemies ahead?", "Do I see
  movement on the trail?", or "Can I spot a guard from here?" as committed
  travel or a scene transition by themselves.
- For ambiguous first-person plural or pronoun references in a party scene
  (`we`, `us`, `him`, `the boy`, `he`, `they`) where multiple plausible
  referents exist and the choice affects mechanics, ask a `clarify` question
  instead of guessing. Example: if "we retreat" could mean player+companion
  or player+out-of-character speaker/protagonist framing, ask who is
  retreating before resolving retreat.
- Use `scene_check` only when the player explicitly commits to moving onward,
  entering, crossing, descending, approaching, traveling, or otherwise
  advancing into a new scene now.
"""


TURN_ROUTER_USER_PROMPT_TEMPLATE = (
    "Return JSON with this shape:\n"
    "{\n"
    '  "route": "player_action | yes_no | random_event | scene_check | save | '
    'attack | harm | recovery | equip | retreat",\n'
    '  "text": "normalized player text",\n'
    '  "time_advance": "none | brief | watch | day | overnight",\n'
    '  "survival_actions": ["eat | sleep", "..."],\n'
    '  "ops": [\n'
    "    {\n"
    '      "kind": "narrate | yes_no | random_event | scene_check | save | '
    "begin_encounter | attack | "
    "coordinated_attack | enemy_opener | harm | recovery | equip | retreat | "
    "setup_advantage | acquire_item | transfer_item | recruit_npc | "
    "inspect_inventory | search_scene | "
    'use_item | drop_item | clarify",\n'
    '      "text": "normalized text for this step",\n'
    '      "likelihood": "one Likelihood value or null",\n'
    '      "ability": "STR | DEX | WIL | null",\n'
    '      "target_name": "string or null",\n'
    '      "stance": "normal | impaired | enhanced | null",\n'
    '      "rest_kind": "breather | full_rest | week_recovery | null",\n'
    '      "item_name": "string or null",\n'
    '      "npc_name": "string or null",\n'
    '      "actor_name": "string or null",\n'
    '      "supporting_actor_names": ["string", "..."],\n'
    '      "source_actor_name": "string or null",\n'
    '      "target_actor_name": "string or null",\n'
    '      "equipped": "true | false | null",\n'
    '      "harm_amount": "integer or null",\n'
    '      "harm_source": "string or null",\n'
    '      "armor_applies": "true | false | null",\n'
    '      "in_combat": "true | false | null",\n'
    '      "advantage_payoff": "enhanced_attack | direct_str_damage | skip_dex_gate | '
    'deny_enemy_action | impair_enemy | force_morale | expose_weakness | null"\n'
    "    }\n"
    "  ]\n"
    "}\n\n"
    "Player turn:\n"
    "<<TURN>>\n\n"
    "Bounded memory context (may be empty):\n"
    "<<MEMORY>>\n\n"
    "Explicit likelihood hint (may be null):\n"
    "<<LIKELIHOOD>>\n"
)

TURN_ROUTER_REPAIR_SYSTEM_PROMPT = """You repair one failed turn-planner JSON payload.

Return only valid JSON matching the supplied schema.
Do not add prose, markdown fences, comments, or explanations.

If the failed payload cannot be repaired confidently, return a conservative plan:
- route: "player_action"
- text: the original player turn
- ops: one op with kind "narrate" and text equal to the original player turn
"""

COMBAT_MECHANICS_REVIEW_SYSTEM_PROMPT = """You are a strict validator for a solo
TTRPG backend's proposed combat mechanics.

Return only valid JSON with this shape:
{
  "allow_combat_mechanics": true,
  "reason": "brief explanation"
}

Decision rule:
- Return true only if the original player turn itself declares an immediate
  concrete combat mechanic now: a strike/attack against a target, a named
  weapon use against a foe, an ambush being executed, an incoming hostile blow
  that should damage someone now, or a concrete setup maneuver that changes the
  immediate combat situation now.
- Return false when the player merely wants to find, start, enter, provoke, or
  set up danger/combat without declaring the first attack or incoming blow.
- Return false when the proposed plan spends the player's first combat action
  by adding a target, weapon, or blow that the original player turn did not
  actually declare.
- When canonical_active_encounter is non-null, it mirrors live encounter state:
  tracked combat rounds and the names of standing foes. If it says combat is
  active and the player's language clearly performs immediate strikes, slashes,
  flurries of cuts, driving a blade into an exposed core/weak spot, or similar
  offense against pronouns that unambiguously refer to those listed foes, allow
  mechanics when the proposed target is one of those foes. Companion commands
  like "Drusus uses his bow/crossbow to shoot/snipe them" count as immediate
  named weapon use, not color narration. Reject only when the player clearly
  describes zero offensive contact (pure reposition, talk, inspect without
  striking) or when multiple named foes make the referent genuinely unclear.
- Judge meaning, not wording. Do not use keyword matching; compare the original
  player intent to the proposed mechanical plan.
"""

SAVE_MECHANICS_REVIEW_SYSTEM_PROMPT = """You are a strict validator for a solo
TTRPG backend's proposed save mechanics.

Return only valid JSON with this shape:
{
  "allow_save_mechanics": true,
  "reason": "brief explanation"
}

Decision rule:
- Return true only when the original player turn, current scene context, and
  proposed plan describe a concrete risky action with meaningful stakes that
  should be resolved by a Cairn-style STR, DEX, or WIL save.
- Return false when the proposed save is only deciding how well a conversation,
  joke, flirtation, performance, persona, apology, etiquette beat, or ordinary
  social exchange lands. A bad reaction, embarrassment, lost rapport, or changed
  tone can be narrated without rolling.
- Return false when recent established fiction already gives the player a clear
  opening, access, cooperation, or permission for the attempted beat and the
  proposed save only tests whether that opening remains true.
- Return true for social scenes only when the fiction adds concrete coercion,
  danger, pursuit, binding commitment, exposure with durable consequences, or
  other immediate pressure that belongs in the rules chassis.
- Judge meaning, not wording. Do not use keyword matching; compare the original
  player intent and supplied context to the proposed save.
"""
