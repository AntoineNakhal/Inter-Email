"""Helpers to keep AI summaries compact and proportional to the source email."""

from __future__ import annotations

import re

from backend.core.email_text import normalize_email_text
from backend.domain.thread import EmailThread
from backend.providers.ai.analysis_style import latest_sender_name, latest_thread_text


SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
GREETING_PREFIX_RE = re.compile(r"^(?:hi|hello|dear)\s+[a-z0-9_.-]+[,:]?\s*", re.IGNORECASE)


def fit_summary_to_thread(summary: str, thread: EmailThread) -> str:
    """Use the AI's summary as-is. Only fill in when empty or a raw greeting."""
    cleaned = normalize_email_text(summary)
    if not cleaned or GREETING_PREFIX_RE.match(cleaned):
        return suggest_summary(thread)
    return cleaned


def suggest_summary(thread: EmailThread) -> str:
    """Last-resort fallback when the AI produced no usable summary."""
    sender_name = latest_sender_name(thread)
    sender_phrase = sender_name or "The sender"
    subject = thread.subject.strip()
    subject_phrase = f' about "{subject}"' if subject else ""

    if thread.waiting_on_us:
        return f"{sender_phrase} is waiting for your reply{subject_phrase}."
    if thread.latest_message_from_me:
        return f"You sent the latest message{subject_phrase} and are waiting for a response."
    return f"New message{subject_phrase} — review to decide next steps."


def _thread_signal_length(thread: EmailThread) -> int:
    recent_parts: list[str] = []
    for message in thread.messages[-3:]:
        candidate = "\n".join(
            part
            for part in [
                message.subject,
                message.snippet,
                message.cleaned_body,
            ]
            if part
        ).strip()
        if candidate:
            recent_parts.append(candidate[:400])

    signal = "\n".join(recent_parts).strip()
    if not signal:
        signal = normalize_email_text(thread.combined_thread_text or thread.subject)
    return len(signal)


def _summary_max_chars(signal_length: int) -> int:
    if signal_length <= 40:
        return max(18, signal_length)
    if signal_length <= 120:
        return min(signal_length, 72)
    if signal_length <= 220:
        return 110
    if signal_length <= 400:
        return 160
    return 220


def _should_replace_summary(summary: str, thread: EmailThread) -> bool:
    lowered = summary.lower()
    latest_text = latest_thread_text(thread)
    if GREETING_PREFIX_RE.match(summary):
        return True
    if any(
        phrase in lowered
        for phrase in ("did you receive", "did you get this", "confirm receipt", "received this?")
    ):
        return True
    if "meet.google.com" in lowered:
        return True
    if len(latest_text) <= 160 and lowered == latest_text:
        return True
    return False
