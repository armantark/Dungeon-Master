import { api, ApiError } from "../lib/api";
import type { GameState, LLMPreset, LLMProvider, LLMSettingsResponse } from "../lib/types";

export type LlmSettingsStatus = "idle" | "loading" | "ready" | "saving" | "error";
export type RuntimeBootstrapStatus = "checking" | "needs_key" | "ready" | "error";
export type CredentialSetupStatus = "idle" | "saving" | "error";

export interface CachedLlmSettings {
  settings: LLMSettingsResponse;
  status: LlmSettingsStatus;
  error: null;
}

export function cacheLlmSettings(response: LLMSettingsResponse): CachedLlmSettings {
  return { settings: response, status: "ready", error: null };
}

export function providerForPreset(preset: LLMPreset): LLMProvider {
  return preset === "gemini_split" ? "gemini" : "openrouter";
}

export function presetForProvider(provider: LLMProvider): LLMPreset {
  return provider === "gemini" ? "gemini_split" : "kimi";
}

export function validateApiKey(apiKey: string): string | null {
  const cleaned = apiKey.trim();
  return cleaned === "" ? null : cleaned;
}

export function formatRuntimeError(error: unknown): string {
  if (error instanceof ApiError) {
    const detail = (error.detail as { detail?: string } | undefined)?.detail;
    return detail ?? error.message;
  }
  if (error instanceof Error) return error.message;
  return "Unknown error";
}

interface RuntimeStateOwner {
  state: GameState | null;
  runtimeStatus: RuntimeBootstrapStatus;
  runtimeError: string | null;
  credentialSetupOpen: boolean;
  credentialSetupProvider: LLMProvider;
  credentialSetupStatus: CredentialSetupStatus;
  credentialSetupError: string | null;
  settingsOpen: boolean;
  settingsStatus: LlmSettingsStatus;
  settings: LLMSettingsResponse | null;
  settingsError: string | null;
  settingsSaveError: string | null;
}

/** Owns application-level readiness, credential setup, and LLM preset workflows. */
export class RuntimeSettingsWorkflow {
  readonly #owner: RuntimeStateOwner;
  readonly #bootstrapLibrary: () => Promise<void>;

  constructor(owner: RuntimeStateOwner, bootstrapLibrary: () => Promise<void>) {
    this.#owner = owner;
    this.#bootstrapLibrary = bootstrapLibrary;
  }

  async bootstrap(): Promise<void> {
    const owner = this.#owner;
    owner.runtimeStatus = "checking";
    owner.runtimeError = null;
    owner.credentialSetupError = null;
    owner.credentialSetupStatus = "idle";
    try {
      const response = await api.getLlmSettings();
      this.#cache(response);
      owner.credentialSetupProvider = providerForPreset(response.preset);
      if (response.needs_key) {
        owner.runtimeStatus = "needs_key";
        owner.state = null;
        return;
      }
      await this.#bootstrapLibrary();
      owner.runtimeStatus = "ready";
    } catch (error) {
      owner.runtimeStatus = "error";
      owner.runtimeError = formatRuntimeError(error);
      owner.settingsStatus = "error";
      owner.settingsError = owner.runtimeError;
    }
  }

  async openSettings(): Promise<void> {
    const owner = this.#owner;
    owner.settingsOpen = true;
    owner.settingsSaveError = null;
    if (owner.settings === null) owner.settingsStatus = "loading";
    try {
      this.#cache(await api.getLlmSettings());
    } catch (error) {
      owner.settingsStatus = "error";
      owner.settingsError = formatRuntimeError(error);
    }
  }

  closeSettings(): void {
    const owner = this.#owner;
    owner.settingsOpen = false;
    owner.settingsSaveError = null;
    if (owner.settingsStatus === "saving" || owner.settingsStatus === "loading") return;
    if (owner.settingsStatus === "error") owner.settingsStatus = "idle";
  }

  async updatePreset(preset: LLMPreset): Promise<boolean> {
    const owner = this.#owner;
    if (owner.settings?.preset === preset) return true;
    owner.settingsStatus = "saving";
    owner.settingsSaveError = null;
    try {
      this.#cache(await api.updateLlmSettings(preset));
      return true;
    } catch (error) {
      owner.settingsStatus = "ready";
      owner.settingsSaveError = formatRuntimeError(error);
      return false;
    }
  }

  openCredentialSetup(provider: LLMProvider): void {
    const owner = this.#owner;
    owner.credentialSetupProvider = provider;
    owner.credentialSetupError = null;
    owner.credentialSetupOpen = true;
  }

  closeCredentialSetup(): void {
    const owner = this.#owner;
    if (owner.credentialSetupStatus === "saving" || owner.runtimeStatus === "needs_key") return;
    owner.credentialSetupOpen = false;
    owner.credentialSetupError = null;
  }

  async saveCredentials(provider: LLMProvider, apiKey: string): Promise<boolean> {
    const owner = this.#owner;
    const cleaned = validateApiKey(apiKey);
    if (cleaned === null) {
      owner.credentialSetupStatus = "error";
      owner.credentialSetupError = "API key cannot be empty.";
      return false;
    }
    owner.credentialSetupStatus = "saving";
    owner.credentialSetupError = null;
    try {
      let response = await api.updateLlmCredentials(provider, cleaned);
      this.#cache(response);
      const targetPreset = presetForProvider(provider);
      if (response.preset !== targetPreset) {
        response = await api.updateLlmSettings(targetPreset);
        this.#cache(response);
      }
      owner.credentialSetupStatus = "idle";
      owner.credentialSetupOpen = false;
      await this.#bootstrapLibrary();
      owner.runtimeStatus = "ready";
      return true;
    } catch (error) {
      owner.credentialSetupStatus = "error";
      owner.credentialSetupError = formatRuntimeError(error);
      owner.runtimeStatus = "needs_key";
      return false;
    }
  }

  #cache(response: LLMSettingsResponse): void {
    const cached = cacheLlmSettings(response);
    this.#owner.settings = cached.settings;
    this.#owner.settingsStatus = cached.status;
    this.#owner.settingsError = cached.error;
  }
}
