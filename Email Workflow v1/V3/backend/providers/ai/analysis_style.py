"""Helpers for keeping thread analysis grounded in the actual latest email."""

from __future__ import annotations

from email.utils import parseaddr

from backend.core.email_text import FOOTER_MARKERS, normalize_email_text
from backend.domain.thread import EmailThread


GENERIC_STATUS_PHRASES = (
    "waiting on inter-op to respond",
    "waiting on us",
    "conversation needs monitoring",
    "review required",
    "awaiting response",
)

RECEIPT_PHRASES = (
    "did you receive",
    "did you get this",
    "confirm receipt",
    "received this?",
)
SCHEDULING_PHRASES = (
    "reschedule",
    "new time",
    "moved to",
    "does this time work",
    "availability",
    "calendar invite",
)
MEETING_LINK_PHRASES = (
    "meet.google.com",
    "google meet",
    "meeting link",
    "join link",
)
DOCUMENT_PHRASES = (
    "quote",
    "purchase order",
    "invoice",
    "proposal",
    "contract",
)


def fit_current_status_to_thread(raw_status: str, thread: EmailThread) -> str:
    normalized = normalize_email_text(raw_status)
    suggested = suggest_current_status(thread)
    if not normalized:
        return suggested

    lowered = normalized.lower()
    if any(marker in lowered for marker in FOOTER_MARKERS):
        return suggested
    if _status_should_be_replaced(lowered, thread):
        return suggested
    return normalized


def suggest_current_status(thread: EmailThread) -> str:
    latest_text = latest_thread_text(thread)
    sender_name = latest_sender_name(thread)
    sender_phrase = sender_name or "the sender"

    if any(phrase in latest_text for phrase in RECEIPT_PHRASES):
        return f"Waiting on Inter-Op to confirm receipt to {sender_phrase}."
    if any(phrase in latest_text for phrase in SCHEDULING_PHRASES):
        return f"Waiting on Inter-Op to confirm the proposed schedule with {sender_phrase}."
    if any(phrase in latest_text for phrase in MEETING_LINK_PHRASES):
        return "Meeting details have been shared and may need a confirmation."
    if any(phrase in latest_text for phrase in DOCUMENT_PHRASES):
        return f"Waiting on Inter-Op to review the requested document from {sender_phrase}."
    if thread.waiting_on_us:
        return f"Waiting on Inter-Op to reply to {sender_phrase}."
    if thread.latest_message_from_me:
        return f"Waiting on {sender_phrase} to respond."
    if thread.resolved_or_closed:
        return "Conversation appears resolved for now."
    return "Conversation needs a quick review to decide the next step."


def latest_thread_text(thread: EmailThread) -> str:
    latest_message = thread.messages[-1] if thread.messages else None
    return normalize_email_text(
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


def latest_sender_name(thread: EmailThread) -> str:
    latest_message = thread.messages[-1] if thread.messages else None
    raw_value = (
        latest_message.sender
        if latest_message and latest_message.sender
        else thread.participants[0]
        if thread.participants
        else ""
    )
    name, email_address = parseaddr(raw_value)
    candidate = (name or email_address.split("@")[0]).strip().strip('"')
    if "," in candidate:
        candidate = candidate.split(",", 1)[1].strip()
    return candidate.split()[0].title() if candidate else ""


def _status_should_be_replaced(lowered_status: str, thread: EmailThread) -> bool:
    latest_text = latest_thread_text(thread)
    if any(phrase in latest_text for phrase in RECEIPT_PHRASES) and "receipt" not in lowered_status:
        return True
    if any(phrase in latest_text for phrase in SCHEDULING_PHRASES) and not any(
        token in lowered_status for token in ("schedule", "time", "availability", "calendar")
    ):
        return True
    if any(phrase in latest_text for phrase in MEETING_LINK_PHRASES) and "meeting" not in lowered_status:
        return True
    if any(phrase in latest_text for phrase in DOCUMENT_PHRASES) and not any(
        token in lowered_status for token in ("document", "quote", "invoice", "proposal", "contract")
    ):
        return True
    return lowered_status in GENERIC_STATUS_PHRASES
