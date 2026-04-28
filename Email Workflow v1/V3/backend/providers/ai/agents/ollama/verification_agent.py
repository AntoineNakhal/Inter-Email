"""Local Ollama agent for verifying thread-analysis quality."""

from __future__ import annotations

from backend.providers.ai.agents.ollama.base import BaseOllamaAgent


class LocalVerificationAgent(BaseOllamaAgent):
    """Scores and reviews the output of the inbox analysis agent."""

    task_name = "thread_verification"
    agent_name = "LocalVerificationAgent"
    task_frame = (
        "Task: verify whether the proposed email-thread analysis is accurate and actionable."
    )

    def instructions(self) -> str:
        return (
            "Review the original thread together with the proposed analysis output. "
            "Do not rewrite the analysis itself. "
            "Return strict JSON with keys: accuracy_percent, verification_summary, "
            "needs_human_review, review_reason."
        )
