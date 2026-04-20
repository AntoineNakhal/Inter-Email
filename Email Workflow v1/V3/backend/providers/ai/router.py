"""Task-level provider router with safe fallbacks."""

from __future__ import annotations

from backend.core.config import AppSettings
from backend.providers.ai.base import AIProvider


class AIProviderRouter:
    """Resolves which provider should handle each task."""

    def __init__(self, settings: AppSettings, registry: dict[str, AIProvider]) -> None:
        self.settings = settings
        self.registry = registry

    def provider_for_task(self, task: str) -> AIProvider:
        configured_name = self.settings.provider_for_task(task)
        return self.registry.get(
            configured_name,
            self.registry.get(
                self.settings.ai_default_provider,
                self.registry["heuristic"],
            ),
        )

    def fallback_provider(self) -> AIProvider:
        return self.registry["heuristic"]
