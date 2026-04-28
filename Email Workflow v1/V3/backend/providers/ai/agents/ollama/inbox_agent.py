"""Local Ollama agent for per-thread inbox analysis."""

from __future__ import annotations

from backend.domain.thread import TriageCategory, UrgencyLevel
from backend.providers.ai.agents.ollama.base import BaseOllamaAgent


class LocalInboxAgent(BaseOllamaAgent):
    """Analyzes every fetched email thread in local AI mode."""

    task_name = "thread_analysis"
    agent_name = "LocalInboxAgent"
    task_frame = (
        "Task: analyze one fetched email thread and produce a queue-ready assessment."
    )

    def identity(self) -> str:
        return (
            "You are Inter-Op's LocalInboxAgent. "
            "When local mode is active, every fetched email thread passes through you, "
            "including routine, noisy, and low-priority threads. "
            "You never skip analysis because of triage heuristics. "
            "Return only valid JSON."
        )

    def instructions(self) -> str:
        return (
            "Analyze the fetched email thread directly. "
            "Ignore email signatures, confidentiality notices, and quoted reply history. "
            "Anchor your analysis on the latest meaningful message and only use older messages as supporting context. "
            "If the email is very short, keep the summary shorter than the email itself. "
            "Make the next_action specific to the latest message and avoid generic actions "
            "like 'prepare and send a reply today'. "
            "Make the current_status exact and concrete, not vague. "
            "Use only these category values: "
            f"{', '.join(category.value for category in TriageCategory)}. "
            "Use only these urgency values: "
            f"{', '.join(level.value for level in UrgencyLevel)}. "
            "Return strict JSON with keys: category, urgency, summary, current_status, "
            "next_action, needs_action_today, should_draft_reply, draft_needs_date, "
            "draft_date_reason, draft_needs_attachment, draft_attachment_reason."
        )
