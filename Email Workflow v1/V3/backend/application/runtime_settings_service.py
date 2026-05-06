"""Application service for mutable runtime settings."""

from __future__ import annotations

from backend.domain.runtime_settings import RuntimeSettings
from backend.persistence.repositories.runtime_settings_repository import (
    RuntimeSettingsRepository,
)


class RuntimeSettingsService:
    """Owns the runtime AI mode and local-agent preferences."""

    def __init__(self, repository: RuntimeSettingsRepository) -> None:
        self.repository = repository

    def get(self) -> RuntimeSettings:
        return self.repository.get()

    def update(
        self,
        *,
        ai_mode: str,
        local_ai_force_all_threads: bool,
        local_ai_model: str,
        local_ai_agent_prompt: str,
        local_ai_max_threads: int = 50,
    ) -> RuntimeSettings:
        return self.repository.update(
            ai_mode=ai_mode,
            local_ai_force_all_threads=local_ai_force_all_threads,
            local_ai_model=local_ai_model,
            local_ai_agent_prompt=local_ai_agent_prompt,
            local_ai_max_threads=local_ai_max_threads,
        )

    def set_gmail_mailbox_email(self, gmail_mailbox_email: str) -> RuntimeSettings:
        return self.repository.update_gmail_mailbox_email(gmail_mailbox_email)

    def set_gmail_mailbox_name(self, gmail_mailbox_name: str) -> RuntimeSettings:
        return self.repository.update_gmail_mailbox_name(gmail_mailbox_name)

    def update_gmail_history_id(self, gmail_history_id: str) -> RuntimeSettings:
        return self.repository.update_gmail_history_id(gmail_history_id)

    def update_gmail_watch(
        self,
        resource_id: str,
        expiry: "datetime | None",
    ) -> RuntimeSettings:
        from datetime import datetime  # local import avoids circular at module level
        return self.repository.update_gmail_watch(resource_id, expiry)

    def clear_gmail_watch(self) -> RuntimeSettings:
        return self.repository.update_gmail_watch("", None)
