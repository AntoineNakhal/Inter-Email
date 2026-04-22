"""Settings API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from backend.domain.runtime_settings import AIMode

class SettingsSummaryResponse(BaseModel):
    environment: str
    database_url: str
    ai_default_provider: str
    thread_analysis_provider: str
    queue_summary_provider: str
    draft_provider: str
    crm_provider: str
    ai_mode: str
    local_ai_force_all_threads: bool
    local_ai_model: str
    local_ai_agent_prompt: str
    ollama_base_url: str
    ollama_model_thread_analysis: str
    runtime_settings_updated_at: datetime | None = None


class RuntimeSettingsUpdateRequest(BaseModel):
    ai_mode: AIMode
    local_ai_force_all_threads: bool = False
    local_ai_model: str = ""
    local_ai_agent_prompt: str = ""
