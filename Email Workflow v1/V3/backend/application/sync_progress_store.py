"""In-memory sync workflow progress tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import ceil
from threading import Lock
from time import perf_counter
from typing import TYPE_CHECKING

from backend.domain.thread import EmailThread
from backend.domain.sync import SyncRunSummary, SyncStage, SyncStatus

if TYPE_CHECKING:
    from backend.application.sync_timing_learner import SyncTimingLearner


STAGE_ORDER: tuple[SyncStage, ...] = (
    SyncStage.QUEUED,
    SyncStage.FETCHING,
    SyncStage.PERSISTING,
    SyncStage.ANALYZING,
    SyncStage.SUMMARIZING,
)

# Each active stage owns an exclusive band of the progress bar.
# The bar can NEVER exceed a stage's ceiling while that stage is active,
# preventing the "stuck at 99% while 22/40 analyzed" problem.
# Transitions are seamless because each stage starts at the previous one's ceiling.
STAGE_PROGRESS_RANGES: dict[SyncStage, tuple[int, int]] = {
    SyncStage.QUEUED:      (0,   2),
    SyncStage.FETCHING:    (2,  22),
    SyncStage.PERSISTING:  (22, 42),
    SyncStage.ANALYZING:   (42, 92),
    SyncStage.SUMMARIZING: (92, 99),
}


@dataclass
class _RunTimingState:
    run_started_at: datetime
    stage_started_at: datetime
    stage: SyncStage
    thread_count: int = 0          # known once ANALYZING starts
    unit_started_at: datetime | None = None
    last_unit_current: int = 0
    observed_ms_per_unit: float | None = None
    observed_unit_samples: int = 0


class SyncProgressStore:
    """Tracks the latest workflow progress for active and recent sync runs.

    Accepts an optional SyncTimingLearner that supplies per-stage average
    durations learned from real past runs. When no learner is provided
    (tests, first boot) the store falls back to conservative built-in
    defaults so the bar still moves from day one.
    """

    def __init__(
        self,
        timing_learner: "SyncTimingLearner | None" = None,
    ) -> None:
        self._learner = timing_learner
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
            progress_percent=0,
            stage_unit_current=0,
            stage_unit_total=0,
            eta_seconds=None,   # no ETA until ANALYZING — we have no real data yet
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
                timing.thread_count = thread_count  # keep in sync for ETA floor
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
            computed_progress = self._estimate_progress_percent(updated, timing)

            # Stage-range ceiling: bar can never exceed this stage's max.
            lo, hi = STAGE_PROGRESS_RANGES.get(updated.stage, (0, 99))

            # On a stage transition, reset the previous_progress anchor to the
            # new stage's floor — a stale high value from the prior stage must
            # not block accurate display in the new stage.
            effective_previous = (
                lo if updated.stage != current.stage else previous_progress
            )

            updated.progress_percent = max(
                effective_previous,
                progress_percent if progress_percent is not None else 0,
                computed_progress,
            )
            updated.progress_percent = min(hi, updated.progress_percent)
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

    # ── estimation helpers ──────────────────────────────────────────────

    def _avg_stage_ms(self, stage: SyncStage, thread_count: int = 0) -> float:
        """Average duration for a stage from the learner, with fallbacks."""
        if self._learner is not None:
            return self._learner.avg_stage_ms(stage, thread_count)
        # Built-in fallbacks (learner-less mode: tests, first boot).
        _defaults: dict[SyncStage, float] = {
            SyncStage.FETCHING: 6000.0,
            SyncStage.PERSISTING: 5000.0,
            SyncStage.ANALYZING: max(thread_count, 1) * 4000.0,
            SyncStage.SUMMARIZING: 3000.0,
        }
        return _defaults.get(stage, 3000.0)

    def _avg_ms_per_thread(self) -> float:
        if self._learner is not None:
            return self._learner.avg_ms_per_thread()
        return 4000.0

    def _eta_floor_seconds(self, stage: SyncStage, thread_count: int = 0) -> int:
        """ETA can never drop below the sum of all remaining stages' averages."""
        if self._learner is not None:
            return self._learner.floor_eta_seconds(stage, thread_count)
        # Fallback: rough sum of stages after current one
        stage_order_list = list(STAGE_ORDER)
        if stage not in stage_order_list:
            return 0
        idx = stage_order_list.index(stage)
        remaining_ms = sum(
            self._avg_stage_ms(s, thread_count)
            for s in stage_order_list[idx + 1:]
            if s not in (SyncStage.QUEUED,)
        )
        return ceil(remaining_ms / 1000)

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
                else timing.observed_ms_per_unit * 0.65 + observed_ms_per_unit * 0.35
            )
            timing.observed_unit_samples += delta_units
            timing.unit_started_at = now
            timing.last_unit_current = summary.stage_unit_current

    def _blended_analyze_ms_per_unit(
        self,
        timing: _RunTimingState,
    ) -> float:
        """Blend real observed speed with the learner's historical average.

        The learner's average acts as a Bayesian prior: after just 1–2
        threads we still have almost no signal, so we lean on history.
        As more threads complete, observed data takes over.
        """
        prior = self._avg_ms_per_thread()
        if timing.observed_ms_per_unit is None or timing.observed_unit_samples <= 0:
            return prior
        prior_weight = 4
        return (
            timing.observed_ms_per_unit * timing.observed_unit_samples
            + prior * prior_weight
        ) / (timing.observed_unit_samples + prior_weight)

    def _effective_thread_count(self, timing: _RunTimingState, summary: SyncRunSummary) -> int:
        """Best available thread count for ETA estimation.

        Priority:
        1. Already known from PERSISTING/ANALYZING updates in this run.
        2. Last run's count from the learner (good prior while FETCHING).
        3. Fall back to 1 so we never multiply by 0.
        """
        known = timing.thread_count or summary.thread_count or 0
        if known > 0:
            return known
        if self._learner is not None:
            last = self._learner.last_thread_count()
            if last > 0:
                return last
        return 1

    def _estimate_eta_seconds(
        self,
        summary: SyncRunSummary,
        timing: _RunTimingState,
    ) -> int | None:
        """Compute remaining seconds, or None if we have no real data yet.

        ETA is only shown once ANALYZING starts — before that we don't know
        how many threads there are so any number would be a guess.
        During ANALYZING: remaining_threads × blended_ms_per_thread (+ summarizing).
        During SUMMARIZING: learned average for that stage.
        All other stages: None (frontend shows nothing).
        """
        if summary.stage == SyncStage.ANALYZING:
            if summary.stage_unit_total <= 0:
                return None  # haven't started yet, no thread count
            blended_ms_per_unit = self._blended_analyze_ms_per_unit(timing)
            remaining_threads = max(0, summary.stage_unit_total - summary.stage_unit_current)
            remaining_ms = remaining_threads * blended_ms_per_unit
            # Add SUMMARIZING time so the ETA stays honest at the tail end.
            thread_count = self._effective_thread_count(timing, summary)
            remaining_ms += self._avg_stage_ms(SyncStage.SUMMARIZING, thread_count)
            return max(0, ceil(remaining_ms / 1000))

        if summary.stage == SyncStage.SUMMARIZING:
            thread_count = self._effective_thread_count(timing, summary)
            stage_elapsed_ms = max(
                0.0,
                (datetime.now(timezone.utc) - timing.stage_started_at).total_seconds() * 1000,
            )
            remaining_ms = max(
                0.0,
                self._avg_stage_ms(SyncStage.SUMMARIZING, thread_count) - stage_elapsed_ms,
            )
            return max(0, ceil(remaining_ms / 1000))

        # QUEUED / FETCHING / PERSISTING — no reliable data yet, hide ETA.
        return None

    def _estimate_progress_percent(
        self,
        summary: SyncRunSummary,
        timing: _RunTimingState,
    ) -> int:
        """Map current sync state to a progress percentage using stage ranges.

        Each stage owns a fixed band of the bar (see STAGE_PROGRESS_RANGES).
        Within a stage we interpolate using:
          1. Real unit counts (threads analyzed, messages saved) — most accurate.
          2. Time elapsed vs. learned stage average — fallback, capped at 80% of
             the stage band so the bar never "finishes" a stage by time alone.

        This replaces the old elapsed/(elapsed+eta) formula, which caused the
        bar to rush to 99% whenever the ETA was underestimated.
        """
        stage_range = STAGE_PROGRESS_RANGES.get(summary.stage)
        if stage_range is None:
            return 0

        lo, hi = stage_range

        # Primary: use real unit counts (most accurate signal).
        if summary.stage_unit_total > 0:
            unit_fraction = min(1.0, summary.stage_unit_current / summary.stage_unit_total)
            return lo + int(unit_fraction * (hi - lo))

        # Fallback: time-elapsed fraction within the stage.
        thread_count = self._effective_thread_count(timing, summary)
        avg_stage_s = self._avg_stage_ms(summary.stage, thread_count) / 1000
        if avg_stage_s > 0:
            stage_elapsed = max(
                0.0,
                (datetime.now(timezone.utc) - timing.stage_started_at).total_seconds(),
            )
            # Cap at 80% of the stage band — never visually "finish" by time alone.
            time_fraction = min(0.8, stage_elapsed / avg_stage_s)
            return lo + int(time_fraction * (hi - lo))

        return lo
