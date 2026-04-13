"""Pydantic models shared across the project."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field


TriageCategory = Literal[
    "Urgent / Executive",
    "Customer / Partner",
    "Events / Logistics",
    "Finance / Admin",
    "FYI / Low Priority",
]

UrgencyLevel = Literal["high", "medium", "low", "unknown"]
RelevanceBucket = Literal["must_review", "important", "maybe", "noise"]
ChangeStatus = Literal["new", "changed", "unchanged"]
AnalysisStatus = Literal["fresh", "cached", "not_requested", "skipped", "failed"]


class EmailMessage(BaseModel):
    """Normalized Gmail message shape before messages are grouped into threads."""

    id: str
    thread_id: str
    subject: str
    from_address: str
    to_address: str
    date: str
    snippet: str
    body_text: str = ""
    label_ids: list[str] = Field(default_factory=list)


class ThreadMessage(BaseModel):
    """Child message shown inside one grouped Gmail thread."""

    message_id: str
    sender: str
    subject: str
    date: str
    snippet: str
    cleaned_body: str = ""


class AgentThreadMessage(BaseModel):
    """Compact child message payload sent to the AI agents."""

    message_id: str
    sender: str
    subject: str
    date: str
    snippet: str
    cleaned_body: str


class AgentThread(BaseModel):
    """Sanitized thread payload sent to the OpenAI agent steps."""

    thread_id: str
    subject: str
    participants: list[str] = Field(default_factory=list)
    message_count: int
    latest_message_date: str
    messages: list[AgentThreadMessage] = Field(default_factory=list)
    combined_thread_text: str
    relevance_score: int = Field(ge=1, le=5)


class ThreadTriageItem(BaseModel):
    """Thread-level triage decision returned by the triage agent."""

    thread_id: str
    category: TriageCategory
    summary: str = Field(validation_alias=AliasChoices("summary", "reason"))
    current_status: str = Field(
        validation_alias=AliasChoices("current_status", "status")
    )
    urgency: UrgencyLevel = "unknown"
    needs_action_today: bool = Field(
        validation_alias=AliasChoices("needs_action_today", "action_needed_today")
    )


class ThreadTriageBatch(BaseModel):
    """Structured batch wrapper for thread triage outputs."""

    items: list[ThreadTriageItem]


class SummaryOutput(BaseModel):
    """High-level summary across the selected threads."""

    top_priorities: list[str] = Field(default_factory=list)
    executive_summary: str
    next_actions: list[str] = Field(default_factory=list)


class ThreadCrmRecord(BaseModel):
    """CRM-ready fields extracted from the current thread state."""

    thread_id: str
    contact_name: str | None = None
    company: str | None = None
    opportunity_type: str | None = None
    next_action: str | None = None
    urgency: UrgencyLevel = "unknown"


class ThreadCrmBatch(BaseModel):
    """Structured batch wrapper for CRM extraction outputs."""

    records: list[ThreadCrmRecord]


class PipelineError(BaseModel):
    """Structured error details for any workflow step that needed a fallback."""

    step: Literal["triage", "summary", "crm"]
    message: str
    used_fallback: bool = True


class EmailThread(BaseModel):
    """Main V2 record. One object represents one Gmail thread."""

    thread_id: str
    source_thread_ids: list[str] = Field(default_factory=list)
    grouping_reason: str = "gmail_thread_id"
    subject: str
    participants: list[str] = Field(default_factory=list)
    message_count: int
    latest_message_date: str
    messages: list[ThreadMessage] = Field(default_factory=list)
    combined_thread_text: str = ""
    latest_message_from_me: bool = False
    latest_message_from_external: bool = False
    latest_message_has_question: bool = False
    latest_message_has_action_request: bool = False
    waiting_on_us: bool = False
    resolved_or_closed: bool = False
    predicted_category: TriageCategory | None = None
    predicted_urgency: UrgencyLevel | None = None
    predicted_summary: str | None = None
    predicted_status: str | None = None
    predicted_needs_action_today: bool | None = None
    predicted_next_action: str | None = None
    crm_contact_name: str | None = None
    crm_company: str | None = None
    crm_opportunity_type: str | None = None
    crm_urgency: UrgencyLevel | None = None
    thread_signature: str = ""
    relevance_bucket: RelevanceBucket | None = None
    change_status: ChangeStatus | None = None
    analysis_status: AnalysisStatus | None = None
    last_analysis_at: str | None = None
    relevance_score: int | None = Field(default=None, ge=1, le=5)
    included_in_ai: bool = False
    selection_reason: str = ""


class FinalRunOutput(BaseModel):
    """Complete thread-based output written by the backend pipeline."""

    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    thread_count: int
    message_count: int
    ai_thread_count: int = 0
    fresh_ai_thread_count: int = 0
    cached_ai_thread_count: int = 0
    filtered_thread_count: int = 0
    new_thread_count: int = 0
    changed_thread_count: int = 0
    threads: list[EmailThread]
    summary: SummaryOutput
    errors: list[PipelineError] = Field(default_factory=list)
