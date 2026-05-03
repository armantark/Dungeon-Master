import type { CampaignStatus, CharacterSheet } from "./types";

// "quiz" and "review" only appear inside the assist flow; once the
// player commits answers we always land in "edit". Exhaustively
// listing them keeps the Svelte template's #else-if ladder typesafe.
export type SetupMode = "choose" | "templates" | "scratch" | "quiz" | "review" | "edit";

export function deriveSetupMode(status: CampaignStatus): SetupMode {
  return status === "ready_to_start" || status === "active" ? "edit" : "choose";
}

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
      { id: `item_${crypto.randomUUID().slice(0, 8)}`, name: "Poor bundle", details: "" },
      { id: `item_${crypto.randomUUID().slice(0, 8)}`, name: "Walking staff", details: "" },
    ],
  };
}
