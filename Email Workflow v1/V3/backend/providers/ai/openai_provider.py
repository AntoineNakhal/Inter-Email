"""OpenAI implementation of the provider interface."""

from __future__ import annotations

from datetime import datetime, timezone
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
    ThreadVerificationRequest,
    ThreadVerificationResult,
)
from backend.domain.thread import (
    DraftDocument,
    EmailThread,
    ThreadAnalysis,
    TriageCategory,
    UrgencyLevel,
)
from backend.providers.ai.analysis_style import fit_current_status_to_thread
from backend.providers.ai.action_style import fit_next_action_to_thread
from backend.providers.ai.base import AIProvider, AIProviderError
from backend.providers.ai.summary_style import fit_summary_to_thread


class OpenAIProvider(AIProvider):
    """OpenAI-backed implementation used first in V3."""

    name = "openai"

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    @staticmethod
    def _user_perspective_block(user_email: str | None) -> str:
        """
        Returns a short paragraph that tells the model whose inbox this is.
        When `user_email` is None we return "" so the system prompt is
        unchanged — keeps the path safe when no Gmail account is connected.
        """
        if not user_email:
            return ""
        return (
            f"PERSPECTIVE: You are analyzing this thread on behalf of {user_email}, "
            "the inbox owner. Treat that address as 'the user'. "
            f"When a message's From header is {user_email}, the user SENT that message — "
            "do not suggest the user 'reply' to their own messages. "
            f"When {user_email} is in To/Cc/Bcc, the user RECEIVED that message. "
            "Frame summary, current_status, and next_action from the user's point of view "
            "(what THEY need to do next, not what 'someone' needs to do).\n\n"
        )

    def analyze_thread(self, request: ThreadAnalysisRequest) -> ThreadAnalysis:
        payload = self._chat_json(
            task="thread_analysis",
            system_prompt=(
                self._user_perspective_block(request.user_email)
                + "You are analyzing one email thread for an internal operations queue. "
                "Ignore email signatures, confidentiality footers, and quoted reply history. "
                "Anchor the analysis primarily on the latest meaningful message, using earlier messages only as context. "
                "For very short emails, keep the summary extremely short and never more detailed "
                "than the source message itself. "
                "The next_action must be concrete and tied to what was actually said in the latest message. "
                "Avoid generic actions like 'prepare and send a reply today'. "
                "The current_status should describe the exact state of the conversation, not a vague generic label. "
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
        normalized_payload = self._normalize_thread_analysis_payload(
            payload,
            request.thread,
        )
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
                self._user_perspective_block(request.user_email)
                + "You are summarizing an internal operations email queue. "
                "Write a concise executive_summary (2-3 sentences) of what needs attention today. "
                "List the top 3-5 threads in top_priorities as short strings (subject: one-line reason). "
                "List 3-5 concrete next_actions as short imperative sentences. "
                "Return strict JSON with keys: top_priorities, executive_summary, next_actions."
            ),
            user_payload=self._build_queue_summary_payload(request),
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

    def verify_thread_analysis(
        self,
        request: ThreadVerificationRequest,
    ) -> ThreadVerificationResult:
        payload = self._chat_json(
            task="thread_verification",
            system_prompt=(
                self._user_perspective_block(request.user_email)
                + "You are verifying the quality of an email-thread analysis for an internal operations queue. "
                "Do not rewrite the analysis. Judge whether it is likely accurate and actionable based on the thread. "
                "Pay particular attention to whether the analysis correctly identifies who SENT vs RECEIVED each message; "
                "if next_action assumes the user must reply to a message they themselves sent, mark it for review. "
                "Return strict JSON with keys: accuracy_percent, verification_summary, "
                "needs_human_review, review_reason."
            ),
            user_payload=self._build_thread_verification_payload(request),
        )
        normalized_payload = self._normalize_thread_verification_payload(payload)
        try:
            return ThreadVerificationResult.model_validate(
                {
                    **normalized_payload,
                    "provider_name": self.name,
                    "model_name": self.settings.model_for_provider_task(
                        self.name,
                        "thread_verification",
                    ),
                    "used_fallback": False,
                    "verified_at": datetime.now(timezone.utc),
                }
            )
        except ValidationError as exc:
            raise AIProviderError(
                f"OpenAI returned invalid thread verification: {exc}"
            ) from exc

    def draft_reply(self, request: DraftReplyRequest) -> DraftDocument:
        payload = self._chat_json(
            task="draft_reply",
            system_prompt=(
                self._user_perspective_block(request.user_email)
                + "Draft a professional reply email for an Inter-Op workflow. "
                "Write the draft FROM the user (the inbox owner). Do not address the user as a third party. "
                "Do not repeat the sender's full message, signature, or confidentiality notice. "
                "Acknowledge briefly, answer the actual ask, and move the conversation forward. "
                "Keep the draft concise unless the request clearly needs more detail. "
                "If user_instructions are present, treat them as the highest-priority drafting requirements "
                "and change the draft accordingly. "
                "If selected_date or attachment_names are present, incorporate them when relevant. "
                "Return strict JSON with keys: subject, body."
            ),
            user_payload=self._build_draft_payload(request),
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

    def _build_queue_summary_payload(
        self,
        request: QueueSummaryRequest,
    ) -> dict[str, object]:
        # Send only the fields Claude needs to write a summary.
        # Never dump full EmailThread objects — messages and bodies are irrelevant here.
        return {
            "thread_count": len(request.threads),
            "threads": [
                {
                    "subject": thread.subject,
                    "category": thread.analysis.category.value if thread.analysis else None,
                    "urgency": thread.analysis.urgency.value if thread.analysis else None,
                    "summary": thread.analysis.summary if thread.analysis else None,
                    "next_action": thread.analysis.next_action if thread.analysis else None,
                    "needs_action_today": (
                        thread.analysis.needs_action_today if thread.analysis else False
                    ),
                    "waiting_on_us": thread.waiting_on_us,
                }
                for thread in request.threads
            ],
        }

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
        thread = request.thread
        latest = thread.messages[-1] if thread.messages else None
        # The verifier only needs enough context to sanity-check the analysis —
        # not the full thread. Sending subject + latest snippet + key flags is
        # sufficient and avoids re-shipping thousands of tokens already consumed
        # by the analysis call.
        return {
            "thread_context": {
                "subject": thread.subject,
                "message_count": thread.message_count,
                "waiting_on_us": thread.waiting_on_us,
                "resolved_or_closed": thread.resolved_or_closed,
                "latest_message_from_me": thread.latest_message_from_me,
                "latest_message": (
                    {
                        "sender": latest.sender,
                        "sent_at": (
                            latest.sent_at.isoformat() if latest.sent_at else None
                        ),
                        "snippet": latest.snippet[:300],
                    }
                    if latest
                    else None
                ),
            },
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
