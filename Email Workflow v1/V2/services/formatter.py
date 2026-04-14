"""Formatting helpers for readable agent inputs."""

from __future__ import annotations

from schemas import (
    AgentThread,
    DraftGenerationRequest,
    EmailThread,
    ThreadTriageItem,
)


def agent_threads_to_payload(
    threads: list[AgentThread],
) -> list[dict[str, str | int | list[str] | list[dict[str, str]]]]:
    """Return plain dictionaries so agent payloads stay clean and predictable."""

    return [thread.model_dump() for thread in threads]


def triage_items_to_payload(
    items: list[ThreadTriageItem],
) -> list[dict[str, str | bool]]:
    """Return plain dictionaries for summary payloads."""

    return [item.model_dump() for item in items]


def reply_draft_threads_to_payload(
    threads: list[EmailThread],
) -> list[dict[str, object]]:
    """Return the compact thread context needed for reply drafting."""

    payload: list[dict[str, object]] = []

    for thread in threads:
        payload.append(
            {
                "thread_id": thread.thread_id,
                "subject": thread.subject,
                "participants": thread.participants,
                "message_count": thread.message_count,
                "latest_message_date": thread.latest_message_date,
                "messages": [message.model_dump() for message in thread.messages],
                "combined_thread_text": thread.combined_thread_text,
                "latest_message_from_me": thread.latest_message_from_me,
                "latest_message_from_external": thread.latest_message_from_external,
                "latest_message_has_question": thread.latest_message_has_question,
                "latest_message_has_action_request": thread.latest_message_has_action_request,
                "waiting_on_us": thread.waiting_on_us,
                "resolved_or_closed": thread.resolved_or_closed,
                "predicted_category": thread.predicted_category,
                "predicted_urgency": thread.predicted_urgency,
                "predicted_summary": thread.predicted_summary,
                "predicted_status": thread.predicted_status,
                "predicted_needs_action_today": thread.predicted_needs_action_today,
                "predicted_next_action": thread.predicted_next_action,
                "should_draft_reply": thread.should_draft_reply,
                "draft_needs_date": thread.draft_needs_date,
                "draft_date_reason": thread.draft_date_reason,
                "draft_needs_attachment": thread.draft_needs_attachment,
                "draft_attachment_reason": thread.draft_attachment_reason,
            }
        )

    return payload


def reply_draft_thread_to_payload(thread: EmailThread) -> dict[str, object]:
    """Return one compact thread payload for on-demand draft generation."""

    return reply_draft_threads_to_payload([thread])[0]


def draft_request_to_payload(request: DraftGenerationRequest) -> dict[str, object]:
    """Return plain user inputs for the on-demand draft generator."""

    return request.model_dump()
