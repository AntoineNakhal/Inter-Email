"""Sync run persistence helpers."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.analysis import QueueSummaryResult
from backend.domain.sync import SyncRunSummary, SyncStage, SyncStatus
from backend.persistence.models.sync_run import SyncRunModel


logger = logging.getLogger(__name__)

# Runs stuck in "running" for longer than this are considered orphaned (process
# was killed mid-sync). They are transitioned to "interrupted" on startup.
_STALE_RUN_THRESHOLD = timedelta(hours=2)


class SyncRepository:
    """Repository for workflow run metadata."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def start_run(self, source: str, mailbox_account: str = "") -> SyncRunModel:
        model = SyncRunModel(
            status=SyncStatus.RUNNING.value,
            source=source,
            mailbox_account=mailbox_account.strip().lower(),
        )
        self.session.add(model)
        self.session.flush()
        return model

    def get_active_run_for_account(self, mailbox_account: str) -> SyncRunModel | None:
        """Return the currently-running run for *mailbox_account*, or None.

        Used to enforce the single-active-run-per-account invariant before
        creating a new run.
        """
        account = mailbox_account.strip().lower()
        if not account:
            return None
        return self.session.scalar(
            select(SyncRunModel)
            .where(
                SyncRunModel.mailbox_account == account,
                SyncRunModel.status == SyncStatus.RUNNING.value,
            )
            .order_by(SyncRunModel.id.desc())
            .limit(1)
        )

    def update_progress(
        self,
        run_id: int,
        *,
        stage: SyncStage,
        progress_percent: int,
        stage_unit_current: int,
        stage_unit_total: int,
        status_message: str,
        eta_seconds: int | None = None,
    ) -> None:
        """Persist a progress snapshot to the DB row.

        Called at each stage transition so a restarted process can read the
        last-known state from the DB instead of showing a stale "running" row.
        """
        model = self.session.get(SyncRunModel, run_id)
        if model is None or model.status != SyncStatus.RUNNING.value:
            return
        model.progress_json = json.dumps(
            {
                "stage": stage.value,
                "progress_percent": progress_percent,
                "stage_unit_current": stage_unit_current,
                "stage_unit_total": stage_unit_total,
                "status_message": status_message,
                "eta_seconds": eta_seconds,
            },
            ensure_ascii=False,
        )
        self.session.flush()

    def interrupt_stale_runs(self) -> int:
        """Mark orphaned running rows as 'interrupted' and return the count.

        Called once at process startup. Any run still in status=running after
        more than *_STALE_RUN_THRESHOLD* was abandoned by a previous process.
        Marking them avoids the frontend showing a perpetual "syncing" state.
        """
        cutoff = datetime.now(timezone.utc) - _STALE_RUN_THRESHOLD
        stale = self.session.scalars(
            select(SyncRunModel).where(
                SyncRunModel.status == SyncStatus.RUNNING.value,
                SyncRunModel.created_at < cutoff,
            )
        ).all()
        for model in stale:
            model.status = SyncStatus.FAILED.value
            model.completed_at = datetime.now(timezone.utc)
            model.error_message = (
                "Process was restarted while this sync was in progress."
            )
        if stale:
            self.session.flush()
            logger.warning(
                "Interrupted %s stale sync run(s) from a previous process.", len(stale)
            )
        return len(stale)

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
            stage_unit_current=0,
            stage_unit_total=0,
            eta_seconds=0,
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

        # For in-flight runs, blend in the persisted progress snapshot so a
        # restarted process can show meaningful progress from the DB instead of
        # a bare "running / 0 %" row.
        progress_snapshot: dict = {}
        if model.status == SyncStatus.RUNNING.value and model.progress_json:
            try:
                progress_snapshot = json.loads(model.progress_json)
            except json.JSONDecodeError:
                progress_snapshot = {}

        status = SyncStatus(model.status)
        default_stage = (
            SyncStage.COMPLETED
            if status == SyncStatus.COMPLETED
            else SyncStage.CANCELLED
            if status == SyncStatus.CANCELLED
            else SyncStage.FAILED
            if status == SyncStatus.FAILED
            else SyncStage.QUEUED
        )
        try:
            stage = (
                SyncStage(progress_snapshot["stage"])
                if progress_snapshot.get("stage")
                else default_stage
            )
        except ValueError:
            stage = default_stage

        return SyncRunSummary(
            run_id=model.id,
            status=status,
            source=model.source,
            stage=stage,
            progress_percent=(
                progress_snapshot.get("progress_percent", 0)
                if status == SyncStatus.RUNNING
                else 100
            ),
            stage_unit_current=progress_snapshot.get("stage_unit_current", 0),
            stage_unit_total=progress_snapshot.get("stage_unit_total", 0),
            eta_seconds=(
            progress_snapshot.get("eta_seconds")
            if status == SyncStatus.RUNNING
            else 0
        ),
            status_message=(
                progress_snapshot.get("status_message")
                or (
                    "Inbox refresh complete."
                    if status == SyncStatus.COMPLETED
                    else "Inbox refresh cancelled."
                    if status == SyncStatus.CANCELLED
                    else "Inbox refresh failed."
                    if status == SyncStatus.FAILED
                    else "Inbox refresh queued."
                )
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
