"""Canonical timing state for the streamed-turn pipeline."""

from __future__ import annotations

from dungeon_master.domain.models import StageStatus, StageTiming, utc_now
from dungeon_master.llm.narration import StreamStageStatus

TURN_STREAM_STAGE_LABELS: dict[str, str] = {
    "planning_turn": "Planning turn",
    "resolving_mechanics": "Resolving mechanics",
    "preparing_narration": "Preparing narration",
    "streaming_narration": "Streaming narration",
    "reconciling_continuity": "Reconciling continuity",
}
TURN_STREAM_STAGE_ORDER: tuple[str, ...] = tuple(TURN_STREAM_STAGE_LABELS)

_STAGE_STATUS_FROM_STREAM: dict[StreamStageStatus, StageStatus] = {
    StreamStageStatus.PENDING: StageStatus.PENDING,
    StreamStageStatus.ACTIVE: StageStatus.ACTIVE,
    StreamStageStatus.DONE: StageStatus.DONE,
    StreamStageStatus.SKIPPED: StageStatus.SKIPPED,
}


class StageTimingTracker:
    """Own persisted stage timings for one streamed turn."""

    def __init__(self) -> None:
        self._records: dict[str, StageTiming] = {}

    def record(self, stage_id: str, label: str, status: StreamStageStatus) -> None:
        persisted_status = _STAGE_STATUS_FROM_STREAM[status]
        existing = self._records.get(stage_id)
        now = utc_now()
        started = existing.started_at if existing is not None else None
        completed = existing.completed_at if existing is not None else None
        if status == StreamStageStatus.ACTIVE and started is None:
            started = now
        if status == StreamStageStatus.DONE and completed is None:
            completed = now
        self._records[stage_id] = StageTiming(
            stage_id=stage_id,
            label=label,
            status=persisted_status,
            started_at=started,
            completed_at=completed,
        )

    def snapshot(self) -> list[StageTiming]:
        return list(self._records.values())
