"""Direct deterministic Cairn mechanics routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, status

from dungeon_master.models import GameState
from dungeon_master.transport.http.runtime import ServiceDep
from dungeon_master.transport.http.schemas import (
    CairnAcquireRequest,
    CairnAttackRequest,
    CairnEquipRequest,
    CairnHarmRequest,
    CairnRecoveryRequest,
    CairnRetreatRequest,
    CairnSaveRequest,
)

router = APIRouter(prefix="/cairn")


@router.post("/save", response_model=GameState)
def cairn_save(svc: ServiceDep, payload: Annotated[CairnSaveRequest, Body()]) -> GameState:
    try:
        return svc.resolve_cairn_save(payload.ability, payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/attack", response_model=GameState)
def cairn_attack(svc: ServiceDep, payload: Annotated[CairnAttackRequest, Body()]) -> GameState:
    try:
        return svc.attack_target(
            target_name=payload.target_name,
            target_armor=payload.target_armor,
            weapon_item_id=payload.weapon_item_id,
            stance=payload.stance,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/harm", response_model=GameState)
def cairn_harm(svc: ServiceDep, payload: Annotated[CairnHarmRequest, Body()]) -> GameState:
    try:
        return svc.suffer_harm(
            amount=payload.amount,
            source=payload.source,
            in_combat=payload.in_combat,
            armor_applies=payload.armor_applies,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/recover", response_model=GameState)
def cairn_recover(svc: ServiceDep, payload: Annotated[CairnRecoveryRequest, Body()]) -> GameState:
    try:
        return svc.recover_character(payload.kind)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/retreat", response_model=GameState)
def cairn_retreat(svc: ServiceDep, payload: Annotated[CairnRetreatRequest, Body()]) -> GameState:
    try:
        return svc.retreat_from_encounter(payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/acquire", response_model=GameState)
def cairn_acquire(svc: ServiceDep, payload: Annotated[CairnAcquireRequest, Body()]) -> GameState:
    try:
        return svc.acquire_inventory(payload.text)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/equip", response_model=GameState)
def cairn_equip(svc: ServiceDep, payload: Annotated[CairnEquipRequest, Body()]) -> GameState:
    try:
        return svc.set_item_equipped(item_id=payload.item_id, equipped=payload.equipped)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
