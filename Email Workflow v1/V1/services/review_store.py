"""Persistence helpers for manual review data in the Streamlit UI."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_REVIEW_OUTPUT_PATH = "data/outputs/review_results.json"
DEFAULT_ACCOUNT_OUTPUT_PATH = "data/outputs/gmail_accounts.json"


def load_review_results(path: str | Path = DEFAULT_REVIEW_OUTPUT_PATH) -> dict[str, dict[str, Any]]:
    """Load review results from JSON, returning an empty dict when missing/invalid."""

    file_path = Path(path)
    if not file_path.exists():
        return {}

    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    if not isinstance(payload, dict):
        return {}
    return {str(key): value for key, value in payload.items() if isinstance(value, dict)}


def save_review_results(
    reviews_by_message_id: dict[str, dict[str, Any]],
    path: str | Path = DEFAULT_REVIEW_OUTPUT_PATH,
) -> None:
    """Persist review results to disk."""

    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(reviews_by_message_id, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def normalize_review_payload(raw_review: dict[str, Any]) -> dict[str, Any]:
    """Return a clean review payload that matches the agreed schema."""

    normalized = {
        "ai_result_correct": raw_review.get("ai_result_correct"),
        "correct_category": raw_review.get("correct_category"),
        "correct_urgency": raw_review.get("correct_urgency"),
        "summary_useful": raw_review.get("summary_useful"),
        "next_action_useful": raw_review.get("next_action_useful"),
        "crm_useful": raw_review.get("crm_useful"),
        "should_have_been_filtered": raw_review.get("should_have_been_filtered"),
        "notes": raw_review.get("notes", ""),
        "improvement_tags": raw_review.get("improvement_tags", []),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    if not isinstance(normalized["improvement_tags"], list):
        normalized["improvement_tags"] = []

    return normalized


def upsert_review_result(
    reviews_by_message_id: dict[str, dict[str, Any]],
    message_id: str,
    review_payload: dict[str, Any],
) -> None:
    """Insert/update one review record in memory."""

    reviews_by_message_id[str(message_id)] = normalize_review_payload(review_payload)


def load_gmail_accounts(path: str | Path = DEFAULT_ACCOUNT_OUTPUT_PATH) -> dict[str, Any]:
    """Load Gmail account profiles used by deep links in review UI."""

    file_path = Path(path)
    if not file_path.exists():
        return {"active_account": None, "accounts": []}

    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"active_account": None, "accounts": []}

    if not isinstance(payload, dict):
        return {"active_account": None, "accounts": []}

    accounts = payload.get("accounts", [])
    if not isinstance(accounts, list):
        accounts = []

    return {
        "active_account": payload.get("active_account"),
        "accounts": [normalize_gmail_account(item) for item in accounts if isinstance(item, dict)],
    }


def normalize_gmail_account(raw_account: dict[str, Any]) -> dict[str, Any]:
    """Return a compact account record for connected Gmail accounts."""

    connected_at = raw_account.get("connected_at")
    if not isinstance(connected_at, str) or not connected_at.strip():
        connected_at = datetime.now(timezone.utc).isoformat()

    return {
        "name": str(raw_account.get("name", "")).strip(),
        "email_address": str(raw_account.get("email_address", "")).strip(),
        "gmail_user_index": str(raw_account.get("gmail_user_index", "0")).strip() or "0",
        "token_path": str(raw_account.get("token_path", "")).strip(),
        "connected_at": connected_at,
    }


def upsert_gmail_account(
    account_payload: dict[str, Any],
    account_record: dict[str, Any],
) -> dict[str, Any]:
    """Insert or update one connected Gmail account record."""

    accounts = account_payload.get("accounts", [])
    if not isinstance(accounts, list):
        accounts = []

    normalized = normalize_gmail_account(account_record)
    if not normalized["name"]:
        return account_payload

    filtered = [
        normalize_gmail_account(item)
        for item in accounts
        if isinstance(item, dict) and str(item.get("name", "")).strip() != normalized["name"]
    ]
    filtered.append(normalized)
    account_payload["accounts"] = filtered
    account_payload["active_account"] = normalized["name"]
    return account_payload


def save_gmail_accounts(
    account_payload: dict[str, Any],
    path: str | Path = DEFAULT_ACCOUNT_OUTPUT_PATH,
) -> None:
    """Persist Gmail account profiles used by deep links in review UI."""

    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(account_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
