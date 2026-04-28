"""Sync run persistence helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.analysis import QueueSummaryResult
from backend.domain.sync import SyncRunSummary, SyncStage, SyncStatus
from backend.persistence.models.sync_run import SyncRunModel


class SyncRepository:
    """Repository for workflow run metadata."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def start_run(self, source: str) -> SyncRunModel:
        model = SyncRunModel(status=SyncStatus.RUNNING.value, source=source)
        self.session.add(model)
        self.session.flush()
        return model

    def get_run_model(self, run_id: int) -> SyncRunModel | None:
        return self.session.get(SyncRunModel, run_id)

    def get_run(self, run_id: int) -> SyncRunSummary | None:
        model = self.get_run_model(run_id)
        return self._to_summary(model) if model else None

    def get_latest_run(self) -> SyncRunSummary | None:
        model = self.session.scalar(
            select(SyncRunModel).order_by(SyncRunModel.id.desc()).limit(1)
        )
        return self._to_summary(model) if model else None

    def delete_all(self) -> None:
        models = self.session.scalars(select(SyncRunModel)).all()
        for model in models:
            self.session.delete(model)
        self.session.flush()

    def complete_run(
        self,
        run: SyncRunModel,
        status: SyncStatus,
        fetched_message_count: int,
        thread_count: int,
        ai_thread_count: int,
        queue_summary: QueueSummaryResult | None = None,
        error_message: str | None = None,
    ) -> SyncRunSummary:
        run.status = status.value
        run.fetched_message_count = fetched_message_count
        run.thread_count = thread_count
        run.ai_thread_count = ai_thread_count
        run.completed_at = datetime.now(timezone.utc)
        run.error_message = error_message
        run.queue_summary_json = json.dumps(
            queue_summary.model_dump(mode="json") if queue_summary else {},
            ensure_ascii=False,
        )
        self.session.flush()
        return SyncRunSummary(
            run_id=run.id,
            status=status,
            source=run.source,
            stage=(
                SyncStage.COMPLETED
                if status == SyncStatus.COMPLETED
                else SyncStage.CANCELLED
                if status == SyncStatus.CANCELLED
                else SyncStage.FAILED
            ),
            progress_percent=100,
            status_message=(
                "Inbox refresh complete."
                if status == SyncStatus.COMPLETED
                else "Inbox refresh cancelled."
                if status == SyncStatus.CANCELLED
                else "Inbox refresh failed."
            ),
            fetched_message_count=fetched_message_count,
            thread_count=thread_count,
            ai_thread_count=ai_thread_count,
            cancellation_requested=False,
            completed_at=run.completed_at,
            queue_summary=queue_summary,
            error_message=error_message,
        )

    def _to_summary(self, model: SyncRunModel) -> SyncRunSummary:
        queue_summary_payload = {}
        if model.queue_summary_json:
            try:
                queue_summary_payload = json.loads(model.queue_summary_json)
            except json.JSONDecodeError:
                queue_summary_payload = {}

        status = SyncStatus(model.status)
        return SyncRunSummary(
            run_id=model.id,
            status=status,
            source=model.source,
            stage=(
                SyncStage.COMPLETED
                if status == SyncStatus.COMPLETED
                else SyncStage.CANCELLED
                if status == SyncStatus.CANCELLED
                else SyncStage.FAILED
                if status == SyncStatus.FAILED
                else SyncStage.QUEUED
            ),
            progress_percent=100 if status != SyncStatus.RUNNING else 0,
            status_message=(
                "Inbox refresh complete."
                if status == SyncStatus.COMPLETED
                else "Inbox refresh cancelled."
                if status == SyncStatus.CANCELLED
                else "Inbox refresh failed."
                if status == SyncStatus.FAILED
                else "Inbox refresh queued."
            ),
            fetched_message_count=model.fetched_message_count,
            thread_count=model.thread_count,
            ai_thread_count=model.ai_thread_count,
            cancellation_requested=False,
            completed_at=model.completed_at,
            queue_summary=(
                QueueSummaryResult.model_validate(queue_summary_payload)
                if queue_summary_payload
                else None
            ),
            error_message=model.error_message,
        )
