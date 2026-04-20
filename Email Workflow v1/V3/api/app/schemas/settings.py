"""Settings API schemas."""

from __future__ import annotations

from pydantic import BaseModel


class SettingsSummaryResponse(BaseModel):
    environment: str
    database_url: str
    ai_default_provider: str
    thread_analysis_provider: str
    queue_summary_provider: str
    draft_provider: str
    crm_provider: str
