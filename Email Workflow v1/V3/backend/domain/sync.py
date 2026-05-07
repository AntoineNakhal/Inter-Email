"""Sync-related domain models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from backend.domain.analysis import QueueSummaryResult
from backend.domain.thread import EmailThread


class SyncStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class SyncStage(str, Enum):
    QUEUED = "queued"
    FETCHING = "fetching"
    PERSISTING = "persisting"
    ANALYZING = "analyzing"
    SUMMARIZING = "summarizing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class SyncRunSummary(BaseModel):
    run_id: int
    status: SyncStatus
    source: str
    stage: SyncStage = SyncStage.QUEUED
    progress_percent: int = 0
    stage_unit_current: int = 0
    stage_unit_total: int = 0
    eta_seconds: int | None = None
    status_message: str = ""
    fetched_message_count: int
    thread_count: int
    ai_thread_count: int
    cancellation_requested: bool = False
    completed_at: datetime | None = None
    queue_summary: QueueSummaryResult | None = None
    error_message: str | None = None
    threads: list[EmailThread] = Field(default_factory=list)


# SyncRunSummary contains EmailThread, which has a forward ref to ThreadOverride
# (defined in a separate module to avoid a circular import). We resolve it here
# so this module is self-contained — both the API and the worker import sync.py,
# but the worker never imports override.py, so the rebuild must happen here.
from backend.domain.override import ThreadOverride as _ThreadOverride  # noqa: E402
EmailThread.model_rebuild(_types_namespace={"ThreadOverride": _ThreadOverride})
SyncRunSummary.model_rebuild()
