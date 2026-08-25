import { describe, expect, it, vi } from "vitest";

import { fetchSaveBinding } from "./save-binding";

describe("fetchSaveBinding", () => {
  it("returns the selected id only after its state has loaded", async () => {
    const state = { id: "state_new" } as never;
    const fetchState = vi.fn().mockResolvedValue(state);

    const binding = await fetchSaveBinding("save_new", fetchState);

    expect(fetchState).toHaveBeenCalledTimes(1);
    expect(binding).toEqual({ saveId: "save_new", state });
  });
});
