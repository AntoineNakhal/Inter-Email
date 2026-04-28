"""Helpers for keeping next actions specific to the actual email content."""

from __future__ import annotations

from email.utils import parseaddr

from backend.core.email_text import normalize_email_text
from backend.domain.thread import EmailThread


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


def fit_next_action_to_thread(raw_action: str, thread: EmailThread) -> str:
    normalized = normalize_email_text(raw_action)
    suggested = suggest_next_action(thread)
    if not normalized:
        return suggested

    lowered = normalized.lower()
    if any(lowered.startswith(prefix) for prefix in GENERIC_ACTION_PREFIXES):
        return suggested

    if _is_too_generic(lowered):
        return suggested

    return normalized


def suggest_next_action(thread: EmailThread) -> str:
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


def _first_name(raw_value: str) -> str:
    name, email_address = parseaddr(raw_value)
    candidate = (name or email_address.split("@")[0]).strip().strip('"')
    if "," in candidate:
        candidate = candidate.split(",", 1)[1].strip()
    return candidate.split()[0].title() if candidate else ""
