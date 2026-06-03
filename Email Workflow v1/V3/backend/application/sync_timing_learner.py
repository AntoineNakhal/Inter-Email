"""Persists real per-stage sync timing averages so SyncProgressStore
can use learned data instead of hardcoded constants.

After every successful sync run, the service records how long each
stage actually took. The learner stores an exponential moving average
(EMA) per stage in a JSON file and serves those averages on the next
run. On the very first run — when no history exists — conservative
defaults are used so the bar still moves, then corrects itself from
run 2 onward.

JSON schema (data/sync_timings.json):
{
  "fetching":   {"avg_ms": 4100.0, "samples": 5},
  "persisting": {"avg_ms": 3200.0, "samples": 5},
  "summarizing":{"avg_ms": 1900.0, "samples": 5},
  "analyzing_ms_per_thread": {"avg_ms": 2800.0, "samples": 5},
  "last_thread_count": 42
}

`analyzing_ms_per_thread` stores time-per-thread so the estimate
scales automatically with the number of threads in each new run.
"""

from __future__ import annotations

import json
import logging
from math import ceil
from pathlib import Path

from backend.domain.sync import SyncStage


logger = logging.getLogger(__name__)

# Only used when there is zero history at all (first run ever).
# Conservative: better to over-estimate early and correct fast.
_FIRST_RUN_DEFAULTS_MS: dict[str, float] = {
    "fetching": 6000.0,
    "persisting": 5000.0,
    "summarizing": 3000.0,
    "analyzing_ms_per_thread": 4000.0,
}

# EMA smoothing factor: 0.3 = 30% weight to newest observation.
# Converges to real data within ~5–7 runs.
_EMA_ALPHA = 0.3

# Stages we track. QUEUED is essentially instant; skip it.
_TRACKED = (
    SyncStage.FETCHING,
    SyncStage.PERSISTING,
    SyncStage.ANALYZING,
    SyncStage.SUMMARIZING,
)


def _stage_key(stage: SyncStage) -> str:
    """Map a SyncStage to its JSON key."""
    return stage.value  # "fetching", "persisting", etc.


