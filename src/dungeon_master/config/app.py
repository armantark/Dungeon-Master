from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

from dungeon_master.models import OracleKind

type ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "default"]
type ReasoningPolicy = ReasoningEffort | Literal["auto"]

DEFAULT_MODEL = "openrouter/moonshotai/kimi-k2.6"
DEFAULT_GEMINI_FLASH_MODEL = "gemini/gemini-3-flash-preview"
DEFAULT_GEMINI_PRO_MODEL = "gemini/gemini-3.1-pro-preview"
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_REASONING_POLICY: ReasoningPolicy = "auto"
DEFAULT_NARRATION_TEMPERATURE = 1.25
DEFAULT_NARRATION_MAX_TOKENS = 4500
DEFAULT_TIMEOUT_SECONDS = 600.0
DEFAULT_STATE_PATH = Path("data/game_state.json")
DEFAULT_RUNTIME_SETTINGS_PATH = Path("data/runtime_settings.json")
DEFAULT_CREDENTIALS_PATH = Path("data/llm_credentials.json")

VALID_REASONING_EFFORTS: tuple[ReasoningEffort, ...] = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "default",
)
VALID_REASONING_POLICIES: tuple[ReasoningPolicy, ...] = (*VALID_REASONING_EFFORTS, "auto")


class LLMCapability(StrEnum):
    STRUCTURED = "structured"
    NARRATION = "narration"
    REASONING = "reasoning"


class LLMPreset(StrEnum):
    KIMI = "kimi"
    GEMINI_SPLIT = "gemini_split"


class LLMProvider(StrEnum):
    OPENROUTER = "openrouter"
    GEMINI = "gemini"


class CredentialSource(StrEnum):
    NONE = "none"
    ENV = "env"
    STORED = "stored"


DEFAULT_LLM_PRESET = LLMPreset.KIMI


@dataclass(frozen=True)
class LLMRuntimeSettings:
    llm_preset: LLMPreset = DEFAULT_LLM_PRESET

    @classmethod
    def from_json_dict(cls, payload: object) -> LLMRuntimeSettings:
        if not isinstance(payload, dict):
            return cls()
        raw_preset = payload.get("llm_preset")
        if isinstance(raw_preset, str):
            try:
                return cls(llm_preset=LLMPreset(raw_preset))
            except ValueError:
                return cls()
        return cls()

    def to_json_dict(self) -> dict[str, str]:
        return {"llm_preset": self.llm_preset.value}


@dataclass(frozen=True)
class LLMPresetDescriptor:
    id: LLMPreset
    label: str
    description: str
    structured_model: str
    narration_model: str
    reasoning_model: str
    required_providers: tuple[LLMProvider, ...]

    def missing_env_vars(self, statuses: tuple[LLMProviderCredentialStatus, ...]) -> list[str]:
        status_map = {status.provider: status for status in statuses}
        return [
            " or ".join(_provider_env_groups(provider)[0])
            for provider in self.required_providers
            if not status_map[provider].configured
        ]

    def is_available(self, statuses: tuple[LLMProviderCredentialStatus, ...]) -> bool:
        status_map = {status.provider: status for status in statuses}
        return all(status_map[provider].configured for provider in self.required_providers)


@dataclass(frozen=True)
class LLMRuntimeBundle:
    settings: LLMRuntimeSettings
    structured: LLMConfig
    narration: LLMConfig
    reasoning: LLMConfig

    def for_capability(self, capability: LLMCapability) -> LLMConfig:
        if capability == LLMCapability.STRUCTURED:
            return self.structured
        if capability == LLMCapability.NARRATION:
            return self.narration
        return self.reasoning


@dataclass(frozen=True)
class LLMCredentials:
    openrouter_api_key: str | None = None
    gemini_api_key: str | None = None

    @classmethod
    def from_json_dict(cls, payload: object) -> LLMCredentials:
        if not isinstance(payload, dict):
            return cls()
        openrouter = _clean_secret(payload.get("openrouter_api_key"))
        gemini = _clean_secret(payload.get("gemini_api_key"))
        return cls(openrouter_api_key=openrouter, gemini_api_key=gemini)

    def to_json_dict(self) -> dict[str, str]:
        payload: dict[str, str] = {}
        if self.openrouter_api_key is not None:
            payload["openrouter_api_key"] = self.openrouter_api_key
        if self.gemini_api_key is not None:
            payload["gemini_api_key"] = self.gemini_api_key
        return payload

    def for_provider(self, provider: LLMProvider) -> str | None:
        if provider == LLMProvider.OPENROUTER:
            return self.openrouter_api_key
        return self.gemini_api_key

    def with_provider(self, provider: LLMProvider, api_key: str) -> LLMCredentials | None:
        cleaned = _clean_secret(api_key)
        if cleaned is None:
            return None
        if provider == LLMProvider.OPENROUTER:
            return replace(self, openrouter_api_key=cleaned)
        return replace(self, gemini_api_key=cleaned)


