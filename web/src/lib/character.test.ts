import { describe, expect, it } from "vitest";

import { blankCharacterDraft, deriveSetupMode } from "./character";
import { canRegenerateMessage } from "./message-actions";

describe("character setup helpers", () => {
  it("maps campaign status to setup mode", () => {
    expect(deriveSetupMode("character_creation")).toBe("choose");
    expect(deriveSetupMode("ready_to_start")).toBe("edit");
    expect(deriveSetupMode("active")).toBe("edit");
  });

  it("builds a blank draft with starter inventory", () => {
    const draft = blankCharacterDraft();
    expect(draft.archetype).toBe("Player-defined survivor");
    expect(draft.inventory).toHaveLength(2);
  });
});

describe("message actions", () => {
  it("only allows regenerate on the latest dm response", () => {
    expect(canRegenerateMessage("dm", "event_1", "event_1")).toBe(true);
    expect(canRegenerateMessage("player", "event_1", "event_1")).toBe(false);
    expect(canRegenerateMessage("dm", "event_1", "event_2")).toBe(false);
    expect(canRegenerateMessage("dm", "event_1", null)).toBe(false);
  });
});
