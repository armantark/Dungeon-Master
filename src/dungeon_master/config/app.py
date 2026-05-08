from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

from dungeon_master.models import OracleKind

type ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "default"]
type ReasoningPolicy = ReasoningEffort | Literal["auto"]

DEFAULT_MODEL = "openrouter/moonshotai/kimi-k2.6"
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_REASONING_POLICY: ReasoningPolicy = "auto"
DEFAULT_NARRATION_TEMPERATURE = 1.25
DEFAULT_NARRATION_MAX_TOKENS = 4500
DEFAULT_TIMEOUT_SECONDS = 600.0
DEFAULT_STATE_PATH = Path("data/game_state.json")

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
        return True


@dataclass(frozen=True)
class AppConfig:
    state_path: Path
    llm: LLMConfig

    @classmethod
    def from_env(cls) -> AppConfig:
        load_dotenv()
        return cls(
            state_path=Path(_env_str("DUNGEON_MASTER_STATE_PATH", default=str(DEFAULT_STATE_PATH))),
            llm=LLMConfig.from_env(),
        )


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
