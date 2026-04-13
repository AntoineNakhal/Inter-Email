"""Small JSON cache for reusable thread-level analysis results."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from schemas import EmailThread, SummaryOutput, ThreadCrmRecord, ThreadTriageItem


DEFAULT_THREAD_CACHE_PATH = "data/outputs/thread_cache.json"


def default_thread_cache_payload() -> dict[str, Any]:
    return {"threads": {}, "summary": {}}


def load_thread_cache(
    path: str | Path = DEFAULT_THREAD_CACHE_PATH,
) -> dict[str, Any]:
    """Load the thread cache or return a safe empty structure."""

    file_path = Path(path)
    if not file_path.exists():
        return default_thread_cache_payload()

    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default_thread_cache_payload()

    if not isinstance(payload, dict):
        return default_thread_cache_payload()

    threads = payload.get("threads")
    summary = payload.get("summary")
    return {
        "threads": threads if isinstance(threads, dict) else {},
        "summary": summary if isinstance(summary, dict) else {},
    }


def save_thread_cache(
    cache_payload: dict[str, Any],
    path: str | Path = DEFAULT_THREAD_CACHE_PATH,
) -> None:
    """Persist the thread cache to disk."""

    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(cache_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def compute_thread_signature(thread: EmailThread) -> str:
    """Build a stable content signature for one grouped thread."""

    payload = {
        "thread_id": thread.thread_id,
        "subject": thread.subject,
        "participants": thread.participants,
        "message_count": thread.message_count,
        "latest_message_date": thread.latest_message_date,
        "messages": [
            {
                "message_id": message.message_id,
                "sender": message.sender,
                "subject": message.subject,
                "date": message.date,
                "snippet": message.snippet,
                "cleaned_body": message.cleaned_body,
            }
            for message in thread.messages
        ],
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_summary_signature(threads: list[EmailThread]) -> str:
    """Build one signature for the current set of machine-covered threads."""

    payload = [
        {
            "thread_id": thread.thread_id,
            "thread_signature": thread.thread_signature,
            "predicted_category": thread.predicted_category,
            "predicted_urgency": thread.predicted_urgency,
            "predicted_summary": thread.predicted_summary,
            "predicted_status": thread.predicted_status,
            "predicted_next_action": thread.predicted_next_action,
        }
        for thread in sorted(threads, key=lambda item: item.thread_id)
    ]
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def get_thread_cache_entry(
    cache_payload: dict[str, Any],
    thread_id: str,
) -> dict[str, Any]:
    """Return one stored thread cache entry or an empty dict."""

    threads = cache_payload.get("threads", {})
    if not isinstance(threads, dict):
        return {}
    entry = threads.get(thread_id, {})
    return entry if isinstance(entry, dict) else {}


def detect_change_status(cache_entry: dict[str, Any], thread_signature: str) -> str:
    """Return whether the current thread is new, changed, or unchanged."""

    if not cache_entry:
        return "new"
    if str(cache_entry.get("thread_signature", "")) == thread_signature:
        return "unchanged"
    return "changed"


def cache_entry_has_predictions(cache_entry: dict[str, Any]) -> bool:
    """Return True when a cache entry contains reusable thread analysis."""

    return bool(
        cache_entry
        and cache_entry.get("predicted_category")
        and cache_entry.get("predicted_summary")
        and cache_entry.get("predicted_status")
    )


def apply_cached_predictions(thread: EmailThread, cache_entry: dict[str, Any]) -> None:
    """Copy reusable cached predictions back onto the current thread."""

    thread.predicted_category = cache_entry.get("predicted_category")
    thread.predicted_urgency = cache_entry.get("predicted_urgency")
    thread.predicted_summary = cache_entry.get("predicted_summary")
    thread.predicted_status = cache_entry.get("predicted_status")
    thread.predicted_needs_action_today = cache_entry.get(
        "predicted_needs_action_today"
    )
    thread.predicted_next_action = cache_entry.get("predicted_next_action")
    thread.crm_contact_name = cache_entry.get("crm_contact_name")
    thread.crm_company = cache_entry.get("crm_company")
    thread.crm_opportunity_type = cache_entry.get("crm_opportunity_type")
    thread.crm_urgency = cache_entry.get("crm_urgency")
    thread.last_analysis_at = cache_entry.get("last_analysis_at")


def build_cached_triage_item(
    thread_id: str,
    cache_entry: dict[str, Any],
) -> ThreadTriageItem | None:
    """Rebuild one triage item from cached thread predictions."""

    if not cache_entry_has_predictions(cache_entry):
        return None

    return ThreadTriageItem(
        thread_id=thread_id,
        category=cache_entry.get("predicted_category"),
        summary=cache_entry.get("predicted_summary"),
        current_status=cache_entry.get("predicted_status"),
        urgency=cache_entry.get("predicted_urgency") or "unknown",
        needs_action_today=bool(cache_entry.get("predicted_needs_action_today")),
    )


def build_cached_crm_record(
    thread_id: str,
    cache_entry: dict[str, Any],
) -> ThreadCrmRecord | None:
    """Rebuild one CRM record from cached thread predictions."""

    if not cache_entry:
        return None

    return ThreadCrmRecord(
        thread_id=thread_id,
        contact_name=cache_entry.get("crm_contact_name"),
        company=cache_entry.get("crm_company"),
        opportunity_type=cache_entry.get("crm_opportunity_type"),
        next_action=cache_entry.get("predicted_next_action"),
        urgency=cache_entry.get("crm_urgency") or "unknown",
    )


def load_cached_summary(
    cache_payload: dict[str, Any],
    coverage_signature: str,
) -> SummaryOutput | None:
    """Return a cached run summary when the covered thread set is unchanged."""

    summary_entry = cache_payload.get("summary", {})
    if not isinstance(summary_entry, dict):
        return None
    if summary_entry.get("coverage_signature") != coverage_signature:
        return None

    summary_payload = summary_entry.get("summary")
    if not isinstance(summary_payload, dict):
        return None

    try:
        return SummaryOutput.model_validate(summary_payload)
    except Exception:
        return None


def save_cached_summary(
    cache_payload: dict[str, Any],
    coverage_signature: str,
    summary: SummaryOutput,
    cached_at: str | None = None,
) -> None:
    """Persist the latest summary snapshot for the current covered threads."""

    cache_payload["summary"] = {
        "coverage_signature": coverage_signature,
        "cached_at": cached_at or datetime.now(timezone.utc).isoformat(),
        "summary": summary.model_dump(),
    }


def upsert_thread_cache_entry(
    cache_payload: dict[str, Any],
    thread: EmailThread,
    seen_at: str | None = None,
) -> None:
    """Insert or update one thread cache entry."""

    resolved_seen_at = seen_at or datetime.now(timezone.utc).isoformat()
    threads = cache_payload.setdefault("threads", {})
    if not isinstance(threads, dict):
        cache_payload["threads"] = {}
        threads = cache_payload["threads"]

    entry = get_thread_cache_entry(cache_payload, thread.thread_id)
    entry.update(
        {
            "thread_id": thread.thread_id,
            "thread_signature": thread.thread_signature,
            "subject": thread.subject,
            "latest_message_date": thread.latest_message_date,
            "message_count": thread.message_count,
            "relevance_bucket": thread.relevance_bucket,
            "selection_reason": thread.selection_reason,
            "last_seen_at": resolved_seen_at,
        }
    )

    if thread.last_analysis_at:
        entry["last_analysis_at"] = thread.last_analysis_at

    if thread.predicted_category is not None:
        entry["predicted_category"] = thread.predicted_category
        entry["predicted_urgency"] = thread.predicted_urgency
        entry["predicted_summary"] = thread.predicted_summary
        entry["predicted_status"] = thread.predicted_status
        entry["predicted_needs_action_today"] = thread.predicted_needs_action_today
        entry["predicted_next_action"] = thread.predicted_next_action
        entry["crm_contact_name"] = thread.crm_contact_name
        entry["crm_company"] = thread.crm_company
        entry["crm_opportunity_type"] = thread.crm_opportunity_type
        entry["crm_urgency"] = thread.crm_urgency

    threads[thread.thread_id] = entry