@dataclass(frozen=True)
class LLMProviderCredentialStatus:
    provider: LLMProvider
    label: str
    api_key: str | None
    source: CredentialSource

    @property
    def configured(self) -> bool:
        return self.api_key is not None


class RuntimeSettingsStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> LLMRuntimeSettings:
        if not self._path.exists():
            return LLMRuntimeSettings()
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return LLMRuntimeSettings()
        return LLMRuntimeSettings.from_json_dict(payload)

    def save(self, settings: LLMRuntimeSettings) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(settings.to_json_dict(), indent=2, sort_keys=True) + "\n"
        tmp_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
        tmp_path.write_text(payload, encoding="utf-8")
        tmp_path.replace(self._path)


class LLMCredentialsStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> LLMCredentials:
        if not self._path.exists():
            return LLMCredentials()
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return LLMCredentials()
        return LLMCredentials.from_json_dict(payload)

    def save(self, settings: LLMCredentials) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(settings.to_json_dict(), indent=2, sort_keys=True) + "\n"
        tmp_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
        tmp_path.write_text(payload, encoding="utf-8")
        tmp_path.replace(self._path)


@dataclass(frozen=True)
class TaskProfile:
    temperature: float
    max_tokens: int
    reasoning_effort: ReasoningEffort
    reasoning_max_tokens: int | None = None
    reasoning_exclude: bool | None = None

    def reasoning(self, *, default_exclude: bool) -> dict[str, object]:
        exclude = default_exclude if self.reasoning_exclude is None else self.reasoning_exclude
        if self.reasoning_max_tokens is not None:
            return {"max_tokens": self.reasoning_max_tokens, "exclude": exclude}
        return {"effort": self.reasoning_effort, "exclude": exclude}


def _default_narration_reasoning_by_task() -> dict[OracleKind, ReasoningEffort]:
    return {
        OracleKind.YES_NO: "minimal",
        OracleKind.PLAYER_ACTION: "minimal",
        OracleKind.RANDOM_EVENT: "low",
        OracleKind.SCENE_CHECK: "low",
        OracleKind.SAVE: "minimal",
        OracleKind.ATTACK: "minimal",
        OracleKind.HARM: "minimal",
        OracleKind.RECOVERY: "minimal",
        OracleKind.RETREAT: "minimal",
    }


def _default_narration_reasoning_budgets() -> dict[ReasoningEffort, int]:
    # OpenRouter's generic reasoning controls are not documented as a strict
    # hard cap for Kimi K2.6, so these budgets act more like guidance than an
    # absolute ceiling. Keep them large enough for short continuity reasoning,
    # but small enough to discourage full hidden drafting before prose starts.
    return {
        "minimal": 300,
        "low": 600,
        "medium": 900,
        "high": 1200,
        "xhigh": 1800,
        "default": 600,
    }


