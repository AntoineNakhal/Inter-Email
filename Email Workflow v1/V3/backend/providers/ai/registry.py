"""Provider registry factory."""

from __future__ import annotations

from backend.core.config import AppSettings
from backend.domain.runtime_settings import RuntimeSettings
from backend.providers.ai.anthropic_provider import AnthropicProvider
from backend.providers.ai.base import AIProvider
from backend.providers.ai.heuristic_provider import HeuristicAIProvider
from backend.providers.ai.ollama_provider import OllamaProvider
from backend.providers.ai.openai_provider import OpenAIProvider


def build_provider_registry(
    settings: AppSettings,
    runtime_settings: RuntimeSettings,
) -> dict[str, AIProvider]:
    """Instantiate the provider adapters available in this runtime."""

    return {
        "heuristic": HeuristicAIProvider(),
        "openai": OpenAIProvider(settings),
        "ollama": OllamaProvider(settings, runtime_settings),
        # User-facing AI mode "claude" maps to this provider.
        "anthropic": AnthropicProvider(settings),
    }
