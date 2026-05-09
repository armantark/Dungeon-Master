import { afterEach, describe, expect, it, vi } from "vitest";

import { api, ApiError } from "./api";
import { game } from "./store.svelte";
import type { LLMSettingsResponse } from "./types";

// We unit-test the LLM-settings half of the store in isolation rather
// than threading it through the existing `store.test.ts` because the
// settings surface is independent of save state, streaming, and the
// chat lifecycle. Splitting the file keeps the resets minimal — we
// only have to bounce the four `settings*` fields between cases —
// and the failure messages stay scoped to "settings stuff broke."
function settingsResponse(overrides: Partial<LLMSettingsResponse> = {}): LLMSettingsResponse {
  return {
    preset: "kimi",
    structured_model: "openrouter/moonshotai/kimi-k2-thinking",
    narration_model: "openrouter/moonshotai/kimi-k2-thinking",
    reasoning_model: "openrouter/moonshotai/kimi-k2-thinking",
    presets: [
      {
        id: "kimi",
        label: "Kimi (OpenRouter)",
        description: "All-Kimi routing.",
        structured_model: "openrouter/moonshotai/kimi-k2-thinking",
        narration_model: "openrouter/moonshotai/kimi-k2-thinking",
        reasoning_model: "openrouter/moonshotai/kimi-k2-thinking",
        available: true,
        missing_env_vars: [],
      },
      {
        id: "gemini_split",
        label: "Gemini split",
        description: "Flash for tools, Pro for prose.",
        structured_model: "gemini/gemini-3-flash-preview",
        narration_model: "gemini/gemini-3.1-pro-preview",
        reasoning_model: "gemini/gemini-3.1-pro-preview",
        available: true,
        missing_env_vars: [],
      },
    ],
    ...overrides,
  };
}

describe("GameStore LLM settings", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    game.settingsOpen = false;
    game.settings = null;
    game.settingsStatus = "idle";
    game.settingsError = null;
    game.settingsSaveError = null;
  });

  it("openSettings fetches the current preset and lands ready", async () => {
    const payload = settingsResponse();
    const spy = vi.spyOn(api, "getLlmSettings").mockResolvedValue(payload);

    await game.openSettings();

    expect(spy).toHaveBeenCalledTimes(1);
    expect(game.settingsOpen).toBe(true);
    expect(game.settingsStatus).toBe("ready");
    expect(game.settings).toEqual(payload);
    expect(game.settingsError).toBeNull();
  });

  it("openSettings surfaces a load error without leaving the modal stuck on loading", async () => {
    vi.spyOn(api, "getLlmSettings").mockRejectedValue(
      new ApiError(500, "model service unreachable"),
    );

    await game.openSettings();

    expect(game.settingsOpen).toBe(true);
    expect(game.settingsStatus).toBe("error");
    expect(game.settingsError).toContain("model service unreachable");
    expect(game.settings).toBeNull();
  });

  it("openSettings keeps cached payload visible while refetching", async () => {
    // First open seeds the cache so the modal can render instantly on
    // subsequent opens. This is the optimistic-render path —
    // `settingsStatus` only flips to "loading" when there's nothing
    // cached to draw against.
    vi.spyOn(api, "getLlmSettings").mockResolvedValueOnce(settingsResponse());
    await game.openSettings();

    const refreshed = settingsResponse({ preset: "gemini_split" });
    let resolveSecond: (value: LLMSettingsResponse) => void = () => {};
    const pending = new Promise<LLMSettingsResponse>((resolve) => {
      resolveSecond = resolve;
    });
    vi.spyOn(api, "getLlmSettings").mockReturnValueOnce(pending);

    const inflight = game.openSettings();

    // While the refresh is pending the cached payload is still ready,
    // so the modal can keep rendering Kimi's card without a flash.
    expect(game.settingsStatus).toBe("ready");
    expect(game.settings?.preset).toBe("kimi");

    resolveSecond(refreshed);
    await inflight;

    expect(game.settings?.preset).toBe("gemini_split");
    expect(game.settingsStatus).toBe("ready");
  });

  it("updateLlmPreset POSTs and updates the cached payload on success", async () => {
    vi.spyOn(api, "getLlmSettings").mockResolvedValue(settingsResponse());
    await game.openSettings();

    const updated = settingsResponse({
      preset: "gemini_split",
      structured_model: "gemini/gemini-3-flash-preview",
      narration_model: "gemini/gemini-3.1-pro-preview",
      reasoning_model: "gemini/gemini-3.1-pro-preview",
    });
    const post = vi.spyOn(api, "updateLlmSettings").mockResolvedValue(updated);

    const ok = await game.updateLlmPreset("gemini_split");

    expect(ok).toBe(true);
    expect(post).toHaveBeenCalledWith("gemini_split");
    expect(game.settings).toEqual(updated);
    expect(game.settingsStatus).toBe("ready");
    expect(game.settingsSaveError).toBeNull();
  });

  it("updateLlmPreset is a no-op when the requested preset is already active", async () => {
    vi.spyOn(api, "getLlmSettings").mockResolvedValue(settingsResponse());
    await game.openSettings();
    const post = vi.spyOn(api, "updateLlmSettings");

    const ok = await game.updateLlmPreset("kimi");

    expect(ok).toBe(true);
    expect(post).not.toHaveBeenCalled();
  });

  it("updateLlmPreset surfaces the in-flight guard error without losing the cached payload", async () => {
    // The backend rejects preset swaps with HTTP 409 while a streamed
    // turn is still active. The store has to keep the cached
    // `settings` payload so the modal can still render the previous
    // selection — we just want a transient `settingsSaveError`.
    vi.spyOn(api, "getLlmSettings").mockResolvedValue(settingsResponse());
    await game.openSettings();
    vi.spyOn(api, "updateLlmSettings").mockRejectedValue(
      new ApiError(409, {
        detail: "Cannot change LLM settings while a request is still in flight.",
      }),
    );

    const ok = await game.updateLlmPreset("gemini_split");

    expect(ok).toBe(false);
    expect(game.settings?.preset).toBe("kimi");
    expect(game.settingsStatus).toBe("ready");
    expect(game.settingsSaveError).toContain("in flight");
  });

  it("closeSettings clears the modal and the stale save error", async () => {
    vi.spyOn(api, "getLlmSettings").mockResolvedValue(settingsResponse());
    await game.openSettings();
    game.settingsSaveError = "stuck error from previous attempt";

    game.closeSettings();

    expect(game.settingsOpen).toBe(false);
    expect(game.settingsSaveError).toBeNull();
    // We deliberately keep the cached payload so the next open is
    // instantaneous — verify the cache survives the close.
    expect(game.settings?.preset).toBe("kimi");
  });
});
