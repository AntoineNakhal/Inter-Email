"""Task-specific local Ollama agents."""

from backend.providers.ai.agents.ollama.crm_agent import LocalCRMAgent
from backend.providers.ai.agents.ollama.draft_agent import LocalDraftAgent
from backend.providers.ai.agents.ollama.inbox_agent import LocalInboxAgent
from backend.providers.ai.agents.ollama.queue_agent import LocalQueueAgent
from backend.providers.ai.agents.ollama.verification_agent import LocalVerificationAgent

__all__ = [
    "LocalInboxAgent",
    "LocalQueueAgent",
    "LocalDraftAgent",
    "LocalCRMAgent",
    "LocalVerificationAgent",
]
