"""Local Ollama agent for inbox-wide queue summaries."""

from __future__ import annotations

from backend.providers.ai.agents.ollama.base import BaseOllamaAgent


class LocalQueueAgent(BaseOllamaAgent):
    """Summarizes the analyzed queue into top priorities and next actions."""

    task_name = "queue_summary"
    agent_name = "LocalQueueAgent"
    task_frame = (
        "Task: summarize the full analyzed inbox queue into priorities and next actions."
    )

    def instructions(self) -> str:
        return (
            "Summarize the analyzed inbox for an operator."
            "Seen emails should not be included in the summary."
            "Focus on emails that need action today, emails waiting on the operator, unresolved emails, and urgent emails."
            "Return strict JSON with keys: top_priorities, executive_summary, next_actions."
        )
