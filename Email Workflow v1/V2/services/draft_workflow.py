"""Shared helpers for reply-draft planning and end-user wizard generation."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from agents.reply_draft_agent import ReplyDraftAgentRunner
from config import get_settings
from schemas import (
    DraftGenerationRequest,
    EmailThread,
    GeneratedReplyDraft,
    ThreadMessage,
    ThreadReplyDraftBatch,
    ThreadReplyDraftRecord,
)


DATE_HINT_PATTERNS = (
    "meeting",
    "schedule",
    "reschedule",
    "availability",
    "available",
    "calendar",
    "call",
    "appointment",
    "event",
    "webinar",
    "demo",
    "next week",
    "next monday",
    "next tuesday",
    "next wednesday",
    "next thursday",
    "next friday",
    "tomorrow",
)

ATTACHMENT_HINT_PATTERNS = (
    "attach",
    "attached",
    "attachment",
    "document",
    "file",
    "pdf",
    "deck",
    "proposal",
    "quote",
    "invoice",
    "contract",
    "resume",
    "brochure",
    "statement of work",
    "scope of work",
)


def draft_steps_for_record(record: dict[str, Any]) -> list[str]:
    """Return only the wizard steps that matter for this thread."""

    steps: list[str] = []
    if bool(record.get("draft_needs_date")):
        steps.append("date")
    if bool(record.get("draft_needs_attachment")):
        steps.append("attachment")
    steps.append("instructions")
    steps.append("preview")
    return steps


def email_thread_from_record(record: dict[str, Any]) -> EmailThread:
    """Rebuild one EmailThread model from the UI-friendly record dict."""

    messages = [
        ThreadMessage(
            message_id=str(message.get("message_id") or ""),
            sender=str(message.get("sender") or ""),
            subject=str(message.get("subject") or ""),
            date=str(message.get("date") or ""),
            snippet=str(message.get("snippet") or ""),
            cleaned_body=str(message.get("cleaned_body") or ""),
        )
        for message in record.get("messages", [])
    ]

    return EmailThread(
        thread_id=str(record.get("thread_id") or record.get("id") or ""),
        source_thread_ids=[
            str(item)
            for item in record.get("source_thread_ids", [])
            if str(item or "").strip()
        ],
        grouping_reason=str(record.get("grouping_reason") or "gmail_thread_id"),
        merge_signals=[
            str(item) for item in record.get("merge_signals", []) if str(item or "").strip()
        ],
        merge_confidence=record.get("merge_confidence"),
        subject=str(record.get("subject") or ""),
        participants=[
            str(item) for item in record.get("participants", []) if str(item or "").strip()
        ],
        message_count=int(record.get("message_count") or len(messages) or 0),
        latest_message_date=str(record.get("latest_message_date") or ""),
        messages=messages,
        combined_thread_text=str(record.get("combined_thread_text") or ""),
        security_status=(
            "classified"
            if str(record.get("security_status") or "").strip().lower()
            == "classified"
            else "standard"
        ),
        sensitivity_markers=[
            str(item)
            for item in record.get("sensitivity_markers", [])
            if str(item or "").strip()
        ],
        sensitivity_reason=record.get("sensitivity_reason"),
        latest_message_from_me=bool(record.get("latest_message_from_me", False)),
        latest_message_from_external=bool(
            record.get("latest_message_from_external", False)
        ),
        latest_message_has_question=bool(
            record.get("latest_message_has_question", False)
        ),
        latest_message_has_action_request=bool(
            record.get("latest_message_has_action_request", False)
        ),
        waiting_on_us=bool(record.get("waiting_on_us", False)),
        resolved_or_closed=bool(record.get("resolved_or_closed", False)),
        predicted_category=record.get("predicted_category"),
        predicted_urgency=record.get("predicted_urgency"),
        predicted_summary=record.get("predicted_summary"),
        predicted_status=record.get("predicted_status"),
        predicted_needs_action_today=record.get("predicted_needs_action_today"),
        predicted_next_action=record.get("predicted_next_action"),
        should_draft_reply=record.get("should_draft_reply"),
        draft_needs_date=bool(record.get("draft_needs_date", False)),
        draft_date_reason=record.get("draft_date_reason"),
        draft_needs_attachment=bool(record.get("draft_needs_attachment", False)),
        draft_attachment_reason=record.get("draft_attachment_reason"),
        thread_signature=str(record.get("thread_signature") or ""),
        relevance_bucket=record.get("relevance_bucket"),
        ai_decision=record.get("ai_decision"),
        ai_decision_reason=record.get("ai_decision_reason"),
        change_status=record.get("change_status"),
        analysis_status=record.get("analysis_status"),
        last_analysis_at=record.get("last_analysis_at"),
        relevance_score=record.get("relevance_score"),
        included_in_ai=bool(record.get("included_in_ai", False)),
        selection_reason=str(record.get("selection_reason") or ""),
    )


def fallback_reply_plan(thread: EmailThread) -> ThreadReplyDraftRecord:
    """Fallback metadata when OpenAI planning is unavailable."""

    should_draft = should_generate_reply_draft(thread)
    if not should_draft:
        return ThreadReplyDraftRecord(thread_id=thread.thread_id, should_draft_reply=False)

    text = _thread_text(thread)
    needs_date = (
        thread.predicted_category == "Events / Logistics"
        or any(pattern in text for pattern in DATE_HINT_PATTERNS)
    )
    needs_attachment = any(pattern in text for pattern in ATTACHMENT_HINT_PATTERNS)

    return ThreadReplyDraftRecord(
        thread_id=thread.thread_id,
        should_draft_reply=True,
        needs_date=needs_date,
        date_reason=(
            "This reply will probably work better with a date or availability window."
            if needs_date
            else None
        ),
        needs_attachment=needs_attachment,
        attachment_reason=(
            "The thread mentions files or documents that may need to be attached."
            if needs_attachment
            else None
        ),
    )


def fallback_reply_plan_batch(threads: list[EmailThread]) -> ThreadReplyDraftBatch:
    """Fallback metadata batch for multiple threads."""

    return ThreadReplyDraftBatch(records=[fallback_reply_plan(thread) for thread in threads])


def fallback_generate_reply_draft(
    thread: EmailThread,
    draft_request: DraftGenerationRequest,
) -> GeneratedReplyDraft:
    """Fallback final draft used when AI generation is unavailable."""

    latest_message = thread.messages[-1] if thread.messages else None
    recipient_name = extract_first_name(latest_message.sender if latest_message else "")
    greeting = f"Hi {recipient_name}," if recipient_name else "Hi,"

    subject = (thread.subject or "Conversation update").strip() or "Conversation update"
    if not subject.lower().startswith(("re:", "fw:", "fwd:")):
        subject = f"Re: {subject}"

    body_lines = [greeting, "", "Thanks for the update."]

    if thread.predicted_summary:
        body_lines.append(thread.predicted_summary.strip())

    if draft_request.user_instructions.strip():
        body_lines.append(
            f"Please note: {draft_request.user_instructions.strip().rstrip('.')}"
        )

    if draft_request.selected_date:
        body_lines.append(
            f"We are available on {draft_request.selected_date} and can move forward from there."
        )

    if draft_request.attachment_names:
        attachment_label = ", ".join(draft_request.attachment_names)
        body_lines.append(f"I've attached {attachment_label} for reference.")
    elif thread.predicted_next_action:
        body_lines.append(
            f"We are reviewing the next step on our side: {thread.predicted_next_action.strip().rstrip('.')}."
        )

    if thread.predicted_needs_action_today:
        body_lines.append("We will get back to you today with the next update.")
    else:
        body_lines.append("We will follow up shortly with the next update.")

    body_lines.extend(["", "Best,", "[Your Name]"])
    return GeneratedReplyDraft(subject=subject, body="\n".join(body_lines).strip())


def generate_reply_draft_for_record(
    record: dict[str, Any],
    draft_request: DraftGenerationRequest,
) -> GeneratedReplyDraft:
    """Generate one final draft from the wizard inputs for a UI record."""

    thread = email_thread_from_record(record)
    env_path = Path(__file__).resolve().parents[1] / ".env"
    load_dotenv(env_path if env_path.exists() else None)
    get_settings.cache_clear()
    settings = get_settings()

    use_fallback = settings.processing_mode == "fallback" or not os.getenv(
        "OPENAI_API_KEY"
    )
    if use_fallback:
        return fallback_generate_reply_draft(thread, draft_request)

    runner = ReplyDraftAgentRunner(model=settings.openai_model)
    try:
        return runner.generate_draft(thread, draft_request)
    except Exception:
        return fallback_generate_reply_draft(thread, draft_request)


def should_generate_reply_draft(thread: EmailThread) -> bool:
    """Return whether email is the next likely move."""

    if thread.resolved_or_closed:
        return False
    if not thread.latest_message_from_external:
        return False
    return bool(
        thread.waiting_on_us
        or thread.latest_message_has_question
        or thread.latest_message_has_action_request
        or thread.predicted_needs_action_today
    )


def extract_first_name(value: str) -> str:
    """Pull a readable first name from a sender string."""

    cleaned = (value or "").split("<", 1)[0].strip().strip('"')
    if not cleaned:
        return ""
    cleaned = re.sub(r"\s+", " ", cleaned)
    if "," in cleaned:
        parts = [part.strip() for part in cleaned.split(",") if part.strip()]
        if len(parts) >= 2:
            return parts[1].split()[0]
    return cleaned.split()[0]


def _thread_text(thread: EmailThread) -> str:
    return " ".join(
        [
            str(thread.subject or ""),
            str(thread.combined_thread_text or ""),
            str(thread.predicted_summary or ""),
            str(thread.predicted_next_action or ""),
        ]
    ).lower()
