"""Provider registry factory."""

from __future__ import annotations

from backend.core.config import AppSettings
from backend.providers.ai.base import AIProvider
from backend.providers.ai.heuristic_provider import HeuristicAIProvider
from backend.providers.ai.ollama_provider import OllamaProvider
from backend.providers.ai.openai_provider import OpenAIProvider


def build_provider_registry(settings: AppSettings) -> dict[str, AIProvider]:
    """Instantiate the provider adapters available in this runtime."""

    return {
        "heuristic": HeuristicAIProvider(),
        "openai": OpenAIProvider(settings),
        "ollama": OllamaProvider(settings),
    }