@dataclass(frozen=True)
class LLMProfiles:
    narration_temperature: float = DEFAULT_NARRATION_TEMPERATURE
    narration_max_tokens: int = DEFAULT_NARRATION_MAX_TOKENS
    narration_reasoning_by_task: dict[OracleKind, ReasoningEffort] = field(
        default_factory=_default_narration_reasoning_by_task,
    )
    narration_reasoning_budgets: dict[ReasoningEffort, int] = field(
        default_factory=_default_narration_reasoning_budgets,
    )
    explainer: TaskProfile = field(
        default_factory=lambda: TaskProfile(
            temperature=0.1,
            max_tokens=2200,
            reasoning_effort="low",
            reasoning_max_tokens=1200,
        ),
    )
    turn_router: TaskProfile = field(
        default_factory=lambda: TaskProfile(
            temperature=0.05,
            max_tokens=1600,
            reasoning_effort="minimal",
            reasoning_max_tokens=64,
            reasoning_exclude=True,
        ),
    )
    thread_updater: TaskProfile = field(
        default_factory=lambda: TaskProfile(
            temperature=0.05,
            max_tokens=1800,
            reasoning_effort="minimal",
            reasoning_max_tokens=96,
            reasoning_exclude=True,
        ),
    )
    npc_updater: TaskProfile = field(
        default_factory=lambda: TaskProfile(
            temperature=0.05,
            max_tokens=1800,
            reasoning_effort="minimal",
            reasoning_max_tokens=96,
            reasoning_exclude=True,
        ),
    )
    character_effect_updater: TaskProfile = field(
        default_factory=lambda: TaskProfile(
            temperature=0.05,
            max_tokens=1800,
            reasoning_effort="minimal",
            reasoning_max_tokens=96,
            reasoning_exclude=True,
        ),
    )
    recruitment_resolver: TaskProfile = field(
        default_factory=lambda: TaskProfile(
            temperature=0.0,
            max_tokens=800,
            reasoning_effort="minimal",
            reasoning_max_tokens=64,
            reasoning_exclude=True,
        ),
    )
    capability_oracle_guard: TaskProfile = field(
        default_factory=lambda: TaskProfile(
            temperature=0.0,
            max_tokens=900,
            reasoning_effort="minimal",
            reasoning_max_tokens=64,
            reasoning_exclude=True,
        ),
    )
    legacy_npc_repair: TaskProfile = field(
        default_factory=lambda: TaskProfile(
            temperature=0.1,
            max_tokens=2200,
            reasoning_effort="low",
            reasoning_max_tokens=900,
        ),
    )
    continuity_classifier: TaskProfile = field(
        default_factory=lambda: TaskProfile(
            temperature=0.0,
            max_tokens=16,
            reasoning_effort="low",
            reasoning_max_tokens=32,
            reasoning_exclude=True,
        ),
    )
    cairn_acquisition: TaskProfile = field(
        default_factory=lambda: TaskProfile(
            temperature=0.1,
            max_tokens=2200,
            reasoning_effort="low",
            reasoning_max_tokens=900,
        ),
    )
    cairn_backfill: TaskProfile = field(
        default_factory=lambda: TaskProfile(
            temperature=0.1,
            max_tokens=12000,
            reasoning_effort="low",
            reasoning_max_tokens=1200,
        ),
    )
    cairn_encounter_seed: TaskProfile = field(
        default_factory=lambda: TaskProfile(
            temperature=0.1,
            max_tokens=2500,
            reasoning_effort="low",
            reasoning_max_tokens=1200,
        ),
    )
    character_templates: TaskProfile = field(
        default_factory=lambda: TaskProfile(
            temperature=0.95,
            max_tokens=12000,
            reasoning_effort="medium",
        ),
    )
    character_quiz: TaskProfile = field(
        default_factory=lambda: TaskProfile(
            temperature=0.9,
            max_tokens=12000,
            reasoning_effort="low",
        ),
    )
    character_draft: TaskProfile = field(
        default_factory=lambda: TaskProfile(
            temperature=0.95,
            max_tokens=12000,
            reasoning_effort="medium",
        ),
    )
    quizzed_character_draft: TaskProfile = field(
        default_factory=lambda: TaskProfile(
            temperature=0.9,
            max_tokens=12000,
            reasoning_effort="medium",
        ),
    )
    campaign_world: TaskProfile = field(
        default_factory=lambda: TaskProfile(
            temperature=0.95,
            max_tokens=12000,
            reasoning_effort="high",
        ),
    )

    def narration_for(
        self,
        *,
        kind: OracleKind,
        reasoning_policy: ReasoningPolicy,
    ) -> TaskProfile:
        effort = (
            self.narration_reasoning_by_task[kind]
            if reasoning_policy == "auto"
            else reasoning_policy
        )
        if effort == "none":
            return TaskProfile(
                temperature=self.narration_temperature,
                max_tokens=self.narration_max_tokens,
                reasoning_effort=effort,
            )
        return TaskProfile(
            temperature=self.narration_temperature,
            max_tokens=self.narration_max_tokens,
            reasoning_effort=effort,
            reasoning_max_tokens=self.narration_reasoning_budgets.get(effort, 1500),
        )


