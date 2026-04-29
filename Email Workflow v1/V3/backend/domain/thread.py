"""Thread and message domain models."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class TriageCategory(str, Enum):
    URGENT_EXECUTIVE = "Urgent / Executive"
    CUSTOMER_PARTNER = "Customer / Partner"
    EVENTS_LOGISTICS = "Events / Logistics"
    FINANCE_ADMIN = "Finance / Admin"
    FYI_LOW_PRIORITY = "FYI / Low Priority"
    CLASSIFIED_SENSITIVE = "Classified / Sensitive"


class UrgencyLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class RelevanceBucket(str, Enum):
    MUST_REVIEW = "must_review"
    IMPORTANT = "important"
    MAYBE = "maybe"
    NOISE = "noise"


class SecurityStatus(str, Enum):
    STANDARD = "standard"
    CLASSIFIED = "classified"


class AnalysisStatus(str, Enum):
    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"
    GUARDRailed = "guardrailed"
    SKIPPED = "skipped"


class InboundEmailMessage(BaseModel):
    """Normalized Gmail message before grouping."""

    external_message_id: str
    external_thread_id: str
    subject: str
    from_address: str
    to_address: str
    date_header: str
    snippet: str
    body_text: str = ""
    label_ids: list[str] = Field(default_factory=list)


class ThreadMessage(BaseModel):
    """Message record stored under one thread."""

    external_message_id: str
    sender: str
    recipients: list[str] = Field(default_factory=list)
    subject: str
    sent_at: datetime | None = None
    snippet: str = ""
    cleaned_body: str = ""
    label_ids: list[str] = Field(default_factory=list)


class ThreadAnalysis(BaseModel):
    """Current analysis state for one thread."""

    category: TriageCategory = TriageCategory.FYI_LOW_PRIORITY
    urgency: UrgencyLevel = UrgencyLevel.UNKNOWN
    summary: str = ""
    current_status: str = ""
    next_action: str = ""
    needs_action_today: bool = False
    should_draft_reply: bool = False
    draft_needs_date: bool = False
    draft_date_reason: str | None = None
    draft_needs_attachment: bool = False
    draft_attachment_reason: str | None = None
    crm_contact_name: str | None = None
    crm_company: str | None = None
    crm_opportunity_type: str | None = None
    crm_urgency: UrgencyLevel | None = None
    provider_name: str = "heuristic"
    model_name: str = "deterministic-fallback"
    prompt_version: str = "v1"
    used_fallback: bool = False
    accuracy_percent: int = 0
    verification_summary: str = ""
    needs_human_review: bool = False
    review_reason: str | None = None
    verifier_provider_name: str = "heuristic"
    verifier_model_name: str = "deterministic-fallback"
    verifier_used_fallback: bool = False
    analyzed_at: datetime | None = None
    verified_at: datetime | None = None


class SeenState(BaseModel):
    """Seen-state tracking for one thread."""

    seen: bool = False
    seen_version: str = ""
    seen_at: datetime | None = None
    pinned: bool = False


class ReviewDecision(BaseModel):
    """Internal review record for one thread."""

    queue_belongs: str = "not_sure"
    merge_correct: str = "not_sure"
    summary_useful: str = "partially"
    next_action_useful: str = "partially"
    draft_useful: str = "partially"
    crm_useful: str = "not_applicable"
    notes: str = ""
    improvement_tags: list[str] = Field(default_factory=list)
    updated_at: datetime | None = None


class DraftDocument(BaseModel):
    """Draft response linked to one thread."""

    subject: str
    body: str
    provider_name: str = "heuristic"
    model_name: str = "deterministic-fallback"
    used_fallback: bool = False
    created_at: datetime | None = None


class EmailThread(BaseModel):
    """Product-level thread object shared across services."""

    model_config = ConfigDict(from_attributes=True)

    external_thread_id: str
    source_thread_ids: list[str] = Field(default_factory=list)
    grouping_reason: str = "gmail_thread_id"
    merge_signals: list[str] = Field(default_factory=list)
    subject: str
    participants: list[str] = Field(default_factory=list)
    message_count: int = 0
    latest_message_date: datetime | None = None
    messages: list[ThreadMessage] = Field(default_factory=list)
    combined_thread_text: str = ""
    security_status: SecurityStatus = SecurityStatus.STANDARD
    sensitivity_markers: list[str] = Field(default_factory=list)
    latest_message_from_me: bool = False
    latest_message_from_external: bool = False
    latest_message_has_question: bool = False
    latest_message_has_action_request: bool = False
    waiting_on_us: bool = False
    resolved_or_closed: bool = False
    relevance_score: int | None = None
    relevance_bucket: RelevanceBucket | None = None
    included_in_ai: bool = False
    ai_decision: str | None = None
    ai_decision_reason: str | None = None
    analysis_status: AnalysisStatus = AnalysisStatus.PENDING
    signature: str = ""
    is_new: bool = False
    last_synced_at: datetime | None = None
    last_analyzed_at: datetime | None = None
    analysis: ThreadAnalysis | None = None
    seen_state: SeenState | None = None
    review: ReviewDecision | None = None
    latest_draft: DraftDocument | None = None

    def compute_signature(self) -> str:
        """Build a stable content signature for seen-state and updates."""

        payload = {
            "thread_id": self.external_thread_id,
            "subject": self.subject,
            "participants": self.participants,
            "messages": [
                {
                    "id": message.external_message_id,
                    "sender": message.sender,
                    "subject": message.subject,
                    "sent_at": message.sent_at.isoformat() if message.sent_at else None,
                    "snippet": message.snippet,
                    "body": message.cleaned_body,
                }
                for message in self.messages
            ],
        }
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
