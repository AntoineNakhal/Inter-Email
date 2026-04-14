"""Tiny JSON-backed workflow progress state shared by backend and Streamlit UIs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, MutableMapping


DEFAULT_PROGRESS_OUTPUT_PATH = "data/outputs/backend_progress.json"
PHASE_PROGRESS_CEILINGS = {
    "queued": 4,
    "startup": 7,
    "fetching_threads": 47,
    "grouping_threads": 66,
    "checking_sensitive_and_cache": 73,
    "triage_and_crm": 81,
    "reply_drafts": 95,
    "summary": 90,
    "saving_cache": 97,
    "writing_output": 99,
    "complete": 100,
    "error": 100,
}


def default_progress_payload() -> dict[str, Any]:
    """Return the default progress structure."""

    return {
        "status": "idle",
        "phase": "idle",
        "progress": 0,
        "detail": "",
        "updated_at": None,
    }


def load_progress_state(
    path: str | Path = DEFAULT_PROGRESS_OUTPUT_PATH,
) -> dict[str, Any]:
    """Load workflow progress or return a safe empty payload."""

    file_path = Path(path)
    if not file_path.exists():
        return default_progress_payload()

    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default_progress_payload()

    if not isinstance(payload, dict):
        return default_progress_payload()

    progress = payload.get("progress", 0)
    try:
        normalized_progress = int(progress)
    except (TypeError, ValueError):
        normalized_progress = 0

    normalized_progress = max(0, min(100, normalized_progress))

    return {
        "status": str(payload.get("status") or "idle"),
        "phase": str(payload.get("phase") or "idle"),
        "progress": normalized_progress,
        "detail": str(payload.get("detail") or ""),
        "updated_at": payload.get("updated_at"),
    }


def save_progress_state(
    payload: dict[str, Any],
    path: str | Path = DEFAULT_PROGRESS_OUTPUT_PATH,
) -> None:
    """Persist workflow progress safely."""

    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


class WorkflowProgressTracker:
    """Simple writer for stage-based workflow progress."""

    def __init__(self, path: str | Path = DEFAULT_PROGRESS_OUTPUT_PATH) -> None:
        self.path = Path(path)

    def update(
        self,
        phase: str,
        progress: int,
        detail: str,
        status: str = "running",
    ) -> None:
        """Write one progress update to disk."""

        save_progress_state(
            {
                "status": status,
                "phase": str(phase or "running"),
                "progress": max(0, min(100, int(progress))),
                "detail": str(detail or ""),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            self.path,
        )

    def mark_complete(self, detail: str = "Refresh complete.") -> None:
        self.update("complete", 100, detail, status="complete")

    def mark_error(self, detail: str) -> None:
        self.update("error", 100, detail, status="error")


def smooth_progress_for_display(
    progress_state: dict[str, Any],
    ui_state: MutableMapping[str, Any],
    key_prefix: str,
    min_step_seconds: float = 0.05,
) -> dict[str, Any]:
    """Return a visually smoother progress payload for UI display only."""

    status = str(progress_state.get("status") or "idle")
    phase = str(progress_state.get("phase") or "idle")
    detail = str(progress_state.get("detail") or "")

    raw_progress = progress_state.get("progress", 0)
    try:
        target_progress = int(raw_progress)
    except (TypeError, ValueError):
        target_progress = 0
    target_progress = max(0, min(100, target_progress))

    display_key = f"{key_prefix}_display_progress"
    stamp_key = f"{key_prefix}_display_progress_updated_at"
    phase_key = f"{key_prefix}_display_phase"
    status_key = f"{key_prefix}_display_status"
    phase_started_key = f"{key_prefix}_display_phase_started_at"

    try:
        current_display = int(ui_state.get(display_key, target_progress))
    except (TypeError, ValueError):
        current_display = target_progress
    current_display = max(0, min(100, current_display))

    try:
        last_step_at = float(ui_state.get(stamp_key, 0.0) or 0.0)
    except (TypeError, ValueError):
        last_step_at = 0.0
    try:
        phase_started_at = float(ui_state.get(phase_started_key, 0.0) or 0.0)
    except (TypeError, ValueError):
        phase_started_at = 0.0

    previous_phase = str(ui_state.get(phase_key) or "")
    previous_status = str(ui_state.get(status_key) or "")
    now_timestamp = datetime.now(timezone.utc).timestamp()
    phase_changed = phase != previous_phase

    if phase_changed or phase_started_at <= 0:
        phase_started_at = now_timestamp

    should_reset = (
        status in {"complete", "error"}
        or (
            phase in {"queued", "startup"}
            and previous_status in {"complete", "error", "idle"}
        )
        or (
            previous_phase == "complete"
            and phase != "complete"
        )
    )

    if should_reset:
        display_progress = target_progress
    elif target_progress <= current_display:
        phase_ceiling = int(PHASE_PROGRESS_CEILINGS.get(phase, target_progress))
        if phase_ceiling < target_progress:
            phase_ceiling = target_progress
        if (
            phase not in {"complete", "error", "idle"}
            and current_display < phase_ceiling
            and now_timestamp - last_step_at >= float(min_step_seconds)
        ):
            display_progress = min(phase_ceiling, current_display + 1)
        else:
            display_progress = current_display
    elif now_timestamp - last_step_at < float(min_step_seconds):
        display_progress = current_display
    else:
        display_progress = min(target_progress, current_display + 1)

    ui_state[display_key] = display_progress
    ui_state[stamp_key] = now_timestamp
    ui_state[phase_key] = phase
    ui_state[status_key] = status
    ui_state[phase_started_key] = phase_started_at

    return {
        "status": status,
        "phase": phase,
        "progress": display_progress,
        "detail": detail,
        "updated_at": progress_state.get("updated_at"),
    }
