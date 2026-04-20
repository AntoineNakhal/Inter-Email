"""Ollama implementation to support local AI later without backend rewrites."""

from __future__ import annotations

import json
from urllib import request as urllib_request

from backend.core.config import AppSettings
from backend.domain.analysis import (
    CRMExtractionRequest,
    CRMExtractionResult,
    DraftReplyRequest,
    QueueSummaryRequest,
    QueueSummaryResult,
    ThreadAnalysisRequest,
)
from backend.domain.thread import DraftDocument, ThreadAnalysis
from backend.providers.ai.base import AIProvider, AIProviderError


class OllamaProvider(AIProvider):
    """Local/self-hosted provider implementation using Ollama's HTTP API."""

    name = "ollama"

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def analyze_thread(self, request: ThreadAnalysisRequest) -> ThreadAnalysis:
        payload = self._generate_json(
            task="thread_analysis",
            instructions=(
                "Return JSON with keys: category, urgency, summary, current_status, "
                "next_action, needs_action_today, should_draft_reply, "
                "draft_needs_date, draft_date_reason, draft_needs_attachment, "
                "draft_attachment_reason."
            ),
            body=request.model_dump(mode="json"),
        )
        return ThreadAnalysis.model_validate(
            {
                **payload,
                "provider_name": self.name,
                "model_name": self.settings.model_for_provider_task(
                    self.name,
                    "thread_analysis",
                ),
                "used_fallback": False,
            }
        )

    def summarize_queue(self, request: QueueSummaryRequest) -> QueueSummaryResult:
        payload = self._generate_json(
            task="queue_summary",
            instructions="Return JSON with keys: top_priorities, executive_summary, next_actions.",
            body=request.model_dump(mode="json"),
        )
        return QueueSummaryResult.model_validate(
            {
                **payload,
                "provider_name": self.name,
                "model_name": self.settings.model_for_provider_task(
                    self.name,
                    "queue_summary",
                ),
                "used_fallback": False,
            }
        )

    def draft_reply(self, request: DraftReplyRequest) -> DraftDocument:
        payload = self._generate_json(
            task="draft_reply",
            instructions="Return JSON with keys: subject, body.",
            body=request.model_dump(mode="json"),
        )
        return DraftDocument.model_validate(
            {
                **payload,
                "provider_name": self.name,
                "model_name": self.settings.model_for_provider_task(
                    self.name,
                    "draft_reply",
                ),
                "used_fallback": False,
            }
        )

    def extract_crm(self, request: CRMExtractionRequest) -> CRMExtractionResult:
        payload = self._generate_json(
            task="crm_extraction",
            instructions=(
                "Return JSON with keys: contact_name, company, opportunity_type, "
                "next_action, urgency."
            ),
            body=request.model_dump(mode="json"),
        )
        return CRMExtractionResult.model_validate(
            {
                **payload,
                "provider_name": self.name,
                "model_name": self.settings.model_for_provider_task(
                    self.name,
                    "crm_extraction",
                ),
                "used_fallback": False,
            }
        )

    def _generate_json(
        self,
        task: str,
        instructions: str,
        body: dict[str, object],
    ) -> dict[str, object]:
        model_name = self.settings.model_for_provider_task(self.name, task)
        if not model_name.strip():
            raise AIProviderError(f"No Ollama model configured for task `{task}`.")

        prompt = (
            "You are an email workflow AI assistant.\n"
            f"{instructions}\n\n"
            "Input JSON:\n"
            f"{json.dumps(body, ensure_ascii=False)}"
        )
        request_body = json.dumps(
            {
                "model": model_name,
                "prompt": prompt,
                "format": "json",
                "stream": False,
            }
        ).encode("utf-8")

        endpoint = f"{self.settings.ollama_base_url.rstrip('/')}/api/generate"
        http_request = urllib_request.Request(
            endpoint,
            data=request_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib_request.urlopen(http_request, timeout=120) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return json.loads(payload.get("response", "{}"))
        except Exception as exc:  # pragma: no cover
            raise AIProviderError(f"Ollama request failed: {exc}") from exc
