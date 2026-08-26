from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum

from pydantic import Field, ValidationError, model_validator

from dungeon_master.models import (
    NPC,
    CampaignStatus,
    CharacterQuiz,
    CharacterQuizOption,
    CharacterQuizQuestion,
    CharacterSheet,
    GameState,
    GameThread,
    InventoryItem,
    OracleTables,
    StrictModel,
)
from dungeon_master.narrative import LITELLM_RETRYABLE_ERRORS


class CharacterDraftMode(StrEnum):
    SCRATCH = "scratch"
    TEMPLATE = "template"


class GeneratedThread(StrictModel):
    title: str = Field(min_length=1)
    stakes: str = Field(min_length=1)


class GeneratedNPC(StrictModel):
    name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    disposition: str = Field(min_length=1)


class GeneratedInventoryItem(StrictModel):
    name: str = Field(min_length=1)
    details: str = Field(min_length=1)


class GeneratedCharacter(StrictModel):
    name: str = Field(min_length=1)
    archetype: str = Field(min_length=1)
    epithet: str = Field(min_length=1)
    backstory: str = Field(min_length=1)
    drive: str = Field(min_length=1)
    flaw: str = Field(min_length=1)
    condition: str = Field(min_length=1)
    inventory: list[GeneratedInventoryItem] = Field(min_length=2, max_length=6)

    def to_character_sheet(self) -> CharacterSheet:
        return CharacterSheet(
            name=self.name,
            archetype=self.archetype,
            epithet=self.epithet,
            backstory=self.backstory,
            drive=self.drive,
            flaw=self.flaw,
            condition=self.condition,
            inventory=[
                InventoryItem(name=item.name, details=item.details) for item in self.inventory
            ],
        )


class GeneratedCharacterTemplates(StrictModel):
    templates: list[GeneratedCharacter] = Field(min_length=4, max_length=4)


class GeneratedQuizOption(StrictModel):
    label: str = Field(min_length=1)


class GeneratedQuizQuestion(StrictModel):
    prompt: str = Field(min_length=1)
    options: list[GeneratedQuizOption] = Field(min_length=2, max_length=6)


class GeneratedCharacterQuiz(StrictModel):
    questions: list[GeneratedQuizQuestion] = Field(min_length=3, max_length=6)

    def to_quiz(self, concept: str) -> CharacterQuiz:
        return CharacterQuiz(
            concept=concept,
            questions=[
                CharacterQuizQuestion(
                    prompt=question.prompt,
                    options=[
                        CharacterQuizOption(label=option.label) for option in question.options
                    ],
                )
                for question in self.questions
            ],
        )


@dataclass(frozen=True)
class CharacterTemplatesResult:
    templates: list[CharacterSheet]
    thinking: str = ""


@dataclass(frozen=True)
class CharacterQuizResult:
    quiz: CharacterQuiz
    thinking: str = ""


@dataclass(frozen=True)
class CharacterDraftResult:
    draft: CharacterSheet
    thinking: str = ""


@dataclass(frozen=True)
class CampaignWorldResult:
    state: GameState
    thinking: str = ""


class GeneratedCampaignWorld(StrictModel):
    current_scene: str = Field(min_length=1)
    setting_notes: str = Field(min_length=1)
    threads: list[GeneratedThread] = Field(min_length=1, max_length=3)
    npcs: list[GeneratedNPC] = Field(default_factory=list, max_length=3)
    oracle_tables: OracleTables

    @model_validator(mode="before")
    @classmethod
    def normalize_bounded_lists(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        # Campaign generation is allowed to be a little generous while
        # brainstorming. Over-counting threads/NPCs should not poison the
        # whole campaign into a placeholder world; we keep the earliest
        # entries because the prompt asks the model to order by immediate
        # usefulness and fold overflow into setting_notes.
        normalized["threads"] = _truncate_list(normalized.get("threads"), max_items=3)
        normalized["npcs"] = _truncate_list(normalized.get("npcs"), max_items=3)
        return normalized

    def to_game_state(self, character: CharacterSheet) -> GameState:
        return GameState(
            current_scene=self.current_scene,
            setting_notes=self.setting_notes,
            player_notes=character.backstory,
            npc_roster_version=2,
            character=character,
            campaign_status=CampaignStatus.ACTIVE,
            threads=[
                GameThread(title=thread.title, stakes=thread.stakes) for thread in self.threads
            ],
            hidden_npcs=[
                NPC(name=npc.name, role=npc.role, disposition=npc.disposition) for npc in self.npcs
            ],
            oracle_tables=self.oracle_tables,
        )


def _truncate_list(value: object, *, max_items: int) -> object:
    if isinstance(value, list) and len(value) > max_items:
        return value[:max_items]
    return value


class CharacterGenerationError(ValueError):
    pass


class CampaignGenerationError(ValueError):
    pass


GENERATION_ERRORS = (
    CharacterGenerationError,
    CampaignGenerationError,
    ValidationError,
    json.JSONDecodeError,
    *LITELLM_RETRYABLE_ERRORS,
)
