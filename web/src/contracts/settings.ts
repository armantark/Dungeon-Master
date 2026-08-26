// Runtime model settings and credential wire contracts.

// Mirrors backend `LLMPreset` (StrEnum) in `dungeon_master/config/app.py`.
//
// We hand-mirror it as a string union (rather than e.g. importing a
// `const enum`) for the same reason as everything else on the wire:
// the API surface is small enough that one place to edit beats a
// codegen step. Keeping the union exhaustive lets the settings UI
// switch on `preset` and fail at type-check time when the backend
// grows a new option.
export type LLMPreset = "kimi" | "gemini_split";
export type LLMProvider = "openrouter" | "gemini";
export type CredentialSource = "none" | "env" | "stored";

// Mirrors `LLMPresetOptionResponse`. `available` is false when the
// preset's required env vars are missing on the server — the UI
// renders the option as a disabled card and surfaces
// `missing_env_vars` so the player knows what to add to `.env`.
export interface LLMPresetOption {
  id: LLMPreset;
  label: string;
  description: string;
  structured_model: string;
  narration_model: string;
  reasoning_model: string;
  available: boolean;
  missing_env_vars: string[];
}

export interface LLMProviderCredential {
  id: LLMProvider;
  label: string;
  configured: boolean;
  source: CredentialSource;
  masked_key: string | null;
}

// Mirrors `LLMSettingsResponse`. `structured_model` / `narration_model`
// / `reasoning_model` are the resolved per-capability LiteLLM slugs
// for the active preset — the UI shows them as a "what's running
// right now" readout next to the picker so the player can verify the
// switch took effect without diffing the .env.
export interface LLMSettingsResponse {
  preset: LLMPreset;
  structured_model: string;
  narration_model: string;
  reasoning_model: string;
  presets: LLMPresetOption[];
  needs_key: boolean;
  provider_credentials: LLMProviderCredential[];
}

// F-10 OOC rules explainer. Mirrors the backend `ExplanationResponse`.
// `thinking` is a non-empty string when the model surfaced a reasoning
// trace; `""` when the model produced none. We don't render it as an
// independent surface — the streaming `thinking_delta` events animate
// the trace inside the chat's collapsed-thinking block. The unary
// shape exists primarily so tests can assert no-mutation against the
// fallback path.
export interface ExplanationResponse {
  answer: string;
  thinking: string;
}
