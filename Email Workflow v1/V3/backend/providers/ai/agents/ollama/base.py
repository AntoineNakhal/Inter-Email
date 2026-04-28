"""Shared prompt scaffolding for task-specific Ollama agents."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod

from backend.domain.runtime_settings import RuntimeSettings


class BaseOllamaAgent(ABC):
    """Common prompt builder for a task-specific local Ollama agent."""

    task_name: str = ""
    agent_name: str = ""
    task_frame: str = ""

    def __init__(self, runtime_settings: RuntimeSettings) -> None:
        self.runtime_settings = runtime_settings

    def compose_prompt(
        self,
        body: dict[str, object],
        user_email: str | None = None,
    ) -> str:
        # The user-perspective block tells the model whose inbox this is so
        # it can distinguish "user sent this" from "user received this" in
        # the thread. Skipped when no Gmail account is connected.
        prompt_parts = [
            self.identity(),
            self.user_perspective_block(user_email),
            self.task_frame,
            self.instructions(),
        ]
        custom_prompt = self.runtime_settings.local_ai_agent_prompt.strip()
        if custom_prompt:
            prompt_parts.extend(
                [
                    "",
                    "Shared local agent instructions:",
                    custom_prompt,
                ]
            )
        prompt_parts.extend(
            [
                "",
                "Input JSON:",
                json.dumps(body, ensure_ascii=False),
            ]
        )
        return "\n".join(part for part in prompt_parts if part)

    @staticmethod
    def user_perspective_block(user_email: str | None) -> str:
        if not user_email:
            return ""
        return (
            f"PERSPECTIVE: You analyze on behalf of {user_email} (the inbox owner). "
            f"Treat that address as 'the user'. When a message's From header is {user_email}, "
            "the user SENT that message — never tell them to reply to themselves. "
            f"When {user_email} is in To/Cc/Bcc, the user RECEIVED that message. "
            "Frame summary, current_status, and next_action from the user's point of view."
        )

    def identity(self) -> str:
        return (
            f"You are Inter-Op's {self.agent_name}. "
            "You are part of a local multi-agent email workflow running on Ollama. "
            "Stay practical, deterministic, and concise. Return only valid JSON."
        )

    @abstractmethod
    def instructions(self) -> str:
        """Return the strict task instructions for this local agent."""
