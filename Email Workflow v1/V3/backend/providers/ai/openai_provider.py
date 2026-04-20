"""OpenAI implementation of the provider interface."""

from __future__ import annotations

import json
from collections.abc import Iterable

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
from backend.domain.thread import (
    DraftDocument,
    ThreadAnalysis,
    TriageCategory,
    UrgencyLevel,
)
from backend.providers.ai.base import AIProvider, AIProviderError


class OpenAIProvider(AIProvider):
    """OpenAI-backed implementation used first in V3."""

    name = "openai"

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def analyze_thread(self, request: ThreadAnalysisRequest) -> ThreadAnalysis:
        payload = self._chat_json(
            task="thread_analysis",
            system_prompt=(
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
            user_payload=self._build_thread_analysis_payload(request),
        )
        normalized_payload = self._normalize_thread_analysis_payload(payload)
        try:
            return ThreadAnalysis.model_validate(
                {
                    **normalized_payload,
                    "provider_name": self.name,
                    "model_name": self.settings.model_for_provider_task(
                        self.name,
                        "thread_analysis",
                    ),
                    "used_fallback": False,
                }
            )
        except ValidationError as exc:
            raise AIProviderError(f"OpenAI returned invalid thread analysis: {exc}") from exc

    def summarize_queue(self, request: QueueSummaryRequest) -> QueueSummaryResult:
        payload = self._chat_json(
            task="queue_summary",
            system_prompt=(
                "You are summarizing an internal operations email queue. "
                "Return strict JSON with keys: top_priorities, executive_summary, next_actions."
            ),
            user_payload=request.model_dump(mode="json"),
        )
        normalized_payload = self._normalize_queue_summary_payload(payload)
        try:
            return QueueSummaryResult.model_validate(
                {
                    **normalized_payload,
                    "provider_name": self.name,
                    "model_name": self.settings.model_for_provider_task(
                        self.name,
                        "queue_summary",
                    ),
                    "used_fallback": False,
                }
            )
        except ValidationError as exc:
            raise AIProviderError(f"OpenAI returned invalid queue summary: {exc}") from exc

    def draft_reply(self, request: DraftReplyRequest) -> DraftDocument:
        payload = self._chat_json(
            task="draft_reply",
            system_prompt=(
                "Draft a professional reply email for an Inter-Op workflow. "
                "Return strict JSON with keys: subject, body."
            ),
            user_payload=request.model_dump(mode="json"),
        )
        normalized_payload = self._normalize_draft_payload(payload)
        try:
            return DraftDocument.model_validate(
                {
                    **normalized_payload,
                    "provider_name": self.name,
                    "model_name": self.settings.model_for_provider_task(
                        self.name,
                        "draft_reply",
                    ),
                    "used_fallback": False,
                }
            )
        except ValidationError as exc:
            raise AIProviderError(f"OpenAI returned invalid draft output: {exc}") from exc

    def extract_crm(self, request: CRMExtractionRequest) -> CRMExtractionResult:
        payload = self._chat_json(
            task="crm_extraction",
            system_prompt=(
                "Extract CRM-ready fields from this email thread. "
                "Use only these urgency values: "
                f"{', '.join(level.value for level in UrgencyLevel)}. "
                "Return strict JSON with keys: contact_name, company, opportunity_type, "
                "next_action, urgency."
            ),
            user_payload=self._build_crm_payload(request),
        )
        normalized_payload = self._normalize_crm_payload(payload)
        try:
            return CRMExtractionResult.model_validate(
                {
                    **normalized_payload,
                    "provider_name": self.name,
                    "model_name": self.settings.model_for_provider_task(
                        self.name,
                        "crm_extraction",
                    ),
                    "used_fallback": False,
                }
            )
        except ValidationError as exc:
            raise AIProviderError(f"OpenAI returned invalid CRM extraction: {exc}") from exc

    def _chat_json(
        self,
        task: str,
        system_prompt: str,
        user_payload: dict[str, object],
    ) -> dict[str, object]:
        if not self.settings.openai_api_key.strip():
            raise AIProviderError("OPENAI_API_KEY is missing.")

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise AIProviderError("The `openai` package is not installed.") from exc

        try:
            client = OpenAI(api_key=self.settings.openai_api_key)
            completion = client.chat.completions.create(
                model=self.settings.model_for_provider_task(self.name, task),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": json.dumps(user_payload, ensure_ascii=False),
                    },
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            content = completion.choices[0].message.content or "{}"
            return json.loads(content if isinstance(content, str) else "{}")
        except Exception as exc:  # pragma: no cover
            raise AIProviderError(f"OpenAI request failed: {exc}") from exc

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
                ("event", "logistics", "meeting", "schedule", "calendar", "travel"),
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
        text = OpenAIProvider._normalize_text(raw_value)
        return text or None

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

    @staticmethod
    def _normalize_string_list(raw_value: object) -> list[str]:
        if raw_value is None:
            return []
        if isinstance(raw_value, str):
            return [raw_value.strip()] if raw_value.strip() else []
        if isinstance(raw_value, Iterable):
            values: list[str] = []
            for item in raw_value:
                text = OpenAIProvider._normalize_text(item)
                if text:
                    values.append(text)
            return values
        text = OpenAIProvider._normalize_text(raw_value)
        return [text] if text else []

    @staticmethod
    def _normalize_key(raw_value: object) -> str:
        return OpenAIProvider._normalize_text(raw_value).lower()
