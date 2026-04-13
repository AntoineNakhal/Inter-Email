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


class EmailMessage(BaseModel):
    """Normalized email shape used across the pipeline."""

    id: str
    thread_id: str
    subject: str
    from_address: str
    to_address: str
    date: str
    snippet: str
    body_text: str = ""
    label_ids: list[str] = Field(default_factory=list)


class AgentEmail(BaseModel):
    """Small sanitized email payload sent to the OpenAI agent steps."""

    id: str
    subject: str
    sender: str
    snippet: str
    body: str
    relevance_score: int = Field(ge=1, le=5)


class EmailBatch(BaseModel):
    """Wrapper model because structured outputs are easier with named objects."""

    emails: list[EmailMessage]


class TriageItem(BaseModel):
    message_id: str
    category: TriageCategory
    summary: str = Field(validation_alias=AliasChoices("summary", "reason"))
    urgency: UrgencyLevel = "unknown"
    needs_action_today: bool = Field(
        validation_alias=AliasChoices("needs_action_today", "action_needed_today")
    )


class TriageBatch(BaseModel):
    items: list[TriageItem]


class SummaryOutput(BaseModel):
    top_priorities: list[str] = Field(default_factory=list)
    executive_summary: str
    next_actions: list[str] = Field(default_factory=list)


class CrmRecord(BaseModel):
    message_id: str
    contact_name: str | None = None
    company: str | None = None
    opportunity_type: str | None = None
    next_action: str | None = None
    urgency: UrgencyLevel = "unknown"


class CrmBatch(BaseModel):
    records: list[CrmRecord]


class PipelineError(BaseModel):
    """Structured error details for any workflow step that needed a fallback."""

    step: Literal["triage", "summary", "crm"]
    message: str
    used_fallback: bool = True


class EmailSelection(BaseModel):
    """Audit trail for why an email was or was not sent to AI."""

    message_id: str
    subject: str
    sender: str
    relevance_score: int = Field(ge=1, le=5)
    included_in_ai: bool
    reason: str


class FinalRunOutput(BaseModel):
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    email_count: int
    ai_email_count: int = 0
    filtered_email_count: int = 0
    emails: list[EmailMessage]
    triage: list[TriageItem]
    summary: SummaryOutput
    crm_records: list[CrmRecord]
    email_selection: list[EmailSelection] = Field(default_factory=list)
    errors: list[PipelineError] = Field(default_factory=list)
