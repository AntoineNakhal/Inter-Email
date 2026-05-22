"""Thread API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from backend.domain.analysis import QueueSummaryResult
from backend.domain.thread import EmailThread


class ThreadOverrideResponse(BaseModel):
    category: str | None = None
    urgency: str | None = None
    needs_action_today: bool | None = None
    waiting_on_us: bool | None = None
    needs_next_action: bool | None = None
    should_draft_reply: bool | None = None
    relevance_bucket: str | None = None
    notes: str = ""
    overridden_at: datetime | None = None
    updated_at: datetime | None = None


class ThreadOverrideRequest(BaseModel):
    category: str | None = None
    urgency: str | None = None
    needs_action_today: bool | None = None
    waiting_on_us: bool | None = None
    needs_next_action: bool | None = None
    should_draft_reply: bool | None = None
    relevance_bucket: str | None = None
    notes: str = ""


class ThreadMessageResponse(BaseModel):
    message_id: str
    sender: str
    recipients: list[str] = Field(default_factory=list)
    subject: str
    sent_at: datetime | None = None
    snippet: str = ""
    cleaned_body: str = ""
    is_forwarded: bool = False
    original_gmail_thread_id: str = ""


class ThreadAnalysisResponse(BaseModel):
    category: str
    urgency: str
    summary: str
    current_status: str
    next_action: str
    needs_next_action: bool
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
    accuracy_percent: int
    verification_summary: str
    needs_human_review: bool
    review_reason: str | None = None
    verifier_provider_name: str
    verifier_model_name: str
    verifier_used_fallback: bool
    analyzed_at: datetime | None = None
    verified_at: datetime | None = None
    ai_override_disagreements: dict[str, str] = Field(default_factory=dict)


class SeenStateResponse(BaseModel):
    seen: bool
    seen_version: str
    seen_at: datetime | None = None
    pinned: bool = False


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


class KbDraftSourceResponse(BaseModel):
    """One Knowledge Base chunk that was injected into the draft prompt.
    Mirrors `backend.domain.thread.KbDraftSource` 1:1 — kept as its own
    API class so we can evolve the wire shape independently."""

    document_id: int
    document_title: str
    product_name: str | None = None
    chunk_id: int
    chunk_index: int
    similarity: float
    content_preview: str


class DraftResponse(BaseModel):
    subject: str
    body: str
    provider_name: str
    model_name: str
    used_fallback: bool
    created_at: datetime | None = None
    kb_sources: list[KbDraftSourceResponse] = Field(default_factory=list)


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
    is_new: bool = False
    is_service_email: bool = False
    # Merge transparency
    grouping_reason: str = "gmail_thread_id"
    merge_signals: list[str] = Field(default_factory=list)
    source_thread_ids: list[str] = Field(default_factory=list)
    messages: list[ThreadMessageResponse] = Field(default_factory=list)
    analysis: ThreadAnalysisResponse | None = None
    seen_state: SeenStateResponse | None = None
    review: ReviewDecisionResponse | None = None
    latest_draft: DraftResponse | None = None
    override: ThreadOverrideResponse | None = None

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
            is_new=thread.is_new,
            is_service_email=thread.is_service_email,
            grouping_reason=thread.grouping_reason,
            merge_signals=thread.merge_signals,
            source_thread_ids=thread.source_thread_ids,
            messages=[
                ThreadMessageResponse(
                    message_id=message.external_message_id,
                    sender=message.sender,
                    recipients=message.recipients,
                    subject=message.subject,
                    sent_at=message.sent_at,
                    snippet=message.snippet,
                    cleaned_body=message.cleaned_body,
                    is_forwarded=message.is_forwarded,
                    original_gmail_thread_id=message.original_gmail_thread_id,
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
                    needs_next_action=thread.analysis.needs_next_action,
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
                    accuracy_percent=thread.analysis.accuracy_percent,
                    verification_summary=thread.analysis.verification_summary,
                    needs_human_review=thread.analysis.needs_human_review,
                    review_reason=thread.analysis.review_reason,
                    verifier_provider_name=thread.analysis.verifier_provider_name,
                    verifier_model_name=thread.analysis.verifier_model_name,
                    verifier_used_fallback=thread.analysis.verifier_used_fallback,
                    analyzed_at=thread.analysis.analyzed_at,
                    verified_at=thread.analysis.verified_at,
                    ai_override_disagreements=thread.analysis.ai_override_disagreements,
                )
                if thread.analysis
                else None
            ),
            seen_state=(
                SeenStateResponse(
                    seen=thread.seen_state.seen,
                    seen_version=thread.seen_state.seen_version,
                    seen_at=thread.seen_state.seen_at,
                    pinned=thread.seen_state.pinned,
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
                    # Forward the audit-trail. Without this, the thread
                    # page reads a draft with an empty kb_sources even
                    # when the DB row has them populated — the bug that
                    # made the panel always say "no sources used".
                    kb_sources=[
                        KbDraftSourceResponse(**source.model_dump())
                        for source in thread.latest_draft.kb_sources
                    ],
                )
                if thread.latest_draft
                else None
            ),
            override=(
                ThreadOverrideResponse(
                    category=thread.override.category.value if thread.override.category else None,
                    urgency=thread.override.urgency.value if thread.override.urgency else None,
                    needs_action_today=thread.override.needs_action_today,
                    waiting_on_us=thread.override.waiting_on_us,
                    needs_next_action=thread.override.needs_next_action,
                    should_draft_reply=thread.override.should_draft_reply,
                    relevance_bucket=thread.override.relevance_bucket.value if thread.override.relevance_bucket else None,
                    notes=thread.override.notes,
                    overridden_at=thread.override.overridden_at,
                    updated_at=thread.override.updated_at,
                )
                if thread.override
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
