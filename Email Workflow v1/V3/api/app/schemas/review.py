"""Review API schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.domain.thread import ReviewDecision


class ReviewRequest(BaseModel):
    queue_belongs: str = "not_sure"
    merge_correct: str = "not_sure"
    summary_useful: str = "partially"
    next_action_useful: str = "partially"
    draft_useful: str = "partially"
    crm_useful: str = "not_applicable"
    notes: str = ""
    improvement_tags: list[str] = Field(default_factory=list)

    def to_domain(self) -> ReviewDecision:
        return ReviewDecision(**self.model_dump())


class SeenStateRequest(BaseModel):
    seen: bool = True
