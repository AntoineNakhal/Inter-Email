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
    # Display name pulled from Gmail sendAs (e.g. "Antoine Nakhal").
    # Used to sign drafts correctly — never inferred from the email address.
    gmail_mailbox_name: str = ""
    # Gmail history cursor (users.history.list startHistoryId).
    # Empty string means "no history yet — do a full bootstrap fetch".
    # Reset to "" when the account is disconnected or switched.
    gmail_history_id: str = ""
    # Active Pub/Sub watch. Empty resource_id means no watch is registered.
    gmail_watch_resource_id: str = ""
    gmail_watch_expiry: datetime | None = None
    # 0 means unlimited. When > 0 and local/claude AI mode is active, only the
    # top N threads by relevance score are sent to AI — the rest get heuristic.
    local_ai_max_threads: int = 50
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