class SyncTimingLearner:
    """Learns per-stage sync durations from real runs and persists them.

    Thread-safe for reads; writes happen only at sync completion (single
    writer at a time in practice).
    """

    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / "sync_timings.json"
        self._data: dict[str, dict] = self._load()

    # ── public API ──────────────────────────────────────────────────────

    def avg_stage_ms(self, stage: SyncStage, thread_count: int = 0) -> float:
        """Return the learned average duration in ms for a stage.

        For ANALYZING, multiplies avg_ms_per_thread by thread_count
        (floored at 1 so it never returns 0 when thread_count is unknown).
        """
        if stage == SyncStage.ANALYZING:
            ms_per = self._data.get(
                "analyzing_ms_per_thread",
                {"avg_ms": _FIRST_RUN_DEFAULTS_MS["analyzing_ms_per_thread"]},
            )["avg_ms"]
            return ms_per * max(thread_count, 1)

        key = _stage_key(stage)
        if key not in self._data:
            return _FIRST_RUN_DEFAULTS_MS.get(key, 3000.0)
        return self._data[key]["avg_ms"]

    def avg_ms_per_thread(self) -> float:
        """Average ANALYZING time per thread, for in-run ETA blending."""
        return self._data.get(
            "analyzing_ms_per_thread",
            {"avg_ms": _FIRST_RUN_DEFAULTS_MS["analyzing_ms_per_thread"]},
        )["avg_ms"]

    def last_thread_count(self) -> int:
        """Thread count from the most recent completed run.

        Used as a prior when the current run hasn't reached PERSISTING yet
        (so thread_count is still 0) — gives a realistic initial ETA instead
        of estimating for just 1 thread.
        """
        return int(self._data.get("last_thread_count", 0))

    def has_history(self) -> bool:
        """True once at least one real sync has been recorded."""
        return bool(self._data)

    def record_run(
        self,
        *,
        fetching_ms: float,
        persisting_ms: float,
        analyzing_ms: float,
        summarizing_ms: float,
        thread_count: int,
    ) -> None:
        """Update all stage averages with timings from a completed run.

        Call this AFTER a successful sync completes, then call save().
        Cancelled or failed runs are intentionally excluded so bad
        partial timings don't corrupt the averages.
        """
        self._update_stage("fetching", fetching_ms)
        self._update_stage("persisting", persisting_ms)
        self._update_stage("summarizing", summarizing_ms)

        # For ANALYZING store ms-per-thread so the estimate scales.
        if thread_count > 0:
            ms_per_thread = analyzing_ms / thread_count
            self._update_stage("analyzing_ms_per_thread", ms_per_thread)

        # Always update last_thread_count — used as ETA prior on the next run
        # before we know how many threads the current run will produce.
        if thread_count > 0:
            self._data["last_thread_count"] = thread_count

        logger.info(
            "SyncTimingLearner recorded run: fetch=%.0fms persist=%.0fms "
            "analyze=%.0fms (%d threads → %.0fms/thread) summarize=%.0fms",
            fetching_ms,
            persisting_ms,
            analyzing_ms,
            thread_count,
            analyzing_ms / max(thread_count, 1),
            summarizing_ms,
        )

    def save(self) -> None:
        """Persist current averages to disk. Best-effort — never raises."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._data, indent=2))
        except Exception:
            logger.warning(
                "SyncTimingLearner: could not save %s", self._path, exc_info=True
            )

    def initial_eta_seconds(self, thread_count: int = 0) -> int:
        """Full-run ETA from learned averages, used at sync start.

        If thread_count is unknown (0), falls back to the last run's thread
        count so the bar starts with a realistic estimate rather than 4 seconds.
        """
        effective_threads = thread_count or self.last_thread_count() or 1
        total_ms = (
            self.avg_stage_ms(SyncStage.FETCHING)
            + self.avg_stage_ms(SyncStage.PERSISTING)
            + self.avg_stage_ms(SyncStage.ANALYZING, effective_threads)
            + self.avg_stage_ms(SyncStage.SUMMARIZING)
        )
        return max(1, ceil(total_ms / 1000))

    def floor_eta_seconds(
        self,
        current_stage: SyncStage,
        thread_count: int = 0,
    ) -> int:
        """Minimum ETA: sum of all stages AFTER the current one.

        This prevents the ETA from dropping to near-zero while there
        are still one or two slow stages ahead.  If thread_count is still
        unknown, use the last run's count as a floor prior.
        """
        effective_threads = thread_count or self.last_thread_count() or 1
        current_index = _TRACKED.index(current_stage) if current_stage in _TRACKED else -1
        remaining_ms = sum(
            self.avg_stage_ms(s, effective_threads)
            for s in _TRACKED[current_index + 1 :]
        )
        return ceil(remaining_ms / 1000)

    # ── internals ──────────────────────────────────────────────────────

    def _update_stage(self, key: str, new_value_ms: float) -> None:
        if new_value_ms <= 0:
            return
        if key not in self._data:
            self._data[key] = {"avg_ms": new_value_ms, "samples": 1}
        else:
            old = self._data[key]["avg_ms"]
            self._data[key]["avg_ms"] = old * (1 - _EMA_ALPHA) + new_value_ms * _EMA_ALPHA
            self._data[key]["samples"] = self._data[key].get("samples", 0) + 1

    def _load(self) -> dict[str, dict]:
        try:
            if self._path.exists():
                raw = json.loads(self._path.read_text())
                if isinstance(raw, dict):
                    return raw
        except Exception:
            logger.warning(
                "SyncTimingLearner: could not load %s — starting fresh",
                self._path,
                exc_info=True,
            )
        return {}
