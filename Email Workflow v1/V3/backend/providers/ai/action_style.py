"""Helpers for keeping next actions specific to the actual email content."""

from __future__ import annotations

from email.utils import parseaddr

from backend.core.email_text import normalize_email_text
from backend.domain.thread import EmailThread, RelevanceBucket


GENERIC_ACTION_PREFIXES = (
    "prepare and send a reply",
    "prepare a follow-up reply",
    "prepare a reply",
    "send a reply",
    "reply today",
    "follow up today",
    "follow up shortly",
    "review the thread and decide the next owner",
)

AUTOMATED_SENDER_HINTS = (
    "no-reply",
    "noreply",
    "do-not-reply",
    "donotreply",
    "mailer-daemon",
    "postmaster",
    "notifications",
    "notification",
    "alerts",
    "alert",
    "calendar-notification",
)

AUTOMATED_CONTENT_HINTS = (
    "automated message",
    "automatic reply",
    "notification",
    "newsletter",
    "digest",
    "system alert",
    "monitoring alert",
    "calendar notification",
)


def fit_next_action_to_thread(raw_action: str, thread: EmailThread) -> str:
    """Pass AI output through unchanged. No heuristic fallback — the AI prompt
    enforces a non-empty next_action whenever needs_next_action is true."""
    return normalize_email_text(raw_action)


def fit_needs_next_action_to_thread(raw_flag: object, thread: EmailThread) -> bool:
    """Trust the AI's judgment. Only override resolved threads."""
    if thread.resolved_or_closed:
        return False
    return bool(raw_flag)


def clear_non_action_fields(normalized: dict[str, object]) -> dict[str, object]:
    normalized["next_action"] = ""
    normalized["needs_action_today"] = False
    normalized["should_draft_reply"] = False
    normalized["draft_needs_date"] = False
    normalized["draft_date_reason"] = None
    normalized["draft_needs_attachment"] = False
    normalized["draft_attachment_reason"] = None
    return normalized


def suggest_next_action(thread: EmailThread) -> str:
    # Service emails never require a reply — action is always external.
    if getattr(thread, "is_service_email", False):
        latest_text_for_service = normalize_email_text(
            "\n".join(
                part for part in [
                    thread.messages[-1].subject if thread.messages else thread.subject,
                    thread.messages[-1].snippet if thread.messages else "",
                ]
                if part
            )
        ).lower()
        if any(p in latest_text_for_service for p in ("register", "sign up", "rsvp", "save your spot")):
            return "Decide whether to register and click the link if yes."
        if any(p in latest_text_for_service for p in ("invoice", "receipt", "payment", "billing")):
            return "Review the receipt or invoice for your records."
        if any(p in latest_text_for_service for p in ("security", "alert", "suspicious", "verify")):
            return "Review the security alert and take the recommended action if needed."
        return "Review this notification and take any required action via the link."

    latest_message = thread.messages[-1] if thread.messages else None
    latest_text = normalize_email_text(
        "\n".join(
            part
            for part in [
                latest_message.subject if latest_message else thread.subject,
                latest_message.snippet if latest_message else "",
                latest_message.cleaned_body if latest_message else thread.combined_thread_text,
            ]
            if part
        )
    ).lower()
    sender_name = _first_name(
        latest_message.sender
        if latest_message and latest_message.sender
        else thread.participants[0]
        if thread.participants
        else ""
    )
    sender_phrase = f" {sender_name}" if sender_name else " the sender"
    subject_phrase = f' about "{thread.subject.strip()}"' if thread.subject.strip() else ""

    if any(
        phrase in latest_text
        for phrase in (
            "did you receive",
            "did you get this",
            "confirm receipt",
            "received this?",
        )
    ):
        return f"Reply to{sender_phrase} confirming you received this."

    if any(
        phrase in latest_text
        for phrase in (
            "reschedule",
            "new time",
            "moved to",
            "does this time work",
            "availability",
            "calendar invite",
        )
    ):
        return f"Reply to{sender_phrase} confirming whether the proposed time works."

    if any(
        phrase in latest_text
        for phrase in (
            "meet.google.com",
            "google meet",
            "meeting link",
            "join link",
        )
    ):
        return f"Check the meeting link and reply to{sender_phrase} if a confirmation is needed."

    if any(
        phrase in latest_text
        for phrase in (
            "quote",
            "purchase order",
            "invoice",
            "proposal",
            "contract",
        )
    ):
        return (
            f"Review the requested document and reply to{sender_phrase} "
            "with approval, questions, or the next step."
        )

    if thread.waiting_on_us:
        return f"Reply to{sender_phrase}{subject_phrase} with the requested confirmation."

    if thread.latest_message_from_me:
        return f"Monitor for{sender_phrase} response{subject_phrase}."

    return f"Review{subject_phrase or ' this thread'} and decide the next owner."


def _is_too_generic(lowered: str) -> bool:
    generic_tokens = (
        "reply",
        "follow up",
        "next step",
        "review the thread",
        "decide the next owner",
    )
    return any(token in lowered for token in generic_tokens) and not any(
        token in lowered
        for token in (
            "confirm",
            "quote",
            "invoice",
            "meeting",
            "link",
            "schedule",
            "receipt",
        )
    )


def _looks_like_automated_no_action(thread: EmailThread) -> bool:
    if thread.latest_message_has_question or thread.latest_message_has_action_request:
        return False
    latest_message = thread.messages[-1] if thread.messages else None
    sender = latest_message.sender if latest_message else ""
    _, sender_email = parseaddr(sender)
    sender_email = sender_email.lower()
    if any(hint in sender_email for hint in AUTOMATED_SENDER_HINTS):
        return True

    latest_text = normalize_email_text(
        "\n".join(
            part
            for part in [
                latest_message.subject if latest_message else thread.subject,
                latest_message.snippet if latest_message else "",
                latest_message.cleaned_body if latest_message else thread.combined_thread_text,
            ]
            if part
        )
    ).lower()
    return any(hint in latest_text for hint in AUTOMATED_CONTENT_HINTS)


def _first_name(raw_value: str) -> str:
    name, email_address = parseaddr(raw_value)
    candidate = (name or email_address.split("@")[0]).strip().strip('"')
    if "," in candidate:
        candidate = candidate.split(",", 1)[1].strip()
    return candidate.split()[0].title() if candidate else ""
