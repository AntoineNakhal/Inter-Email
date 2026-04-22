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
    ) -> RuntimeSettings:
        return self.repository.update(
            ai_mode=ai_mode,
            local_ai_force_all_threads=local_ai_force_all_threads,
            local_ai_model=local_ai_model,
            local_ai_agent_prompt=local_ai_agent_prompt,
        )
