"""Runtime-configurable product settings stored in the app database."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class AIMode(str, Enum):
    OPENAI = "openai"
    LOCAL = "local"


class RuntimeSettings(BaseModel):
    ai_mode: AIMode = AIMode.OPENAI
    local_ai_force_all_threads: bool = False
    local_ai_model: str = ""
    local_ai_agent_prompt: str = ""
    updated_at: datetime | None = None

    @property
    def local_ai_enabled(self) -> bool:
        return self.ai_mode == AIMode.LOCAL
