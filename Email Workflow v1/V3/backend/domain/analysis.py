"""AI task request and response models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from backend.domain.thread import EmailThread, ThreadAnalysis, UrgencyLevel


class ThreadAnalysisRequest(BaseModel):
    thread: EmailThread
    # The connected mailbox owner. When set, providers prepend a
    # "you are analyzing on behalf of {user_email}" perspective block to
    # their prompts so the AI knows when the user is the SENDER vs the
    # RECIPIENT, and frames next_action/summary from the user's POV.
    user_email: str | None = None


class QueueSummaryRequest(BaseModel):
    threads: list[EmailThread]
    user_email: str | None = None


class CRMExtractionRequest(BaseModel):
    thread: EmailThread
    user_email: str | None = None


class DraftReplyRequest(BaseModel):
    thread: EmailThread
    selected_date: str | None = None
    attachment_names: list[str] = Field(default_factory=list)
    user_instructions: str = ""
    user_email: str | None = None


class ThreadVerificationRequest(BaseModel):
    thread: EmailThread
    analysis: ThreadAnalysis
    user_email: str | None = None


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


class ThreadVerificationResult(BaseModel):
    accuracy_percent: int = 0
    verification_summary: str = ""
    needs_human_review: bool = False
    review_reason: str | None = None
    provider_name: str = "heuristic"
    model_name: str = "deterministic-fallback"
    used_fallback: bool = False
    verified_at: datetime | None = None