@dataclass(frozen=True)
class LLMConfig:
    model: str
    api_key: str | None
    base_url: str | None
    reasoning_policy: ReasoningPolicy = DEFAULT_REASONING_POLICY
    exclude_reasoning: bool = False
    # These two remain top-level because the narrator is the only call path
    # that deliberately exposes an env-facing creativity knob.
    temperature: float = DEFAULT_NARRATION_TEMPERATURE
    max_tokens: int = DEFAULT_NARRATION_MAX_TOKENS
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_retries: int = 2
    app_name: str | None = None
    site_url: str | None = None
    profiles: LLMProfiles = field(default_factory=LLMProfiles)

    def __post_init__(self) -> None:
        synced_profiles = replace(
            self.profiles,
            narration_temperature=self.temperature,
            narration_max_tokens=self.max_tokens,
        )
        object.__setattr__(self, "profiles", synced_profiles)

    @classmethod
    def from_env(cls) -> LLMConfig:
        load_dotenv()
        return cls(
            model=_env_str("LITELLM_MODEL", default=DEFAULT_MODEL),
            api_key=_first_present_env(("OPENROUTER_API_KEY", "LITELLM_API_KEY")),
            base_url=_env_str("OPENROUTER_API_BASE", default=DEFAULT_OPENROUTER_BASE_URL).rstrip(
                "/",
            ),
            reasoning_policy=_reasoning_policy_from_env(),
            exclude_reasoning=_env_bool("LITELLM_EXCLUDE_REASONING", default=False),
            temperature=_env_float_first(
                ("LITELLM_NARRATION_TEMPERATURE", "LITELLM_TEMPERATURE"),
                default=DEFAULT_NARRATION_TEMPERATURE,
            ),
            max_tokens=_env_int_first(
                ("LITELLM_NARRATION_MAX_TOKENS", "LITELLM_MAX_TOKENS"),
                default=DEFAULT_NARRATION_MAX_TOKENS,
            ),
            timeout_seconds=_env_float("LITELLM_TIMEOUT_SECONDS", default=DEFAULT_TIMEOUT_SECONDS),
            max_retries=_env_int("LITELLM_MAX_RETRIES", default=2),
            app_name=os.getenv("OR_APP_NAME") or "Dungeon Master",
            site_url=os.getenv("OR_SITE_URL") or None,
        )

    def is_usable(self) -> bool:
        if not self.model:
            return False
        if self.model.startswith("openrouter/"):
            return self.api_key is not None
        if self.model.startswith("gemini/"):
            return self.api_key is not None
        return True


def describe_llm_presets() -> tuple[LLMPresetDescriptor, ...]:
    return (
        LLMPresetDescriptor(
            id=LLMPreset.KIMI,
            label="Kimi",
            description="Current OpenRouter Kimi path for every backend LLM workload.",
            structured_model=DEFAULT_MODEL,
            narration_model=DEFAULT_MODEL,
            reasoning_model=DEFAULT_MODEL,
            required_providers=(LLMProvider.OPENROUTER,),
        ),
        LLMPresetDescriptor(
            id=LLMPreset.GEMINI_SPLIT,
            label="Gemini split",
            description=(
                "Use Gemini Flash for structured routing/update work and Gemini Pro "
                "for narration plus heavier generation."
            ),
            structured_model=DEFAULT_GEMINI_FLASH_MODEL,
            narration_model=DEFAULT_GEMINI_PRO_MODEL,
            reasoning_model=DEFAULT_GEMINI_PRO_MODEL,
            required_providers=(LLMProvider.GEMINI,),
        ),
    )


def build_llm_runtime(
    settings: LLMRuntimeSettings | None = None,
    credentials: LLMCredentials | None = None,
) -> LLMRuntimeBundle:
    current = settings or LLMRuntimeSettings()
    base = LLMConfig.from_env()
    provider_statuses = resolve_provider_credentials(credentials)
    status_map = {status.provider: status for status in provider_statuses}
    if current.llm_preset == LLMPreset.GEMINI_SPLIT:
        gemini_key = status_map[LLMProvider.GEMINI].api_key
        structured = replace(
            base,
            model=DEFAULT_GEMINI_FLASH_MODEL,
            api_key=gemini_key,
            base_url=None,
            app_name=None,
            site_url=None,
        )
        pro = replace(
            base,
            model=DEFAULT_GEMINI_PRO_MODEL,
            api_key=gemini_key,
            base_url=None,
            app_name=None,
            site_url=None,
        )
        return LLMRuntimeBundle(
            settings=current,
            structured=structured,
            narration=pro,
            reasoning=pro,
        )

    kimi = replace(
        base,
        model=DEFAULT_MODEL,
        api_key=status_map[LLMProvider.OPENROUTER].api_key,
        base_url=_env_str("OPENROUTER_API_BASE", default=DEFAULT_OPENROUTER_BASE_URL).rstrip("/"),
        app_name=os.getenv("OR_APP_NAME") or "Dungeon Master",
        site_url=os.getenv("OR_SITE_URL") or None,
    )
    return LLMRuntimeBundle(
        settings=current,
        structured=kimi,
        narration=kimi,
        reasoning=kimi,
    )


