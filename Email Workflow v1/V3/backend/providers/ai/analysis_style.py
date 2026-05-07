"""Helpers for keeping thread analysis grounded in the actual latest email."""

from __future__ import annotations

from email.utils import parseaddr

from backend.core.email_text import FOOTER_MARKERS, normalize_email_text
from backend.domain.thread import EmailThread


GENERIC_STATUS_PHRASES = (
    "waiting on inter-op to respond",
    "waiting on inter-op",
    "waiting on us",
    "conversation needs monitoring",
    "review required",
    "awaiting response",
)

EVENT_PHRASES = (
    "register now",
    "register here",
    "save your spot",
    "rsvp",
    "join us",
    "webinar",
    "coaching session",
    "virtual event",
    "online event",
    "sign up",
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
    """Use the AI's status as-is. Empty stays empty — no heuristic fill."""
    return normalize_email_text(raw_status)


def suggest_current_status(thread: EmailThread) -> str:
    latest_text = latest_thread_text(thread)
    sender_name = latest_sender_name(thread)
    sender_phrase = sender_name or "sender"

    if any(phrase in latest_text for phrase in EVENT_PHRASES):
        return f"Invitation from {sender_phrase} — decision pending."
    if any(phrase in latest_text for phrase in RECEIPT_PHRASES):
        return f"You need to confirm receipt to {sender_phrase}."
    if any(phrase in latest_text for phrase in SCHEDULING_PHRASES):
        return f"You need to confirm the schedule with {sender_phrase}."
    if any(phrase in latest_text for phrase in MEETING_LINK_PHRASES):
        return "Meeting details shared — confirm if needed."
    if any(phrase in latest_text for phrase in DOCUMENT_PHRASES):
        return f"Document from {sender_phrase} needs your review."
    if thread.waiting_on_us:
        return f"{sender_phrase} is waiting for your reply."
    if thread.latest_message_from_me:
        return f"Waiting on {sender_phrase} to respond."
    if thread.resolved_or_closed:
        return "Resolved."
    return "Needs a quick review."


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
    # Substring match — catches variants like "Waiting on Inter-Op to reply to Google"
    # not just the exact phrases in the list.
    return any(phrase in lowered_status for phrase in GENERIC_STATUS_PHRASES)
