"""In-memory sync workflow progress tracking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import ceil
from threading import Lock

from backend.domain.thread import EmailThread
from backend.domain.sync import SyncRunSummary, SyncStage, SyncStatus


STAGE_ORDER: tuple[SyncStage, ...] = (
    SyncStage.QUEUED,
    SyncStage.FETCHING,
    SyncStage.PERSISTING,
    SyncStage.ANALYZING,
    SyncStage.SUMMARIZING,
)

BASE_STAGE_DURATIONS_MS: dict[SyncStage, int] = {
    SyncStage.QUEUED: 1200,
    SyncStage.FETCHING: 5200,
    SyncStage.PERSISTING: 4800,
    SyncStage.ANALYZING: 20000,
    SyncStage.SUMMARIZING: 2600,
}

DEFAULT_ANALYZE_MS_PER_THREAD = 5000.0


@dataclass
class _RunTimingState:
    run_started_at: datetime
    stage_started_at: datetime
    stage: SyncStage
    unit_started_at: datetime | None = None
    last_unit_current: int = 0
    observed_ms_per_unit: float | None = None
    observed_unit_samples: int = 0


class SyncProgressStore:
    """Tracks the latest workflow progress for active and recent sync runs."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._runs: dict[int, SyncRunSummary] = {}
        self._latest_run_id: int | None = None
        self._cancel_requested: set[int] = set()
        self._snapshots: dict[int, list[EmailThread]] = {}
        self._timings: dict[int, _RunTimingState] = {}

    def start(self, run_id: int, source: str) -> SyncRunSummary:
        now = datetime.now(timezone.utc)
        summary = SyncRunSummary(
            run_id=run_id,
            status=SyncStatus.RUNNING,
            source=source,
            stage=SyncStage.QUEUED,
            progress_percent=1,
            stage_unit_current=0,
            stage_unit_total=0,
            eta_seconds=self._estimate_initial_eta_seconds(),
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
            self._timings[run_id] = _RunTimingState(
                run_started_at=now,
                stage_started_at=now,
                stage=SyncStage.QUEUED,
            )
        return summary.model_copy(deep=True)

    def update(
        self,
        run_id: int,
        *,
        stage: SyncStage,
        progress_percent: int | None = None,
        status_message: str,
        fetched_message_count: int | None = None,
        thread_count: int | None = None,
        ai_thread_count: int | None = None,
        stage_unit_current: int | None = None,
        stage_unit_total: int | None = None,
    ) -> SyncRunSummary | None:
        with self._lock:
            current = self._runs.get(run_id)
            if current is None:
                return None
            timing = self._timings.get(run_id)
            if timing is None:
                now = datetime.now(timezone.utc)
                timing = _RunTimingState(
                    run_started_at=now,
                    stage_started_at=now,
                    stage=current.stage,
                )
                self._timings[run_id] = timing
            updated = current.model_copy(deep=True)
            previous_progress = updated.progress_percent
            updated.stage = stage
            updated.status_message = status_message
            updated.status = SyncStatus.RUNNING
            updated.cancellation_requested = run_id in self._cancel_requested
            if fetched_message_count is not None:
                updated.fetched_message_count = fetched_message_count
            if thread_count is not None:
                updated.thread_count = thread_count
            if ai_thread_count is not None:
                updated.ai_thread_count = ai_thread_count
            if stage != current.stage:
                updated.stage_unit_current = 0
                updated.stage_unit_total = 0
            if stage_unit_current is not None:
                updated.stage_unit_current = max(0, stage_unit_current)
            if stage_unit_total is not None:
                updated.stage_unit_total = max(0, stage_unit_total)

            self._advance_timing_state(timing, updated)
            computed_eta_seconds = self._estimate_eta_seconds(updated, timing)
            computed_progress = self._estimate_progress_percent(
                updated,
                timing,
                computed_eta_seconds,
            )
            updated.progress_percent = max(
                previous_progress,
                progress_percent if progress_percent is not None else 0,
                computed_progress,
            )
            updated.progress_percent = min(99, updated.progress_percent)
            updated.eta_seconds = computed_eta_seconds
            self._runs[run_id] = updated
            self._latest_run_id = run_id
            return updated.model_copy(deep=True)

    def complete(self, summary: SyncRunSummary) -> SyncRunSummary:
        completed = summary.model_copy(deep=True)
        completed.status = SyncStatus.COMPLETED
        completed.stage = SyncStage.COMPLETED
        completed.progress_percent = 100
        completed.stage_unit_current = completed.stage_unit_total
        completed.eta_seconds = 0
        completed.status_message = completed.status_message or "Inbox refresh complete."
        completed.cancellation_requested = False
        with self._lock:
            self._runs[summary.run_id] = completed
            self._latest_run_id = summary.run_id
            self._cancel_requested.discard(summary.run_id)
            self._snapshots.pop(summary.run_id, None)
            self._timings.pop(summary.run_id, None)
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
            stage_unit_current=0,
            stage_unit_total=0,
            eta_seconds=0,
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
            self._timings.pop(run_id, None)
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
            stage_unit_current=0,
            stage_unit_total=0,
            eta_seconds=0,
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
            self._timings.pop(run_id, None)
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
            self._timings.clear()

    def _estimate_initial_eta_seconds(self) -> int:
        total_ms = sum(BASE_STAGE_DURATIONS_MS.values())
        return ceil(total_ms / 1000)

    def _advance_timing_state(
        self,
        timing: _RunTimingState,
        summary: SyncRunSummary,
    ) -> None:
        now = datetime.now(timezone.utc)
        if timing.stage != summary.stage:
            timing.stage = summary.stage
            timing.stage_started_at = now
            timing.unit_started_at = now if summary.stage_unit_total > 0 else None
            timing.last_unit_current = summary.stage_unit_current
            timing.observed_ms_per_unit = None
            return

        if summary.stage_unit_total <= 0:
            return

        if timing.unit_started_at is None:
            timing.unit_started_at = now
            timing.last_unit_current = summary.stage_unit_current
            return

        if summary.stage_unit_current > timing.last_unit_current:
            delta_units = summary.stage_unit_current - timing.last_unit_current
            elapsed_ms = max(
                1.0,
                (now - timing.unit_started_at).total_seconds() * 1000,
            )
            observed_ms_per_unit = elapsed_ms / delta_units
            timing.observed_ms_per_unit = (
                observed_ms_per_unit
                if timing.observed_ms_per_unit is None
                else timing.observed_ms_per_unit * 0.65
                + observed_ms_per_unit * 0.35
            )
            timing.observed_unit_samples += delta_units
            timing.unit_started_at = now
            timing.last_unit_current = summary.stage_unit_current

    def _blended_analyze_ms_per_unit(
        self,
        timing: _RunTimingState,
        summary: SyncRunSummary,
    ) -> float:
        default_ms_per_unit = DEFAULT_ANALYZE_MS_PER_THREAD
        if timing.observed_ms_per_unit is None or timing.observed_unit_samples <= 0:
            return default_ms_per_unit

        prior_weight = 4
        return (
            timing.observed_ms_per_unit * timing.observed_unit_samples
            + default_ms_per_unit * prior_weight
        ) / (timing.observed_unit_samples + prior_weight)

    def _estimate_stage_duration_ms(
        self,
        stage: SyncStage,
        summary: SyncRunSummary,
    ) -> float:
        base = float(BASE_STAGE_DURATIONS_MS[stage])
        if stage == SyncStage.ANALYZING:
            total_threads = summary.stage_unit_total or summary.thread_count
            return max(
                base,
                float(max(total_threads, 1))
                * DEFAULT_ANALYZE_MS_PER_THREAD,
            )
        return base

    def _estimate_progress_percent(
        self,
        summary: SyncRunSummary,
        timing: _RunTimingState,
        eta_seconds: int,
    ) -> int:
        elapsed_seconds = max(
            0.0,
            (datetime.now(timezone.utc) - timing.run_started_at).total_seconds(),
        )
        total_estimated_seconds = elapsed_seconds + max(0, eta_seconds)
        if total_estimated_seconds <= 0:
            return 0
        return max(1, int(round((elapsed_seconds / total_estimated_seconds) * 100)))

    def _estimate_eta_seconds(
        self,
        summary: SyncRunSummary,
        timing: _RunTimingState,
    ) -> int:
        if summary.stage not in STAGE_ORDER:
            return 0

        remaining_ms = 0.0
        current_index = STAGE_ORDER.index(summary.stage)
        current_stage_duration_ms = self._estimate_stage_duration_ms(summary.stage, summary)
        stage_elapsed_ms = max(
            0.0,
            (datetime.now(timezone.utc) - timing.stage_started_at).total_seconds() * 1000,
        )

        if summary.stage == SyncStage.ANALYZING and summary.stage_unit_total > 0:
            blended_ms_per_unit = self._blended_analyze_ms_per_unit(
                timing,
                summary,
            )
            if summary.stage_unit_current < summary.stage_unit_total:
                current_unit_elapsed_ms = max(
                    0.0,
                    (datetime.now(timezone.utc) - (timing.unit_started_at or datetime.now(timezone.utc))).total_seconds() * 1000,
                )
                remaining_ms += (
                    max(blended_ms_per_unit - current_unit_elapsed_ms, 0.0)
                    + max(summary.stage_unit_total - summary.stage_unit_current - 1, 0)
                    * blended_ms_per_unit
                )
            else:
                remaining_ms += 0.0
        else:
            remaining_ms += max(current_stage_duration_ms - stage_elapsed_ms, 0.0)

        for future_stage in STAGE_ORDER[current_index + 1 :]:
            remaining_ms += self._estimate_stage_duration_ms(future_stage, summary)

        return ceil(remaining_ms / 1000)
