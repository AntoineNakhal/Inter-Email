"""Thread API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from backend.domain.analysis import QueueSummaryResult
from backend.domain.thread import EmailThread


class ThreadMessageResponse(BaseModel):
    message_id: str
    sender: str
    recipients: list[str] = Field(default_factory=list)
    subject: str
    sent_at: datetime | None = None
    snippet: str = ""
    cleaned_body: str = ""


class ThreadAnalysisResponse(BaseModel):
    category: str
    urgency: str
    summary: str
    current_status: str
    next_action: str
    needs_action_today: bool
    should_draft_reply: bool
    draft_needs_date: bool
    draft_date_reason: str | None = None
    draft_needs_attachment: bool
    draft_attachment_reason: str | None = None
    crm_contact_name: str | None = None
    crm_company: str | None = None
    crm_opportunity_type: str | None = None
    crm_urgency: str | None = None
    provider_name: str
    model_name: str
    used_fallback: bool
    analyzed_at: datetime | None = None


class SeenStateResponse(BaseModel):
    seen: bool
    seen_version: str
    seen_at: datetime | None = None


class ReviewDecisionResponse(BaseModel):
    queue_belongs: str
    merge_correct: str
    summary_useful: str
    next_action_useful: str
    draft_useful: str
    crm_useful: str
    notes: str
    improvement_tags: list[str] = Field(default_factory=list)
    updated_at: datetime | None = None


class DraftResponse(BaseModel):
    subject: str
    body: str
    provider_name: str
    model_name: str
    used_fallback: bool
    created_at: datetime | None = None


class ThreadResponse(BaseModel):
    thread_id: str
    subject: str
    participants: list[str] = Field(default_factory=list)
    message_count: int
    latest_message_date: datetime | None = None
    security_status: str
    sensitivity_markers: list[str] = Field(default_factory=list)
    waiting_on_us: bool
    resolved_or_closed: bool
    relevance_score: int | None = None
    relevance_bucket: str | None = None
    included_in_ai: bool
    ai_decision: str | None = None
    ai_decision_reason: str | None = None
    analysis_status: str
    signature: str
    messages: list[ThreadMessageResponse] = Field(default_factory=list)
    analysis: ThreadAnalysisResponse | None = None
    seen_state: SeenStateResponse | None = None
    review: ReviewDecisionResponse | None = None
    latest_draft: DraftResponse | None = None

    @classmethod
    def from_domain(cls, thread: EmailThread) -> "ThreadResponse":
        return cls(
            thread_id=thread.external_thread_id,
            subject=thread.subject,
            participants=thread.participants,
            message_count=thread.message_count,
            latest_message_date=thread.latest_message_date,
            security_status=thread.security_status.value,
            sensitivity_markers=thread.sensitivity_markers,
            waiting_on_us=thread.waiting_on_us,
            resolved_or_closed=thread.resolved_or_closed,
            relevance_score=thread.relevance_score,
            relevance_bucket=(
                thread.relevance_bucket.value if thread.relevance_bucket else None
            ),
            included_in_ai=thread.included_in_ai,
            ai_decision=thread.ai_decision,
            ai_decision_reason=thread.ai_decision_reason,
            analysis_status=thread.analysis_status.value,
            signature=thread.signature,
            messages=[
                ThreadMessageResponse(
                    message_id=message.external_message_id,
                    sender=message.sender,
                    recipients=message.recipients,
                    subject=message.subject,
                    sent_at=message.sent_at,
                    snippet=message.snippet,
                    cleaned_body=message.cleaned_body,
                )
                for message in thread.messages
            ],
            analysis=(
                ThreadAnalysisResponse(
                    category=thread.analysis.category.value,
                    urgency=thread.analysis.urgency.value,
                    summary=thread.analysis.summary,
                    current_status=thread.analysis.current_status,
                    next_action=thread.analysis.next_action,
                    needs_action_today=thread.analysis.needs_action_today,
                    should_draft_reply=thread.analysis.should_draft_reply,
                    draft_needs_date=thread.analysis.draft_needs_date,
                    draft_date_reason=thread.analysis.draft_date_reason,
                    draft_needs_attachment=thread.analysis.draft_needs_attachment,
                    draft_attachment_reason=thread.analysis.draft_attachment_reason,
                    crm_contact_name=thread.analysis.crm_contact_name,
                    crm_company=thread.analysis.crm_company,
                    crm_opportunity_type=thread.analysis.crm_opportunity_type,
                    crm_urgency=(
                        thread.analysis.crm_urgency.value
                        if thread.analysis.crm_urgency
                        else None
                    ),
                    provider_name=thread.analysis.provider_name,
                    model_name=thread.analysis.model_name,
                    used_fallback=thread.analysis.used_fallback,
                    analyzed_at=thread.analysis.analyzed_at,
                )
                if thread.analysis
                else None
            ),
            seen_state=(
                SeenStateResponse(
                    seen=thread.seen_state.seen,
                    seen_version=thread.seen_state.seen_version,
                    seen_at=thread.seen_state.seen_at,
                )
                if thread.seen_state
                else None
            ),
            review=(
                ReviewDecisionResponse(
                    queue_belongs=thread.review.queue_belongs,
                    merge_correct=thread.review.merge_correct,
                    summary_useful=thread.review.summary_useful,
                    next_action_useful=thread.review.next_action_useful,
                    draft_useful=thread.review.draft_useful,
                    crm_useful=thread.review.crm_useful,
                    notes=thread.review.notes,
                    improvement_tags=thread.review.improvement_tags,
                    updated_at=thread.review.updated_at,
                )
                if thread.review
                else None
            ),
            latest_draft=(
                DraftResponse(
                    subject=thread.latest_draft.subject,
                    body=thread.latest_draft.body,
                    provider_name=thread.latest_draft.provider_name,
                    model_name=thread.latest_draft.model_name,
                    used_fallback=thread.latest_draft.used_fallback,
                    created_at=thread.latest_draft.created_at,
                )
                if thread.latest_draft
                else None
            ),
        )


class QueueSummaryResponse(BaseModel):
    top_priorities: list[str] = Field(default_factory=list)
    executive_summary: str = ""
    next_actions: list[str] = Field(default_factory=list)
    provider_name: str = "heuristic"
    model_name: str = "deterministic-fallback"
    used_fallback: bool = False

    @classmethod
    def from_domain(cls, summary: QueueSummaryResult) -> "QueueSummaryResponse":
        return cls(**summary.model_dump())


class ThreadListResponse(BaseModel):
    threads: list[ThreadResponse] = Field(default_factory=list)


class QueueDashboardResponse(BaseModel):
    threads: list[ThreadResponse] = Field(default_factory=list)
    summary: QueueSummaryResponse
