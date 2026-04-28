"""Runtime-configurable product settings stored in the app database."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class AIMode(str, Enum):
    OPENAI = "openai"
    LOCAL = "local"
    # User-facing brand name for the Anthropic provider. Routes everything
    # to registry["anthropic"] when selected.
    CLAUDE = "claude"


class RuntimeSettings(BaseModel):
    ai_mode: AIMode = AIMode.OPENAI
    local_ai_force_all_threads: bool = False
    local_ai_model: str = ""
    local_ai_agent_prompt: str = ""
    gmail_mailbox_email: str = ""
    updated_at: datetime | None = None

    @property
    def local_ai_enabled(self) -> bool:
        return self.ai_mode == AIMode.LOCAL

    @property
    def claude_enabled(self) -> bool:
        return self.ai_mode == AIMode.CLAUDE

    @property
    def local_ai_analyzes_all_fetched_threads(self) -> bool:
        return self.local_ai_enabled or self.local_ai_force_all_threads
