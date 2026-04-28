"""In-memory sync workflow progress tracking."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock

from backend.domain.thread import EmailThread
from backend.domain.sync import SyncRunSummary, SyncStage, SyncStatus


class SyncProgressStore:
    """Tracks the latest workflow progress for active and recent sync runs."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._runs: dict[int, SyncRunSummary] = {}
        self._latest_run_id: int | None = None
        self._cancel_requested: set[int] = set()
        self._snapshots: dict[int, list[EmailThread]] = {}

    def start(self, run_id: int, source: str) -> SyncRunSummary:
        summary = SyncRunSummary(
            run_id=run_id,
            status=SyncStatus.RUNNING,
            source=source,
            stage=SyncStage.QUEUED,
            progress_percent=2,
            status_message="Sync queued.",
            fetched_message_count=0,
            thread_count=0,
            ai_thread_count=0,
            cancellation_requested=False,
        )
        with self._lock:
            self._runs[run_id] = summary
            self._latest_run_id = run_id
            self._cancel_requested.discard(run_id)
        return summary.model_copy(deep=True)

    def update(
        self,
        run_id: int,
        *,
        stage: SyncStage,
        progress_percent: int,
        status_message: str,
        fetched_message_count: int | None = None,
        thread_count: int | None = None,
        ai_thread_count: int | None = None,
    ) -> SyncRunSummary | None:
        with self._lock:
            current = self._runs.get(run_id)
            if current is None:
                return None
            updated = current.model_copy(deep=True)
            updated.stage = stage
            updated.progress_percent = max(0, min(100, progress_percent))
            updated.status_message = status_message
            updated.status = SyncStatus.RUNNING
            updated.cancellation_requested = run_id in self._cancel_requested
            if fetched_message_count is not None:
                updated.fetched_message_count = fetched_message_count
            if thread_count is not None:
                updated.thread_count = thread_count
            if ai_thread_count is not None:
                updated.ai_thread_count = ai_thread_count
            self._runs[run_id] = updated
            self._latest_run_id = run_id
            return updated.model_copy(deep=True)

    def complete(self, summary: SyncRunSummary) -> SyncRunSummary:
        completed = summary.model_copy(deep=True)
        completed.status = SyncStatus.COMPLETED
        completed.stage = SyncStage.COMPLETED
        completed.progress_percent = 100
        completed.status_message = completed.status_message or "Inbox refresh complete."
        completed.cancellation_requested = False
        with self._lock:
            self._runs[summary.run_id] = completed
            self._latest_run_id = summary.run_id
            self._cancel_requested.discard(summary.run_id)
            self._snapshots.pop(summary.run_id, None)
        return completed.model_copy(deep=True)

    def request_cancel(self, run_id: int) -> SyncRunSummary | None:
        with self._lock:
            current = self._runs.get(run_id)
            if current is None or current.status != SyncStatus.RUNNING:
                return None
            self._cancel_requested.add(run_id)
            updated = current.model_copy(deep=True)
            updated.cancellation_requested = True
            updated.status_message = "Cancelling refresh and restoring the previous local inbox."
            self._runs[run_id] = updated
            self._latest_run_id = run_id
            return updated.model_copy(deep=True)

    def is_cancel_requested(self, run_id: int) -> bool:
        with self._lock:
            return run_id in self._cancel_requested

    def cancel(
        self,
        run_id: int,
        *,
        source: str,
        status_message: str,
        fetched_message_count: int = 0,
        thread_count: int = 0,
        ai_thread_count: int = 0,
    ) -> SyncRunSummary:
        cancelled = SyncRunSummary(
            run_id=run_id,
            status=SyncStatus.CANCELLED,
            source=source,
            stage=SyncStage.CANCELLED,
            progress_percent=100,
            status_message=status_message,
            fetched_message_count=fetched_message_count,
            thread_count=thread_count,
            ai_thread_count=ai_thread_count,
            cancellation_requested=False,
            completed_at=datetime.now(timezone.utc),
        )
        with self._lock:
            self._runs[run_id] = cancelled
            self._latest_run_id = run_id
            self._cancel_requested.discard(run_id)
            self._snapshots.pop(run_id, None)
        return cancelled.model_copy(deep=True)

    def fail(
        self,
        run_id: int,
        *,
        source: str,
        error_message: str,
        fetched_message_count: int = 0,
        thread_count: int = 0,
        ai_thread_count: int = 0,
    ) -> SyncRunSummary:
        failed = SyncRunSummary(
            run_id=run_id,
            status=SyncStatus.FAILED,
            source=source,
            stage=SyncStage.FAILED,
            progress_percent=100,
            status_message="Inbox refresh failed.",
            fetched_message_count=fetched_message_count,
            thread_count=thread_count,
            ai_thread_count=ai_thread_count,
            cancellation_requested=False,
            error_message=error_message,
        )
        with self._lock:
            self._runs[run_id] = failed
            self._latest_run_id = run_id
            self._cancel_requested.discard(run_id)
            self._snapshots.pop(run_id, None)
        return failed.model_copy(deep=True)

    def capture_snapshot(self, run_id: int, threads: list[EmailThread]) -> None:
        with self._lock:
            self._snapshots[run_id] = [thread.model_copy(deep=True) for thread in threads]

    def snapshot_for_run(self, run_id: int) -> list[EmailThread]:
        with self._lock:
            snapshot = self._snapshots.get(run_id, [])
            return [thread.model_copy(deep=True) for thread in snapshot]

    def get(self, run_id: int) -> SyncRunSummary | None:
        with self._lock:
            current = self._runs.get(run_id)
            return current.model_copy(deep=True) if current else None

    def latest(self) -> SyncRunSummary | None:
        with self._lock:
            if self._latest_run_id is None:
                return None
            current = self._runs.get(self._latest_run_id)
            return current.model_copy(deep=True) if current else None

    def running(self) -> SyncRunSummary | None:
        with self._lock:
            running_runs = [
                run.model_copy(deep=True)
                for run in self._runs.values()
                if run.status == SyncStatus.RUNNING
            ]
        if not running_runs:
            return None
        return max(running_runs, key=lambda run: run.run_id)

    def clear(self) -> None:
        with self._lock:
            self._runs.clear()
            self._latest_run_id = None
            self._cancel_requested.clear()
            self._snapshots.clear()
