"""Task-level provider router with safe fallbacks."""

from __future__ import annotations

from backend.core.config import AppSettings
from backend.domain.runtime_settings import RuntimeSettings
from backend.providers.ai.base import AIProvider


class AIProviderRouter:
    """Resolves which provider should handle each task."""

    def __init__(
        self,
        settings: AppSettings,
        registry: dict[str, AIProvider],
        runtime_settings: RuntimeSettings,
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.runtime_settings = runtime_settings

    def provider_for_task(self, task: str) -> AIProvider:
        # Mode toggles short-circuit per-task config: when the user picks
        # "local" or "claude" as their AI mode, every task is routed to
        # that single provider. This mirrors the existing local-mode
        # behavior — a one-flag global switch.
        if self.runtime_settings.local_ai_enabled:
            return self.registry.get("ollama", self.registry["heuristic"])
        if self.runtime_settings.claude_enabled:
            return self.registry.get("anthropic", self.registry["heuristic"])

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
