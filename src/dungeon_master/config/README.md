# Config Package

This package exists to make model/runtime tuning easy to trace without pretending every call should share one giant flat knob set.

## What Lives Here

`app.py` holds two layers of configuration:

1. `AppConfig`
   - Cross-cutting runtime settings such as `DUNGEON_MASTER_STATE_PATH`.
2. `LLMConfig`
   - Model/provider/runtime settings shared across LiteLLM calls:
     - model slug
     - API key / base URL
     - timeout / retries
     - reasoning visibility
     - narrator-facing defaults
3. `LLMProfiles`
   - Task-specific completion budgets for the concrete call sites:
     - narration
     - turn routing
     - explainer
     - thread / NPC continuity
     - Cairn structured helpers
     - character generation
     - campaign generation

That split is deliberate:

- Global runtime knobs stay in env.
- Task behavior stays in typed Python profiles so it is obvious which calls are meant to be creative vs mechanical.
- The narrator keeps its own env-facing creativity knob because that is the one setting the player is most likely to want to bias intentionally.

## Current Tuning Intent

- Narration is the most creative path. Its default temperature is higher (`1.25`) and its token budget is dedicated to prose generation rather than reused as a hidden floor for unrelated structured calls.
- Mechanical / structured interpreter calls stay low-temperature (`0.0` to `0.1`) so they behave like planners/updaters, not improv actors.
- Large JSON authoring flows (character/campaign generation) keep their own explicit budgets here instead of silently borrowing `LITELLM_MAX_TOKENS`.

## Env Surface

The supported env knobs are intentionally small:

- `OPENROUTER_API_KEY`
- `OPENROUTER_API_BASE`
- `LITELLM_MODEL`
- `LITELLM_REASONING_EFFORT`
- `LITELLM_EXCLUDE_REASONING`
- `LITELLM_NARRATION_TEMPERATURE`
- `LITELLM_NARRATION_MAX_TOKENS`
- `LITELLM_TIMEOUT_SECONDS`
- `LITELLM_MAX_RETRIES`
- `OR_APP_NAME`
- `OR_SITE_URL`
- `DUNGEON_MASTER_STATE_PATH`

Backward-compatible fallbacks remain for the older `LITELLM_TEMPERATURE` and `LITELLM_MAX_TOKENS` names, but the new names are the source of truth.

## How To Extend It

When adding a new model-backed subsystem:

1. Add a new `TaskProfile` field to `LLMProfiles`.
2. Give it a specific temperature, output budget, and reasoning shape.
3. Reference that profile from the call site instead of inlining a fresh literal bundle.

If a new knob feels like something the player should tweak frequently, that is usually a sign it belongs in the product later, not as another hidden env var.
