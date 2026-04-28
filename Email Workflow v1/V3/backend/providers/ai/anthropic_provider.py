"""Anthropic / Claude implementation of the provider interface.

Design note (intentional inheritance):
    The task prompts, payload-building, and JSON normalization in
    `OpenAIProvider` are provider-agnostic — they only operate on our
    domain types (EmailThread, ThreadAnalysisRequest, ...) and on plain
    dicts coming back from the model. The single OpenAI-specific piece
    is `_chat_json`, which talks to the OpenAI SDK.

    Rather than duplicate ~300 lines of helpers, AnthropicProvider
    subclasses OpenAIProvider and overrides only:
        - `name`           — registry key + provenance tag on saved analysis
        - `_chat_json`     — calls Anthropic's Messages API instead of OpenAI

    All five task methods (analyze_thread, summarize_queue, draft_reply,
    extract_crm, verify_thread_analysis) inherit unchanged. They call
    `self._chat_json(...)` which, thanks to Python's MRO, dispatches to
    the override below when self is an AnthropicProvider.

    If the prompts ever need to diverge (e.g., Claude responds better to
    a different system prompt phrasing), copy that single method down
    into this class — the override is contained.
"""

from __future__ import annotations

import json

from backend.core.config import AppSettings
from backend.providers.ai.base import AIProviderError
from backend.providers.ai.openai_provider import OpenAIProvider


class AnthropicProvider(OpenAIProvider):
    """Claude-backed provider implementation.

    Registry key / provider name: ``anthropic``.
    User-facing AI mode that selects this provider: ``claude``.
    """

    name = "anthropic"

    def __init__(self, settings: AppSettings) -> None:
        # Skip OpenAIProvider.__init__ work other than storing settings.
        # Anthropic doesn't need an OpenAI client, but we DO need the
        # same `self.settings` so all inherited helpers keep working.
        self.settings = settings

    # Tight per-task output budgets — our JSON responses are small.
    # draft_reply needs more headroom since it generates prose.
    _MAX_TOKENS_BY_TASK: dict[str, int] = {
        "thread_analysis": 512,
        "thread_verification": 256,
        "queue_summary": 1024,
        "crm_extraction": 256,
        "draft_reply": 1024,
    }
    _MAX_TOKENS_DEFAULT = 512

    def _chat_json(
        self,
        task: str,
        system_prompt: str,
        user_payload: dict[str, object],
    ) -> dict[str, object]:
        if not self.settings.anthropic_api_key.strip():
            raise AIProviderError("ANTHROPIC_API_KEY is missing.")

        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise AIProviderError(
                "The `anthropic` package is not installed. Run `pip install -e .` "
                "or add `anthropic>=0.40.0` to your environment."
            ) from exc

        try:
            client = Anthropic(api_key=self.settings.anthropic_api_key)
            max_tokens = self._MAX_TOKENS_BY_TASK.get(task, self._MAX_TOKENS_DEFAULT)
            # Claude's Messages API takes `system` separately and a list of
            # user/assistant messages. We send the structured input as a
            # single user message containing JSON, mirroring how the OpenAI
            # path passes the payload. The system prompt already instructs
            # "Return strict JSON" — Claude is reliable at that.
            response = client.messages.create(
                model=self.settings.model_for_provider_task(self.name, task),
                max_tokens=max_tokens,
                temperature=0.2,
                system=system_prompt,
                messages=[
                    {
                        "role": "user",
                        "content": json.dumps(user_payload, ensure_ascii=False),
                    },
                ],
            )
            content = self._extract_text(response)
            return self._parse_json_payload(content)
        except AIProviderError:
            raise
        except Exception as exc:  # pragma: no cover
            raise AIProviderError(f"Anthropic request failed: {exc}") from exc

    @staticmethod
    def _extract_text(response: object) -> str:
        """
        Pull plain text out of an Anthropic Messages response.

        The SDK returns a list of content blocks. For our use case we only
        care about TextBlock entries — we concatenate their `.text` fields.
        Defensive: if the shape changes in a future SDK version, we fall
        back to str(response) so JSON parsing has a chance.
        """
        try:
            content_blocks = getattr(response, "content", None) or []
            texts: list[str] = []
            for block in content_blocks:
                # Each block may be a TextBlock (has .text) or a dict.
                text = getattr(block, "text", None)
                if text is None and isinstance(block, dict):
                    text = block.get("text")
                if isinstance(text, str):
                    texts.append(text)
            joined = "".join(texts).strip()
            return joined or "{}"
        except Exception:  # pragma: no cover
            return "{}"

    @staticmethod
    def _parse_json_payload(content: str) -> dict[str, object]:
        """
        Parse a JSON object from the model's response.

        Claude is reliable about returning bare JSON when instructed, but
        occasionally wraps it in ```json fences. We trim those defensively
        before json.loads to avoid spurious provider errors that would
        push us to the heuristic fallback.
        """
        text = content.strip()
        if text.startswith("```"):
            # Drop the first fence line (```json or ```) and the trailing fence.
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            parsed = json.loads(text or "{}")
        except json.JSONDecodeError as exc:
            raise AIProviderError(
                f"Anthropic returned non-JSON content: {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise AIProviderError(
                "Anthropic returned a non-object JSON payload."
            )
        return parsed
