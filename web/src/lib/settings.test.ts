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
    needs_key: false,
    provider_credentials: [
      {
        id: "openrouter",
        label: "OpenRouter",
        configured: true,
        source: "env",
        masked_key: "open...1234",
      },
      {
        id: "gemini",
        label: "Gemini",
        configured: true,
        source: "env",
        masked_key: "gemi...5678",
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
    game.runtimeStatus = "checking";
    game.runtimeError = null;
    game.credentialSetupOpen = false;
    game.credentialSetupProvider = "openrouter";
    game.credentialSetupStatus = "idle";
    game.credentialSetupError = null;
  });

  it("bootstrapRuntime gates on needs_key without bootstrapping the save library", async () => {
    const payload = settingsResponse({
      needs_key: true,
      provider_credentials: [
        {
          id: "openrouter",
          label: "OpenRouter",
          configured: false,
          source: "none",
          masked_key: null,
        },
        {
          id: "gemini",
          label: "Gemini",
          configured: false,
          source: "none",
          masked_key: null,
        },
      ],
    });
    vi.spyOn(api, "getLlmSettings").mockResolvedValue(payload);
    const bootstrapSpy = vi.spyOn(game, "bootstrap").mockResolvedValue();

    await game.bootstrapRuntime();

    expect(bootstrapSpy).not.toHaveBeenCalled();
    expect(game.runtimeStatus).toBe("needs_key");
    expect(game.settings?.needs_key).toBe(true);
  });

  it("bootstrapRuntime continues into normal bootstrap when a provider is configured", async () => {
    vi.spyOn(api, "getLlmSettings").mockResolvedValue(settingsResponse());
    const bootstrapSpy = vi.spyOn(game, "bootstrap").mockResolvedValue();

    await game.bootstrapRuntime();

    expect(bootstrapSpy).toHaveBeenCalledTimes(1);
    expect(game.runtimeStatus).toBe("ready");
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

  it("saveLlmCredentials stores a key, selects the matching preset, and bootstraps", async () => {
    const byokSaved = settingsResponse({
      needs_key: false,
      provider_credentials: [
        {
          id: "openrouter",
          label: "OpenRouter",
          configured: false,
          source: "none",
          masked_key: null,
        },
        {
          id: "gemini",
          label: "Gemini",
          configured: true,
          source: "stored",
          masked_key: "gemi...1234",
        },
      ],
    });
    const switched = settingsResponse({
      preset: "gemini_split",
      structured_model: "gemini/gemini-3-flash-preview",
      narration_model: "gemini/gemini-3.1-pro-preview",
      reasoning_model: "gemini/gemini-3.1-pro-preview",
      needs_key: false,
      provider_credentials: byokSaved.provider_credentials,
    });
    const saveSpy = vi.spyOn(api, "updateLlmCredentials").mockResolvedValue(byokSaved);
    const presetSpy = vi.spyOn(api, "updateLlmSettings").mockResolvedValue(switched);
    const bootstrapSpy = vi.spyOn(game, "bootstrap").mockResolvedValue();

    const ok = await game.saveLlmCredentials("gemini", "gemini-secret");

    expect(ok).toBe(true);
    expect(saveSpy).toHaveBeenCalledWith("gemini", "gemini-secret");
    expect(presetSpy).toHaveBeenCalledWith("gemini_split");
    expect(bootstrapSpy).toHaveBeenCalledTimes(1);
    expect(game.runtimeStatus).toBe("ready");
    expect(game.settings?.preset).toBe("gemini_split");
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
