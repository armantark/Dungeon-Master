import { defaultCairnCharacterState, defaultCairnItemState } from "./cairn";
import type { CampaignStatus, CharacterSheet } from "./types";

// "quiz" and "review" only appear inside the assist flow; once the
// player commits answers we always land in "edit". Exhaustively
// listing them keeps the Svelte template's #else-if ladder typesafe.
export type SetupMode = "choose" | "templates" | "scratch" | "quiz" | "review" | "edit";

export function deriveSetupMode(status: CampaignStatus): SetupMode {
  return status === "ready_to_start" || status === "active" ? "edit" : "choose";
}

// Blank drafts seed inventory + cairn at their `unset` defaults. The
// real Cairn mechanics are derived later by the backend's one-time
// LLM-backed backfill on `finalize` / `start_campaign`; until then the
// frontend gates the Cairn block off the `source === "unset"` flag.
export function blankCharacterDraft(): CharacterSheet {
  return {
    name: "Unnamed wanderer",
    archetype: "Player-defined survivor",
    epithet: "A figure not yet pinned down by the world's cruelty.",
    backstory: "No backstory finalized yet.",
    drive: "Choose a life before the world answers it.",
    flaw: "Undefined.",
    condition: "Unrecorded.",
    inventory: [
      {
        id: `item_${crypto.randomUUID().slice(0, 8)}`,
        name: "Poor bundle",
        details: "",
        cairn: defaultCairnItemState(),
      },
      {
        id: `item_${crypto.randomUUID().slice(0, 8)}`,
        name: "Walking staff",
        details: "",
        cairn: defaultCairnItemState(),
      },
    ],
    cairn: defaultCairnCharacterState(),
  };
}
