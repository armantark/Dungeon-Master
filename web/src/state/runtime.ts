import { ApiError } from "../lib/api";
import type {
  LLMPreset,
  LLMProvider,
  LLMSettingsResponse,
} from "../lib/types";

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
