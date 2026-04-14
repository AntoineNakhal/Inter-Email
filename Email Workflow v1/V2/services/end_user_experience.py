"""Helpers for the non-technical end-user queue experience."""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any


def normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _shorten_text(value: Any, max_chars: int = 240) -> str:
    text = _clean_text(value)
    if len(text) <= max_chars:
        return text

    for marker in [". ", "! ", "? "]:
        cut_index = text.rfind(marker, 0, max_chars)
        if cut_index >= int(max_chars * 0.55):
            return text[: cut_index + 1].strip()

    return text[: max_chars - 3].rstrip(" ,;:") + "..."


def _safe_record_date(record: dict[str, Any]) -> datetime:
    minimum = datetime.min.replace(tzinfo=timezone.utc)
    value = str(record.get("latest_message_date") or "").strip()
    if not value:
        return minimum
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return minimum
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def user_priority(record: dict[str, Any]) -> dict[str, str | int]:
    """Map technical thread state into a plain-language priority."""

    if normalize_text(record.get("security_status")) == "classified":
        return {
            "label": "Manual only",
            "caption": "Sensitive content needs manual handling",
            "tone": "blocked",
            "rank": 0,
        }

    if record.get("waiting_on_us") or record.get("predicted_needs_action_today") is True:
        return {
            "label": "Today",
            "caption": "This likely needs a response or decision today",
            "tone": "urgent",
            "rank": 1,
        }

    if normalize_text(record.get("predicted_urgency")) == "high":
        return {
            "label": "Today",
            "caption": "Marked high priority by the system",
            "tone": "urgent",
            "rank": 1,
        }

    if normalize_text(record.get("relevance_bucket")) in {"must_review", "important"}:
        return {
            "label": "Soon",
            "caption": "Worth reviewing soon even if it may not need same-day action",
            "tone": "important",
            "rank": 2,
        }

    if normalize_text(record.get("change_status")) == "changed":
        return {
            "label": "Watch",
            "caption": "Something changed since the last run",
            "tone": "watch",
            "rank": 3,
        }

    if record.get("resolved_or_closed"):
        return {
            "label": "Done",
            "caption": "Looks resolved or closed",
            "tone": "calm",
            "rank": 5,
        }

    return {
        "label": "FYI",
        "caption": "Keep visible, but no strong action signal right now",
        "tone": "neutral",
        "rank": 4,
    }


def trust_signal(record: dict[str, Any]) -> dict[str, str]:
    """Describe how much the user should trust the machine summary."""

    if normalize_text(record.get("security_status")) == "classified":
        return {
            "label": "Manual review required",
            "caption": "Sensitive threads are held out of AI on purpose.",
            "tone": "blocked",
        }

    merge_confidence = normalize_text(record.get("merge_confidence"))
    if len(record.get("source_thread_ids", [])) > 1 and merge_confidence == "low":
        return {
            "label": "Check the grouping",
            "caption": "This card combines multiple Gmail threads with low merge confidence.",
            "tone": "warning",
        }

    if len(record.get("source_thread_ids", [])) > 1 and merge_confidence == "medium":
        return {
            "label": "Review before acting",
            "caption": "This card merges multiple Gmail threads. The summary may still be right, but verify the conversation.",
            "tone": "caution",
        }

    analysis_status = normalize_text(record.get("analysis_status"))
    if analysis_status in {"not_requested", "skipped"}:
        return {
            "label": "No AI summary",
            "caption": "This thread stayed visible, but it was not fully analyzed by AI.",
            "tone": "manual",
        }

    if normalize_text(record.get("ai_decision")) == "maybe":
        return {
            "label": "Worth a quick check",
            "caption": "The system kept this visible because it may matter, but confidence is lower.",
            "tone": "caution",
        }

    return {
        "label": "Looks reliable",
        "caption": "No obvious warning flags in the current thread view.",
        "tone": "positive",
    }


def why_it_matters(record: dict[str, Any]) -> list[str]:
    """Return short, non-technical reasons for visibility."""

    reasons: list[str] = []

    if normalize_text(record.get("security_status")) == "classified":
        reasons.append("Sensitive handling marker detected")
    if record.get("waiting_on_us"):
        reasons.append("Someone is likely waiting on your team")
    if record.get("latest_message_has_action_request"):
        reasons.append("The latest message asks for action")
    if record.get("latest_message_has_question"):
        reasons.append("The latest message asks a question")
    if normalize_text(record.get("change_status")) == "new":
        reasons.append("New since the last run")
    if normalize_text(record.get("change_status")) == "changed":
        reasons.append("Updated since the last run")
    if record.get("latest_message_from_external"):
        reasons.append("The latest message came from outside your team")
    if not reasons and record.get("resolved_or_closed"):
        reasons.append("This conversation looks resolved")
    if not reasons:
        reasons.append("Kept visible for awareness")

    return reasons[:3]


def next_step_label(record: dict[str, Any]) -> str:
    """Return a short action line that reads well in the queue."""

    if normalize_text(record.get("security_status")) == "classified":
        return "Open the thread in Gmail and review it manually."

    action = str(record.get("predicted_next_action") or "").strip()
    if action:
        return action

    if record.get("waiting_on_us"):
        return "Open the thread and decide whether to reply."
    if record.get("resolved_or_closed"):
        return "No action needed unless something changes."
    return "Review when convenient."