def single_llm_runtime(config: LLMConfig) -> LLMRuntimeBundle:
    return LLMRuntimeBundle(
        settings=LLMRuntimeSettings(),
        structured=config,
        narration=config,
        reasoning=config,
    )


@dataclass(frozen=True)
class AppConfig:
    state_path: Path
    runtime_settings_path: Path
    credentials_path: Path
    llm: LLMConfig

    @classmethod
    def from_env(cls) -> AppConfig:
        load_dotenv()
        return cls(
            state_path=Path(_env_str("DUNGEON_MASTER_STATE_PATH", default=str(DEFAULT_STATE_PATH))),
            runtime_settings_path=Path(
                _env_str(
                    "DUNGEON_MASTER_RUNTIME_SETTINGS_PATH",
                    default=str(DEFAULT_RUNTIME_SETTINGS_PATH),
                ),
            ),
            credentials_path=Path(
                _env_str(
                    "DUNGEON_MASTER_CREDENTIALS_PATH",
                    default=str(DEFAULT_CREDENTIALS_PATH),
                ),
            ),
            llm=LLMConfig.from_env(),
        )


def resolve_provider_credentials(
    credentials: LLMCredentials | None = None,
) -> tuple[LLMProviderCredentialStatus, ...]:
    stored = credentials or LLMCredentials()
    return tuple(_provider_status(provider, stored) for provider in LLMProvider)


def _provider_status(
    provider: LLMProvider,
    credentials: LLMCredentials,
) -> LLMProviderCredentialStatus:
    stored_secret = credentials.for_provider(provider)
    if stored_secret is not None:
        return LLMProviderCredentialStatus(
            provider=provider,
            label=_provider_label(provider),
            api_key=stored_secret,
            source=CredentialSource.STORED,
        )
    env_secret = _first_present_env(_provider_env_groups(provider)[0])
    if env_secret is not None:
        return LLMProviderCredentialStatus(
            provider=provider,
            label=_provider_label(provider),
            api_key=env_secret,
            source=CredentialSource.ENV,
        )
    return LLMProviderCredentialStatus(
        provider=provider,
        label=_provider_label(provider),
        api_key=None,
        source=CredentialSource.NONE,
    )


def _provider_label(provider: LLMProvider) -> str:
    if provider == LLMProvider.OPENROUTER:
        return "OpenRouter"
    return "Gemini"


def _provider_env_groups(provider: LLMProvider) -> tuple[tuple[str, ...], ...]:
    if provider == LLMProvider.OPENROUTER:
        return (("OPENROUTER_API_KEY", "LITELLM_API_KEY"),)
    return (("GEMINI_API_KEY", "GOOGLE_API_KEY", "LITELLM_API_KEY"),)


def _clean_secret(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _first_present_env(names: tuple[str, ...]) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def _env_str(name: str, *, default: str) -> str:
    value = os.getenv(name)
    if value:
        return value
    return default


def _env_bool(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, *, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_float_first(names: tuple[str, ...], *, default: float) -> float:
    for name in names:
        value = os.getenv(name)
        if value is None or not value.strip():
            continue
        try:
            return float(value)
        except ValueError:
            continue
    return default


def _env_int(name: str, *, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_int_first(names: tuple[str, ...], *, default: int) -> int:
    for name in names:
        value = os.getenv(name)
        if value is None or not value.strip():
            continue
        try:
            return int(value)
        except ValueError:
            continue
    return default


def _reasoning_policy_from_env() -> ReasoningPolicy:
    value = os.getenv("LITELLM_REASONING_EFFORT", DEFAULT_REASONING_POLICY)
    if value not in VALID_REASONING_POLICIES:
        return DEFAULT_REASONING_POLICY
    return value
