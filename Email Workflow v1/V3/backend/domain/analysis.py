"""AI task request and response models."""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.domain.thread import EmailThread, UrgencyLevel


class ThreadAnalysisRequest(BaseModel):
    thread: EmailThread


class QueueSummaryRequest(BaseModel):
    threads: list[EmailThread]


class CRMExtractionRequest(BaseModel):
    thread: EmailThread


class DraftReplyRequest(BaseModel):
    thread: EmailThread
    selected_date: str | None = None
    attachment_names: list[str] = Field(default_factory=list)
    user_instructions: str = ""


class QueueSummaryResult(BaseModel):
    top_priorities: list[str] = Field(default_factory=list)
    executive_summary: str = ""
    next_actions: list[str] = Field(default_factory=list)
    provider_name: str = "heuristic"
    model_name: str = "deterministic-fallback"
    used_fallback: bool = False


class CRMExtractionResult(BaseModel):
    contact_name: str | None = None
    company: str | None = None
    opportunity_type: str | None = None
    next_action: str | None = None
    urgency: UrgencyLevel = UrgencyLevel.UNKNOWN
    provider_name: str = "heuristic"
    model_name: str = "deterministic-fallback"
    used_fallback: bool = False