def display_category(record: dict[str, Any]) -> str:
    """Return the best business category label for end-user display."""

    if normalize_text(record.get("security_status")) == "classified":
        return "Classified / Sensitive"

    category = str(record.get("predicted_category") or "").strip()
    if category:
        return category

    return "Uncategorized"


def user_friendly_summary(record: dict[str, Any]) -> str:
    """Return the best summary available for a non-technical reader."""

    summary = str(record.get("predicted_summary") or "").strip()
    if summary:
        return _shorten_text(summary)

    preview = str(record.get("latest_message_preview") or "").strip()
    if preview:
        return _shorten_text(preview)

    subject = str(record.get("subject") or "").strip()
    if subject:
        return f"Conversation about {subject}."

    return "No summary available yet."


def queue_sort_key(record: dict[str, Any]) -> tuple[int, datetime]:
    priority = user_priority(record)
    return (int(priority["rank"]), _safe_record_date(record))


def sort_for_end_user(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort the queue by attention level, then by most recent thread."""

    sorted_records = list(records)
    sorted_records.sort(key=lambda record: _safe_record_date(record), reverse=True)
    sorted_records.sort(key=lambda record: int(user_priority(record)["rank"]))
    return sorted_records


def sort_latest_first(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort conversations only by the latest message date, newest first."""

    sorted_records = list(records)
    sorted_records.sort(key=lambda record: _safe_record_date(record), reverse=True)
    return sorted_records


def build_priority_sections(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group threads into practical sections for the end-user dashboard."""

    ordered_records = sort_for_end_user(records)

    def in_section(record: dict[str, Any], label: str) -> bool:
        return user_priority(record)["label"] == label

    return [
        {
            "title": "Needs attention today",
            "items": [record for record in ordered_records if in_section(record, "Today")],
            "empty": "Nothing looks like a same-day action item.",
        },
        {
            "title": "Review soon",
            "items": [record for record in ordered_records if in_section(record, "Soon")],
            "empty": "No medium-priority work is waiting right now.",
        },
        {
            "title": "Watch list",
            "items": [record for record in ordered_records if in_section(record, "Watch")],
            "empty": "No watch-list threads are visible.",
        },
        {
            "title": "Manual only",
            "items": [record for record in ordered_records if in_section(record, "Manual only")],
            "empty": "No sensitive threads are currently blocked from AI.",
        },
        {
            "title": "FYI / done",
            "items": [
                record
                for record in ordered_records
                if in_section(record, "FYI") or in_section(record, "Done")
            ],
            "empty": "No low-priority or resolved threads are visible.",
        },
    ]


def build_dashboard_sections(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Partition the active dashboard queue into clear daily work sections."""

    ordered_records = sort_for_end_user(records)
    sections = [
        {
            "title": "Needs attention today",
            "items": [],
            "empty": "Nothing looks like a same-day action item.",
        },
        {
            "title": "New since last run",
            "items": [],
            "empty": "No newly surfaced conversations are waiting.",
        },
        {
            "title": "Changed since last run",
            "items": [],
            "empty": "No previously seen conversations changed.",
        },
        {
            "title": "Sensitive / manual only",
            "items": [],
            "empty": "No sensitive conversations need manual handling right now.",
        },
        {
            "title": "Review soon",
            "items": [],
            "empty": "No medium-priority review items are waiting.",
        },
        {
            "title": "FYI / done",
            "items": [],
            "empty": "No low-priority or resolved conversations are visible.",
        },
    ]
    section_map = {section["title"]: section for section in sections}

    for record in ordered_records:
        priority_label = str(user_priority(record)["label"])
        change_status = normalize_text(record.get("change_status"))
        security_status = normalize_text(record.get("security_status"))

        if security_status == "classified":
            section_map["Sensitive / manual only"]["items"].append(record)
        elif priority_label == "Today":
            section_map["Needs attention today"]["items"].append(record)
        elif change_status == "new":
            section_map["New since last run"]["items"].append(record)
        elif change_status == "changed":
            section_map["Changed since last run"]["items"].append(record)
        elif priority_label == "Soon":
            section_map["Review soon"]["items"].append(record)
        else:
            section_map["FYI / done"]["items"].append(record)

    return sections


def dashboard_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    """Build a small dashboard summary from the current records."""

    counts = {
        "today": 0,
        "soon": 0,
        "watch": 0,
        "manual_only": 0,
        "fyi_or_done": 0,
    }
    for record in records:
        label = user_priority(record)["label"]
        if label == "Today":
            counts["today"] += 1
        elif label == "Soon":
            counts["soon"] += 1
        elif label == "Watch":
            counts["watch"] += 1
        elif label == "Manual only":
            counts["manual_only"] += 1
        else:
            counts["fyi_or_done"] += 1
    return counts


def dashboard_snapshot(
    records: list[dict[str, Any]],
    seen_records: list[dict[str, Any]],
) -> dict[str, int]:
    """Return the main operational counts for the dashboard hero."""

    snapshot = {
        "today": 0,
        "new": 0,
        "changed": 0,
        "manual_only": 0,
        "seen": len(seen_records),
    }

    for record in records:
        if normalize_text(record.get("security_status")) == "classified":
            snapshot["manual_only"] += 1
        elif str(user_priority(record)["label"]) == "Today":
            snapshot["today"] += 1
        elif normalize_text(record.get("change_status")) == "new":
            snapshot["new"] += 1
        elif normalize_text(record.get("change_status")) == "changed":
            snapshot["changed"] += 1

    return snapshot
