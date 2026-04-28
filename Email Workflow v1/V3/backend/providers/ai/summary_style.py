"""Helpers to keep AI summaries compact and proportional to the source email."""

from __future__ import annotations

import re

from backend.core.email_text import normalize_email_text
from backend.domain.thread import EmailThread
from backend.providers.ai.analysis_style import latest_sender_name, latest_thread_text


SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
GREETING_PREFIX_RE = re.compile(r"^(?:hi|hello|dear)\s+[a-z0-9_.-]+[,:]?\s*", re.IGNORECASE)


def fit_summary_to_thread(summary: str, thread: EmailThread) -> str:
    cleaned = normalize_email_text(summary)
    suggested = suggest_summary(thread)
    if not cleaned:
        return suggested

    if _should_replace_summary(cleaned, thread):
        return suggested

    max_chars = _summary_max_chars(_thread_signal_length(thread))
    if len(cleaned) <= max_chars:
        return cleaned

    for sentence in SENTENCE_SPLIT_RE.split(cleaned):
        compact_sentence = sentence.strip()
        if 16 <= len(compact_sentence) <= max_chars:
            return compact_sentence

    clipped = cleaned[: max_chars + 1].strip()
    if len(clipped) > max_chars and " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    return f"{clipped.rstrip(' ,;:.')}..."


def suggest_summary(thread: EmailThread) -> str:
    latest_text = latest_thread_text(thread)
    sender_name = latest_sender_name(thread)
    sender_phrase = sender_name or "The sender"

    if any(
        phrase in latest_text
        for phrase in ("did you receive", "did you get this", "confirm receipt", "received this?")
    ):
        return f"{sender_phrase} is asking for confirmation that the message was received."
    if any(
        phrase in latest_text
        for phrase in ("reschedule", "new time", "moved to", "does this time work", "availability")
    ):
        return f"{sender_phrase} proposed a scheduling change and is waiting for confirmation."
    if any(
        phrase in latest_text
        for phrase in ("meet.google.com", "google meet", "meeting link", "join link")
    ):
        return f"{sender_phrase} shared the meeting link for the conversation."
    if any(
        phrase in latest_text
        for phrase in ("quote", "purchase order", "invoice", "proposal", "contract")
    ):
        return f"{sender_phrase} requested review of a business document."
    if thread.waiting_on_us:
        return f"{sender_phrase} is waiting for a reply from Inter-Op."
    if thread.latest_message_from_me:
        return "Inter-Op sent the latest message and is waiting for a response."
    return "The thread contains a recent update that may need review."


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
