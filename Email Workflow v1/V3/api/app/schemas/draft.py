"""Draft API schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

from api.app.schemas.thread import DraftResponse
from backend.domain.thread import DraftDocument


class DraftGenerateRequest(BaseModel):
    selected_date: str | None = None
    attachment_names: list[str] = Field(default_factory=list)
    user_instructions: str = ""


class DraftGenerateResponse(DraftResponse):
    @classmethod
    def from_domain(cls, draft: DraftDocument) -> "DraftGenerateResponse":
        return cls(**draft.model_dump())
