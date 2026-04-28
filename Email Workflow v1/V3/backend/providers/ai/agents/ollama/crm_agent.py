"""Local Ollama agent for CRM-ready extraction."""

from __future__ import annotations

from backend.domain.thread import UrgencyLevel
from backend.providers.ai.agents.ollama.base import BaseOllamaAgent


class LocalCRMAgent(BaseOllamaAgent):
    """Extracts structured CRM-ready fields from analyzed threads."""

    task_name = "crm_extraction"
    agent_name = "LocalCRMAgent"
    task_frame = (
        "Task: extract CRM-ready structured fields from the analyzed email thread."
    )

    def instructions(self) -> str:
        return (
            "Extract CRM-ready details from the email thread. "
            "Use only these urgency values: "
            f"{', '.join(level.value for level in UrgencyLevel)}. "
            "Return strict JSON with keys: contact_name, company, opportunity_type, "
            "next_action, urgency."
        )
