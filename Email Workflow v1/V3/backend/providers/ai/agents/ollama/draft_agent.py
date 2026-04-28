"""Local Ollama agent for drafting replies."""

from __future__ import annotations

from backend.providers.ai.agents.ollama.base import BaseOllamaAgent


class LocalDraftAgent(BaseOllamaAgent):
    """Builds a reply draft grounded in the analyzed email thread."""

    task_name = "draft_reply"
    agent_name = "LocalDraftAgent"
    task_frame = "Task: draft a reply based on the analyzed email thread."

    def instructions(self) -> str:
        return (
            "Return strict JSON with keys: subject, body. "
            "Do not restate the sender's email, signature, or confidentiality footer. "
            "Acknowledge briefly, answer the real ask, and keep the reply concise. "
            "If user_instructions are provided, treat them as highest-priority drafting requirements "
            "and visibly change the draft to match them. "
            "If selected_date or attachment_names are provided, incorporate them when relevant."
        )
