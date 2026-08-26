"""Typed HTTP request and response bodies."""

from __future__ import annotations

from pydantic import BaseModel, Field

from dungeon_master.campaign import CharacterDraftMode
from dungeon_master.config import CredentialSource, LLMPreset, LLMProvider
from dungeon_master.models import (
    AttackStance,
    CairnAbility,
    CairnRestKind,
    CampaignEndReason,
    CampaignSeed,
    CharacterQuiz,
    CharacterQuizAnswer,
    CharacterSheet,
    Likelihood,
)
from dungeon_master.save_library import SaveSummary


class ChaosFactorRequest(BaseModel):
    value: int = Field(ge=1, le=9)


class NotesRequest(BaseModel):
    setting_notes: str = Field(min_length=1)
    player_notes: str = Field(min_length=1)


class DirectivesRequest(BaseModel):
    world_guidance: str = ""
    play_guidance: str = ""


class CampaignSeedRequest(BaseModel):
    campaign_seed: CampaignSeed


class YesNoRequest(BaseModel):
    question: str = Field(min_length=1)
    likelihood: Likelihood


class SceneCheckRequest(BaseModel):
    expected_scene: str = Field(min_length=1)


class PlayerActionRequest(BaseModel):
    action: str = Field(min_length=1)


class PlayerTurnRequest(BaseModel):
    text: str = Field(min_length=1)


class ExplainRequest(BaseModel):
    question: str = Field(min_length=1)


class CairnSaveRequest(BaseModel):
    ability: CairnAbility
    reason: str = Field(min_length=1)


class CairnAttackRequest(BaseModel):
    target_name: str = Field(min_length=1)
    target_armor: int = Field(default=0, ge=0, le=3)
    weapon_item_id: str | None = None
    stance: AttackStance = AttackStance.NORMAL


class CairnHarmRequest(BaseModel):
    amount: int = Field(ge=0)
    source: str = Field(min_length=1)
    in_combat: bool = True
    armor_applies: bool = True


class CairnRecoveryRequest(BaseModel):
    kind: CairnRestKind


class CairnRetreatRequest(BaseModel):
    reason: str = Field(min_length=1)


class CairnAcquireRequest(BaseModel):
    text: str = Field(min_length=1)


class CairnEquipRequest(BaseModel):
    item_id: str = Field(min_length=1)
    equipped: bool = True


class CharacterDraftRequest(BaseModel):
    mode: CharacterDraftMode
    prompt: str | None = None
    template: CharacterSheet | None = None


class CharacterFinalizeRequest(BaseModel):
    character: CharacterSheet


class CampaignEndRequest(BaseModel):
    reason: CampaignEndReason
    summary: str | None = Field(default=None, min_length=1)


class CharacterTemplatesResponse(BaseModel):
    templates: list[CharacterSheet]
    thinking: str = ""


class CharacterDraftResponse(BaseModel):
    draft: CharacterSheet
    thinking: str = ""


class CharacterQuizRequest(BaseModel):
    concept: str = Field(min_length=1, max_length=2000)


class CharacterQuizResponse(BaseModel):
    quiz: CharacterQuiz
    thinking: str = ""


class ExplanationResponse(BaseModel):
    answer: str
    thinking: str = ""


class CreateSaveRequest(BaseModel):
    select: bool = True


class SelectSaveRequest(BaseModel):
    save_id: str = Field(min_length=1)


class SaveLibraryBootstrapResponse(BaseModel):
    active_save_id: str | None
    saves: list[SaveSummary]


class LLMSettingsUpdateRequest(BaseModel):
    preset: LLMPreset


class LLMCredentialsUpdateRequest(BaseModel):
    provider: LLMProvider
    api_key: str = Field(min_length=1, max_length=4096)


class LLMPresetOptionResponse(BaseModel):
    id: LLMPreset
    label: str
    description: str
    structured_model: str
    narration_model: str
    reasoning_model: str
    available: bool
    missing_env_vars: list[str] = Field(default_factory=list)


class LLMProviderCredentialResponse(BaseModel):
    id: LLMProvider
    label: str
    configured: bool
    source: CredentialSource
    masked_key: str | None = None


class LLMSettingsResponse(BaseModel):
    preset: LLMPreset
    structured_model: str
    narration_model: str
    reasoning_model: str
    presets: list[LLMPresetOptionResponse]
    needs_key: bool
    provider_credentials: list[LLMProviderCredentialResponse]


class CharacterQuizzedDraftRequest(BaseModel):
    concept: str = Field(min_length=1, max_length=2000)
    answers: list[CharacterQuizAnswer] = Field(default_factory=list)
    final_note: str | None = None


class CancelRequestResponse(BaseModel):
    cancelled: bool
