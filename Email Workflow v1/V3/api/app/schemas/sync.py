"""Sync API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from api.app.schemas.thread import QueueSummaryResponse, ThreadResponse
from backend.domain.sync import SyncRunSummary


class SyncRequest(BaseModel):
    source: str = "anywhere"
    max_results: int = 50


class SyncStatusResponse(BaseModel):
    run_id: int
    status: str
    source: str
    stage: str
    progress_percent: int
    status_message: str
    fetched_message_count: int
    thread_count: int
    ai_thread_count: int
    completed_at: datetime | None = None
    queue_summary: QueueSummaryResponse | None = None
    error_message: str | None = None

    @classmethod
    def from_domain(cls, result: SyncRunSummary) -> "SyncStatusResponse":
        return cls(
            run_id=result.run_id,
            status=result.status.value,
            source=result.source,
            stage=result.stage.value,
            progress_percent=result.progress_percent,
            status_message=result.status_message,
            fetched_message_count=result.fetched_message_count,
            thread_count=result.thread_count,
            ai_thread_count=result.ai_thread_count,
            completed_at=result.completed_at,
            queue_summary=(
                QueueSummaryResponse.from_domain(result.queue_summary)
                if result.queue_summary
                else None
            ),
            error_message=result.error_message,
        )


class SyncResponse(SyncStatusResponse):
    threads: list[ThreadResponse] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, result: SyncRunSummary) -> "SyncResponse":
        return cls(
            run_id=result.run_id,
            status=result.status.value,
            source=result.source,
            stage=result.stage.value,
            progress_percent=result.progress_percent,
            status_message=result.status_message,
            fetched_message_count=result.fetched_message_count,
            thread_count=result.thread_count,
            ai_thread_count=result.ai_thread_count,
            completed_at=result.completed_at,
            queue_summary=(
                QueueSummaryResponse.from_domain(result.queue_summary)
                if result.queue_summary
                else None
            ),
            error_message=result.error_message,
            threads=[ThreadResponse.from_domain(thread) for thread in result.threads],
        )
