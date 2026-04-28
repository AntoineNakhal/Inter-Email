"""Ollama implementation to support local AI without backend rewrites."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from collections.abc import Iterable
from urllib import parse as urllib_parse
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
    ThreadVerificationRequest,
    ThreadVerificationResult,
)
from backend.domain.runtime_settings import RuntimeSettings
from backend.domain.thread import (
    DraftDocument,
    EmailThread,
    ThreadAnalysis,
    TriageCategory,
    UrgencyLevel,
)
from backend.providers.ai.analysis_style import fit_current_status_to_thread
from backend.providers.ai.action_style import fit_next_action_to_thread
from backend.providers.ai.agents.ollama import (
    LocalCRMAgent,
    LocalDraftAgent,
    LocalInboxAgent,
    LocalQueueAgent,
    LocalVerificationAgent,
)
from backend.providers.ai.base import AIProvider, AIProviderError
from backend.providers.ai.summary_style import fit_summary_to_thread


class OllamaProvider(AIProvider):
    """Local/self-hosted provider implementation using Ollama's HTTP API."""

    name = "ollama"

    def __init__(self, settings: AppSettings, runtime_settings: RuntimeSettings) -> None:
        self.settings = settings
        self.runtime_settings = runtime_settings
        self.inbox_agent = LocalInboxAgent(runtime_settings)
        self.queue_agent = LocalQueueAgent(runtime_settings)
        self.draft_agent = LocalDraftAgent(runtime_settings)
        self.crm_agent = LocalCRMAgent(runtime_settings)
        self.verification_agent = LocalVerificationAgent(runtime_settings)

    def analyze_thread(self, request: ThreadAnalysisRequest) -> ThreadAnalysis:
        payload = self._generate_json(
            task=self.inbox_agent.task_name,
            prompt=self.inbox_agent.compose_prompt(
                self._build_thread_analysis_payload(request),
                user_email=request.user_email,
            ),
        )
        normalized_payload = self._normalize_thread_analysis_payload(
            payload,
            request.thread,
        )
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
            task=self.queue_agent.task_name,
            prompt=self.queue_agent.compose_prompt(
                request.model_dump(mode="json"),
                user_email=request.user_email,
            ),
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
            task=self.draft_agent.task_name,
            prompt=self.draft_agent.compose_prompt(
                self._build_draft_payload(request),
                user_email=request.user_email,
            ),
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
            task=self.crm_agent.task_name,
            prompt=self.crm_agent.compose_prompt(
                self._build_crm_payload(request),
                user_email=request.user_email,
            ),
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

    def verify_thread_analysis(
        self,
        request: ThreadVerificationRequest,
    ) -> ThreadVerificationResult:
        payload = self._generate_json(
            task=self.verification_agent.task_name,
            prompt=self.verification_agent.compose_prompt(
                self._build_thread_verification_payload(request),
                user_email=request.user_email,
            ),
        )
        normalized_payload = self._normalize_thread_verification_payload(payload)
        try:
            return ThreadVerificationResult.model_validate(
                {
                    **normalized_payload,
                    "provider_name": self.name,
                    "model_name": self._model_for_task("thread_verification"),
                    "used_fallback": False,
                    "verified_at": datetime.now(timezone.utc),
                }
            )
        except ValidationError as exc:
            raise AIProviderError(
                f"Ollama returned invalid thread verification: {exc}"
            ) from exc

    def _generate_json(
        self,
        task: str,
        prompt: str,
    ) -> dict[str, object]:
        model_name = self._model_for_task(task)
        if not model_name.strip():
            raise AIProviderError(f"No Ollama model configured for task `{task}`.")

        request_body = json.dumps(
            {
                "model": model_name,
                "prompt": prompt,
                "format": "json",
                "stream": False,
            }
        ).encode("utf-8")

        errors: list[str] = []
        for endpoint in self._generate_endpoint_candidates():
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
                errors.append(f"{endpoint}: {exc}")

        raise AIProviderError("Ollama request failed: " + " | ".join(errors))

    def _model_for_task(self, task: str) -> str:
        runtime_model = self.runtime_settings.local_ai_model.strip()
        if runtime_model:
            return runtime_model
        return self.settings.model_for_provider_task(self.name, task)

    def _generate_endpoint_candidates(self) -> list[str]:
        base_url = self.settings.ollama_base_url.strip() or "http://localhost:11434"
        parsed = urllib_parse.urlparse(base_url)
        hostname = (parsed.hostname or "").strip().lower()
        candidates = [base_url.rstrip("/") + "/api/generate"]

        alternate_host = None
        if hostname in {"localhost", "127.0.0.1"}:
            alternate_host = "host.docker.internal"
        elif hostname == "host.docker.internal":
            alternate_host = "localhost"

        if alternate_host:
            port = f":{parsed.port}" if parsed.port else ""
            alternate_base_url = urllib_parse.urlunparse(
                parsed._replace(netloc=f"{alternate_host}{port}")
            )
            candidates.append(alternate_base_url.rstrip("/") + "/api/generate")

        deduped: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            deduped.append(candidate)
        return deduped

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
                "latest_message": (
                    {
                        "sender": thread.messages[-1].sender,
                        "subject": thread.messages[-1].subject,
                        "sent_at": (
                            thread.messages[-1].sent_at.isoformat()
                            if thread.messages[-1].sent_at
                            else None
                        ),
                        "snippet": thread.messages[-1].snippet[:300],
                        "cleaned_body": thread.messages[-1].cleaned_body[:1000],
                    }
                    if thread.messages
                    else None
                ),
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

    def _build_draft_payload(
        self,
        request: DraftReplyRequest,
    ) -> dict[str, object]:
        thread = request.thread
        analysis = thread.analysis
        latest_message = thread.messages[-1] if thread.messages else None
        return {
            "drafting_priority": [
                "Follow user_instructions first when they are provided.",
                "Do not repeat the sender's message, signature, or confidentiality notice.",
                "Keep the reply concise and move the conversation forward.",
            ],
            "draft_context": {
                "user_instructions": request.user_instructions.strip(),
                "selected_date": request.selected_date,
                "attachment_names": request.attachment_names,
            },
            "thread": {
                "thread_id": thread.external_thread_id,
                "subject": thread.subject,
                "participants": thread.participants[:12],
                "latest_message": (
                    {
                        "sender": latest_message.sender,
                        "subject": latest_message.subject,
                        "sent_at": (
                            latest_message.sent_at.isoformat()
                            if latest_message.sent_at
                            else None
                        ),
                        "snippet": latest_message.snippet[:300],
                        "cleaned_body": latest_message.cleaned_body[:1200],
                    }
                    if latest_message
                    else None
                ),
                "analysis": {
                    "summary": analysis.summary if analysis else None,
                    "current_status": analysis.current_status if analysis else None,
                    "next_action": analysis.next_action if analysis else None,
                    "needs_action_today": (
                        analysis.needs_action_today if analysis else None
                    ),
                    "should_draft_reply": (
                        analysis.should_draft_reply if analysis else None
                    ),
                },
            },
        }

    def _build_thread_verification_payload(
        self,
        request: ThreadVerificationRequest,
    ) -> dict[str, object]:
        return {
            "thread": self._build_thread_analysis_payload(
                ThreadAnalysisRequest(thread=request.thread)
            )["thread"],
            "analysis": {
                "category": request.analysis.category.value,
                "urgency": request.analysis.urgency.value,
                "summary": request.analysis.summary,
                "current_status": request.analysis.current_status,
                "next_action": request.analysis.next_action,
                "needs_action_today": request.analysis.needs_action_today,
                "should_draft_reply": request.analysis.should_draft_reply,
                "draft_needs_date": request.analysis.draft_needs_date,
                "draft_needs_attachment": request.analysis.draft_needs_attachment,
                "crm_contact_name": request.analysis.crm_contact_name,
                "crm_company": request.analysis.crm_company,
                "crm_opportunity_type": request.analysis.crm_opportunity_type,
            },
        }

    def _normalize_thread_analysis_payload(
        self,
        payload: dict[str, object],
        thread: EmailThread,
    ) -> dict[str, object]:
        normalized = dict(payload)
        normalized["category"] = self._normalize_category(normalized.get("category"))
        normalized["urgency"] = self._normalize_urgency(normalized.get("urgency"))
        normalized["summary"] = fit_summary_to_thread(
            self._normalize_text(normalized.get("summary")),
            thread,
        )
        normalized["current_status"] = fit_current_status_to_thread(
            self._normalize_text(normalized.get("current_status")),
            thread,
        )
        normalized["next_action"] = fit_next_action_to_thread(
            self._normalize_text(normalized.get("next_action")),
            thread,
        )
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

    def _normalize_thread_verification_payload(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        normalized = dict(payload)
        accuracy_raw = normalized.get("accuracy_percent")
        try:
            accuracy_percent = int(accuracy_raw)
        except (TypeError, ValueError):
            accuracy_percent = 0
        normalized["accuracy_percent"] = max(0, min(100, accuracy_percent))
        normalized["verification_summary"] = self._normalize_text(
            normalized.get("verification_summary")
        )
        normalized["needs_human_review"] = self._normalize_bool(
            normalized.get("needs_human_review")
        )
        normalized["review_reason"] = self._normalize_optional_text(
            normalized.get("review_reason")
        )
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
