"""Ollama implementation to support local AI without backend rewrites."""

from __future__ import annotations

import json
from collections.abc import Iterable
from urllib import request as urllib_request

from pydantic import ValidationError

from backend.core.config import AppSettings
from backend.domain.analysis import (
    CRMExtractionRequest,
    CRMExtractionResult,
    DraftReplyRequest,
    QueueSummaryRequest,
    QueueSummaryResult,
    ThreadAnalysisRequest,
)
from backend.domain.runtime_settings import RuntimeSettings
from backend.domain.thread import (
    DraftDocument,
    ThreadAnalysis,
    TriageCategory,
    UrgencyLevel,
)
from backend.providers.ai.base import AIProvider, AIProviderError


class OllamaProvider(AIProvider):
    """Local/self-hosted provider implementation using Ollama's HTTP API."""

    name = "ollama"

    def __init__(self, settings: AppSettings, runtime_settings: RuntimeSettings) -> None:
        self.settings = settings
        self.runtime_settings = runtime_settings

    def analyze_thread(self, request: ThreadAnalysisRequest) -> ThreadAnalysis:
        payload = self._generate_json(
            task="thread_analysis",
            instructions=(
                "You are analyzing one email thread for an internal operations queue. "
                "Use only these category values: "
                f"{', '.join(category.value for category in TriageCategory)}. "
                "Use only these urgency values: "
                f"{', '.join(level.value for level in UrgencyLevel)}. "
                "Return strict JSON with keys: category, urgency, summary, current_status, "
                "next_action, needs_action_today, should_draft_reply, "
                "draft_needs_date, draft_date_reason, draft_needs_attachment, "
                "draft_attachment_reason."
            ),
            body=self._build_thread_analysis_payload(request),
        )
        normalized_payload = self._normalize_thread_analysis_payload(payload)
        try:
            return ThreadAnalysis.model_validate(
                {
                    **normalized_payload,
                    "provider_name": self.name,
                    "model_name": self._model_for_task("thread_analysis"),
                    "used_fallback": False,
                }
            )
        except ValidationError as exc:
            raise AIProviderError(f"Ollama returned invalid thread analysis: {exc}") from exc

    def summarize_queue(self, request: QueueSummaryRequest) -> QueueSummaryResult:
        payload = self._generate_json(
            task="queue_summary",
            instructions="Return strict JSON with keys: top_priorities, executive_summary, next_actions.",
            body=request.model_dump(mode="json"),
        )
        normalized_payload = self._normalize_queue_summary_payload(payload)
        try:
            return QueueSummaryResult.model_validate(
                {
                    **normalized_payload,
                    "provider_name": self.name,
                    "model_name": self._model_for_task("queue_summary"),
                    "used_fallback": False,
                }
            )
        except ValidationError as exc:
            raise AIProviderError(f"Ollama returned invalid queue summary: {exc}") from exc

    def draft_reply(self, request: DraftReplyRequest) -> DraftDocument:
        payload = self._generate_json(
            task="draft_reply",
            instructions="Return strict JSON with keys: subject, body.",
            body=request.model_dump(mode="json"),
        )
        normalized_payload = self._normalize_draft_payload(payload)
        try:
            return DraftDocument.model_validate(
                {
                    **normalized_payload,
                    "provider_name": self.name,
                    "model_name": self._model_for_task("draft_reply"),
                    "used_fallback": False,
                }
            )
        except ValidationError as exc:
            raise AIProviderError(f"Ollama returned invalid draft output: {exc}") from exc

    def extract_crm(self, request: CRMExtractionRequest) -> CRMExtractionResult:
        payload = self._generate_json(
            task="crm_extraction",
            instructions=(
                "Use only these urgency values: "
                f"{', '.join(level.value for level in UrgencyLevel)}. "
                "Return strict JSON with keys: contact_name, company, opportunity_type, "
                "next_action, urgency."
            ),
            body=self._build_crm_payload(request),
        )
        normalized_payload = self._normalize_crm_payload(payload)
        try:
            return CRMExtractionResult.model_validate(
                {
                    **normalized_payload,
                    "provider_name": self.name,
                    "model_name": self._model_for_task("crm_extraction"),
                    "used_fallback": False,
                }
            )
        except ValidationError as exc:
            raise AIProviderError(f"Ollama returned invalid CRM extraction: {exc}") from exc

    def _generate_json(
        self,
        task: str,
        instructions: str,
        body: dict[str, object],
    ) -> dict[str, object]:
        model_name = self._model_for_task(task)
        if not model_name.strip():
            raise AIProviderError(f"No Ollama model configured for task `{task}`.")

        prompt_parts = [
            "You are an AI email workflow agent for Inter-Op.",
            instructions,
        ]
        if self.runtime_settings.local_ai_agent_prompt.strip():
            prompt_parts.extend(
                [
                    "",
                    "Agent instructions:",
                    self.runtime_settings.local_ai_agent_prompt.strip(),
                ]
            )
        prompt_parts.extend(
            [
                "",
                "Input JSON:",
                json.dumps(body, ensure_ascii=False),
            ]
        )
        prompt = "\n".join(prompt_parts)

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

    def _model_for_task(self, task: str) -> str:
        runtime_model = self.runtime_settings.local_ai_model.strip()
        if runtime_model:
            return runtime_model
        return self.settings.model_for_provider_task(self.name, task)

    def _build_thread_analysis_payload(
        self,
        request: ThreadAnalysisRequest,
    ) -> dict[str, object]:
        thread = request.thread
        return {
            "thread": {
                "thread_id": thread.external_thread_id,
                "subject": thread.subject,
                "participants": thread.participants[:12],
                "message_count": thread.message_count,
                "latest_message_date": (
                    thread.latest_message_date.isoformat()
                    if thread.latest_message_date
                    else None
                ),
                "waiting_on_us": thread.waiting_on_us,
                "resolved_or_closed": thread.resolved_or_closed,
                "latest_message_from_me": thread.latest_message_from_me,
                "latest_message_from_external": thread.latest_message_from_external,
                "latest_message_has_question": thread.latest_message_has_question,
                "latest_message_has_action_request": thread.latest_message_has_action_request,
                "relevance_score": thread.relevance_score,
                "combined_thread_text": thread.combined_thread_text[:6000],
                "messages": [
                    {
                        "sender": message.sender,
                        "subject": message.subject,
                        "sent_at": (
                            message.sent_at.isoformat() if message.sent_at else None
                        ),
                        "snippet": message.snippet[:400],
                        "cleaned_body": message.cleaned_body[:1600],
                    }
                    for message in thread.messages[-5:]
                ],
            }
        }

    def _build_crm_payload(
        self,
        request: CRMExtractionRequest,
    ) -> dict[str, object]:
        thread = request.thread
        analysis = thread.analysis
        return {
            "thread": {
                "thread_id": thread.external_thread_id,
                "subject": thread.subject,
                "participants": thread.participants[:12],
                "message_count": thread.message_count,
                "latest_message_date": (
                    thread.latest_message_date.isoformat()
                    if thread.latest_message_date
                    else None
                ),
                "combined_thread_text": thread.combined_thread_text[:5000],
                "messages": [
                    {
                        "sender": message.sender,
                        "subject": message.subject,
                        "sent_at": (
                            message.sent_at.isoformat() if message.sent_at else None
                        ),
                        "snippet": message.snippet[:300],
                        "cleaned_body": message.cleaned_body[:1200],
                    }
                    for message in thread.messages[-4:]
                ],
                "analysis": {
                    "category": analysis.category.value if analysis else None,
                    "urgency": analysis.urgency.value if analysis else None,
                    "summary": analysis.summary if analysis else None,
                    "next_action": analysis.next_action if analysis else None,
                },
            }
        }

    def _normalize_thread_analysis_payload(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        normalized = dict(payload)
        normalized["category"] = self._normalize_category(normalized.get("category"))
        normalized["urgency"] = self._normalize_urgency(normalized.get("urgency"))
        normalized["summary"] = self._normalize_text(normalized.get("summary"))
        normalized["current_status"] = self._normalize_text(
            normalized.get("current_status")
        )
        normalized["next_action"] = self._normalize_text(normalized.get("next_action"))
        normalized["needs_action_today"] = self._normalize_bool(
            normalized.get("needs_action_today")
        )
        normalized["should_draft_reply"] = self._normalize_bool(
            normalized.get("should_draft_reply")
        )
        normalized["draft_needs_date"] = self._normalize_bool(
            normalized.get("draft_needs_date")
        )
        normalized["draft_date_reason"] = self._normalize_optional_text(
            normalized.get("draft_date_reason")
        )
        normalized["draft_needs_attachment"] = self._normalize_bool(
            normalized.get("draft_needs_attachment")
        )
        normalized["draft_attachment_reason"] = self._normalize_optional_text(
            normalized.get("draft_attachment_reason")
        )
        return normalized

    def _normalize_queue_summary_payload(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        normalized = dict(payload)
        normalized["top_priorities"] = self._normalize_string_list(
            normalized.get("top_priorities")
        )
        normalized["executive_summary"] = self._normalize_text(
            normalized.get("executive_summary")
        )
        normalized["next_actions"] = self._normalize_string_list(
            normalized.get("next_actions")
        )
        return normalized

    def _normalize_draft_payload(self, payload: dict[str, object]) -> dict[str, object]:
        normalized = dict(payload)
        normalized["subject"] = self._normalize_text(normalized.get("subject"))
        normalized["body"] = self._normalize_text(normalized.get("body"))
        return normalized

    def _normalize_crm_payload(self, payload: dict[str, object]) -> dict[str, object]:
        normalized = dict(payload)
        normalized["contact_name"] = self._normalize_optional_text(
            normalized.get("contact_name")
        )
        normalized["company"] = self._normalize_optional_text(normalized.get("company"))
        normalized["opportunity_type"] = self._normalize_optional_text(
            normalized.get("opportunity_type")
        )
        normalized["next_action"] = self._normalize_optional_text(
            normalized.get("next_action")
        )
        normalized["urgency"] = self._normalize_urgency(normalized.get("urgency"))
        return normalized

    def _normalize_category(self, raw_value: object) -> str:
        if isinstance(raw_value, TriageCategory):
            return raw_value.value

        normalized = self._normalize_key(raw_value)
        direct_map = {
            self._normalize_key(category.value): category.value
            for category in TriageCategory
        }
        if normalized in direct_map:
            return direct_map[normalized]

        keyword_map = (
            (
                TriageCategory.FINANCE_ADMIN,
                ("finance", "billing", "invoice", "payment", "accounting", "admin"),
            ),
            (
                TriageCategory.EVENTS_LOGISTICS,
                ("event", "logistics", "meeting", "schedule", "calendar", "travel", "interview"),
            ),
            (
                TriageCategory.URGENT_EXECUTIVE,
                ("urgent", "executive", "critical", "escalation", "security"),
            ),
            (
                TriageCategory.CLASSIFIED_SENSITIVE,
                ("classified", "sensitive", "confidential", "protected", "cui"),
            ),
            (
                TriageCategory.CUSTOMER_PARTNER,
                ("customer", "client", "partner", "proposal", "sales", "account"),
            ),
            (
                TriageCategory.FYI_LOW_PRIORITY,
                ("fyi", "low", "monitor", "monitoring", "alert", "notification"),
            ),
        )
        for category, keywords in keyword_map:
            if any(keyword in normalized for keyword in keywords):
                return category.value
        return TriageCategory.FYI_LOW_PRIORITY.value

    def _normalize_urgency(self, raw_value: object) -> str:
        if isinstance(raw_value, UrgencyLevel):
            return raw_value.value

        normalized = self._normalize_key(raw_value)
        direct_map = {
            self._normalize_key(level.value): level.value
            for level in UrgencyLevel
        }
        if normalized in direct_map:
            return direct_map[normalized]

        if any(keyword in normalized for keyword in ("urgent", "critical", "asap", "high")):
            return UrgencyLevel.HIGH.value
        if any(keyword in normalized for keyword in ("medium", "normal", "soon")):
            return UrgencyLevel.MEDIUM.value
        if any(keyword in normalized for keyword in ("low", "minor", "routine")):
            return UrgencyLevel.LOW.value
        return UrgencyLevel.UNKNOWN.value

    @staticmethod
    def _normalize_bool(raw_value: object) -> bool:
        if isinstance(raw_value, bool):
            return raw_value
        if isinstance(raw_value, str):
            normalized = raw_value.strip().lower()
            if normalized in {"true", "yes", "1", "y"}:
                return True
            if normalized in {"false", "no", "0", "n", ""}:
                return False
        if isinstance(raw_value, (int, float)):
            return bool(raw_value)
        return False

    @staticmethod
    def _normalize_text(raw_value: object) -> str:
        if raw_value is None:
            return ""
        if isinstance(raw_value, str):
            return raw_value.strip()
        return str(raw_value).strip()

    @staticmethod
    def _normalize_optional_text(raw_value: object) -> str | None:
        text = OllamaProvider._normalize_text(raw_value)
        return text or None

    @staticmethod
    def _normalize_string_list(raw_value: object) -> list[str]:
        if raw_value is None:
            return []
        if isinstance(raw_value, str):
            return [raw_value.strip()] if raw_value.strip() else []
        if isinstance(raw_value, Iterable):
            values: list[str] = []
            for item in raw_value:
                text = OllamaProvider._normalize_text(item)
                if text:
                    values.append(text)
            return values
        text = OllamaProvider._normalize_text(raw_value)
        return [text] if text else []

    @staticmethod
    def _normalize_key(raw_value: object) -> str:
        return OllamaProvider._normalize_text(raw_value).lower()
