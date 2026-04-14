"""Persist simple end-user UI state such as seen conversations."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_END_USER_STATE_PATH = "data/outputs/end_user_state.json"


def default_end_user_state_payload() -> dict[str, Any]:
    """Return a safe empty payload for end-user visibility state."""

    return {"seen_threads": {}}


def load_end_user_state(
    path: str | Path = DEFAULT_END_USER_STATE_PATH,
) -> dict[str, Any]:
    """Load persisted end-user state or return an empty structure."""

    file_path = Path(path)
    if not file_path.exists():
        return default_end_user_state_payload()

    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default_end_user_state_payload()

    if not isinstance(payload, dict):
        return default_end_user_state_payload()

    seen_threads = payload.get("seen_threads", {})
    if not isinstance(seen_threads, dict):
        seen_threads = {}

    return {"seen_threads": seen_threads}


def save_end_user_state(
    state_payload: dict[str, Any],
    path: str | Path = DEFAULT_END_USER_STATE_PATH,
) -> None:
    """Persist end-user visibility state to disk."""

    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(state_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_thread_version(record: dict[str, Any]) -> str:
    """Return the best available version marker for one thread card."""

    signature = str(record.get("thread_signature") or "").strip()
    if signature:
        return signature

    return "|".join(
        [
            str(record.get("thread_id") or record.get("id") or "").strip(),
            str(record.get("latest_message_date") or "").strip(),
            str(record.get("message_count") or "").strip(),
        ]
    )


def _scope_thread_key(thread_id: str, scope: str) -> str:
    scope_value = str(scope or "default").strip() or "default"
    return f"{scope_value}::{thread_id}"


def mark_thread_seen(
    state_payload: dict[str, Any],
    record: dict[str, Any],
    scope: str = "default",
) -> None:
    """Mark one thread as seen for the current account scope."""

    thread_id = str(record.get("thread_id") or record.get("id") or "").strip()
    if not thread_id:
        return

    seen_threads = state_payload.setdefault("seen_threads", {})
    if not isinstance(seen_threads, dict):
        seen_threads = {}
        state_payload["seen_threads"] = seen_threads

    seen_threads[_scope_thread_key(thread_id, scope)] = {
        "thread_id": thread_id,
        "scope": str(scope or "default"),
        "seen_version": build_thread_version(record),
        "subject": str(record.get("subject") or "").strip(),
        "marked_seen_at": datetime.now(timezone.utc).isoformat(),
    }


def clear_thread_seen(
    state_payload: dict[str, Any],
    thread_id: str,
    scope: str = "default",
) -> None:
    """Remove the seen marker for one thread."""

    seen_threads = state_payload.get("seen_threads", {})
    if not isinstance(seen_threads, dict):
        return

    seen_threads.pop(_scope_thread_key(str(thread_id), scope), None)


def is_thread_seen(
    state_payload: dict[str, Any],
    record: dict[str, Any],
    scope: str = "default",
) -> bool:
    """Return True when the user already saw this exact thread version."""

    thread_id = str(record.get("thread_id") or record.get("id") or "").strip()
    if not thread_id:
        return False

    seen_threads = state_payload.get("seen_threads", {})
    if not isinstance(seen_threads, dict):
        return False

    entry = seen_threads.get(_scope_thread_key(thread_id, scope), {})
    if not isinstance(entry, dict):
        return False

    return str(entry.get("seen_version") or "").strip() == build_thread_version(record)
