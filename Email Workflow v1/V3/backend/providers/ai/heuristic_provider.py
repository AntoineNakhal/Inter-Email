"""Deterministic AI fallback provider for local development and degraded mode."""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parseaddr

from backend.core.email_text import normalize_email_text
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
    ThreadAnalysis,
    TriageCategory,
    UrgencyLevel,
)
from backend.providers.ai.analysis_style import suggest_current_status
from backend.providers.ai.action_style import fit_next_action_to_thread, suggest_next_action
from backend.providers.ai.base import AIProvider
from backend.providers.ai.summary_style import suggest_summary


DATE_HINT_PATTERNS = (
    "meeting",
    "schedule",
    "calendar",
    "availability",
    "tomorrow",
    "next week",
)
ATTACHMENT_HINT_PATTERNS = (
    "attach",
    "attachment",
    "proposal",
    "quote",
    "invoice",
    "contract",
    "deck",
    "document",
)


class HeuristicAIProvider(AIProvider):
    """Fallback provider used when external AI is unavailable."""

    name = "heuristic"

    def analyze_thread(self, request: ThreadAnalysisRequest) -> ThreadAnalysis:
        thread = request.thread
        text = f"{thread.subject}\n{thread.combined_thread_text}".lower()
        urgency = self._infer_urgency(text=text, waiting_on_us=thread.waiting_on_us)
        category = self._infer_category(text=text)
        needs_action_today = urgency == UrgencyLevel.HIGH or (
            thread.waiting_on_us and not thread.resolved_or_closed
        )
        should_draft_reply = thread.waiting_on_us and not thread.resolved_or_closed

        return ThreadAnalysis(
            category=category,
            urgency=urgency,
            summary=self._build_summary(thread),
            current_status=self._build_status(thread),
            next_action=self._build_next_action(thread, needs_action_today),
            needs_action_today=needs_action_today,
            should_draft_reply=should_draft_reply,
            draft_needs_date=any(pattern in text for pattern in DATE_HINT_PATTERNS),
            draft_date_reason=(
                "The conversation references timing or scheduling."
                if any(pattern in text for pattern in DATE_HINT_PATTERNS)
                else None
            ),
            draft_needs_attachment=any(
                pattern in text for pattern in ATTACHMENT_HINT_PATTERNS
            ),
            draft_attachment_reason=(
                "The conversation likely needs a file or reference attachment."
                if any(pattern in text for pattern in ATTACHMENT_HINT_PATTERNS)
                else None
            ),
            provider_name=self.name,
            model_name="deterministic-fallback",
            used_fallback=True,
            analyzed_at=datetime.now(timezone.utc),
        )

    def summarize_queue(self, request: QueueSummaryRequest) -> QueueSummaryResult:
        actionable_threads = [
            thread
            for thread in request.threads
            if thread.analysis and thread.analysis.needs_action_today
        ]
        top_threads = actionable_threads[:5]
        return QueueSummaryResult(
            top_priorities=[
                f"{thread.subject}: {thread.analysis.summary}"
                for thread in top_threads
                if thread.analysis
            ],
            executive_summary=(
                f"{len(actionable_threads)} thread(s) need attention today. "
                f"{len(request.threads)} thread(s) are currently in the queue."
            ),
            next_actions=[
                thread.analysis.next_action
                for thread in top_threads
                if thread.analysis and thread.analysis.next_action
            ],
            provider_name=self.name,
            model_name="deterministic-fallback",
            used_fallback=True,
        )

    def verify_thread_analysis(
        self,
        request: ThreadVerificationRequest,
    ) -> ThreadVerificationResult:
        thread = request.thread
        analysis = request.analysis
        accuracy_percent = 58

        if analysis.summary.strip():
            accuracy_percent += 10
        if analysis.next_action.strip():
            accuracy_percent += 12
        if analysis.current_status.strip():
            accuracy_percent += 6
        if analysis.needs_action_today == thread.waiting_on_us:
            accuracy_percent += 6
        if thread.waiting_on_us and analysis.should_draft_reply:
            accuracy_percent += 4
        if analysis.category == self._infer_category(
            f"{thread.subject}\n{thread.combined_thread_text}".lower()
        ):
            accuracy_percent += 8
        if analysis.urgency == self._infer_urgency(
            text=f"{thread.subject}\n{thread.combined_thread_text}".lower(),
            waiting_on_us=thread.waiting_on_us,
        ):
            accuracy_percent += 6

        accuracy_percent = max(35, min(96, accuracy_percent))
        needs_human_review = accuracy_percent < 70 or not analysis.next_action.strip()
        review_reason = (
            "The local verifier is not fully confident in the summary or next action."
            if needs_human_review
            else None
        )
        verification_summary = (
            "Heuristic verifier sees a strong match between the thread signals and the generated analysis."
            if not needs_human_review
            else "Heuristic verifier found gaps or ambiguity in the generated analysis."
        )
        return ThreadVerificationResult(
            accuracy_percent=accuracy_percent,
            verification_summary=verification_summary,
            needs_human_review=needs_human_review,
            review_reason=review_reason,
            provider_name=self.name,
            model_name="deterministic-fallback",
            used_fallback=True,
            verified_at=datetime.now(timezone.utc),
        )

    def draft_reply(self, request: DraftReplyRequest) -> DraftDocument:
        thread = request.thread
        recipient = self._first_name(thread.participants[0] if thread.participants else "")
        greeting = f"Hi {recipient}," if recipient else "Hi,"
        subject = thread.subject.strip() or "Conversation update"
        if not subject.lower().startswith(("re:", "fw:", "fwd:")):
            subject = f"Re: {subject}"

        lines = [greeting, ""]
        lines.extend(self._build_draft_body_lines(request))

        lines.extend(["", "Best,", "Inter-Op Team"])
        return DraftDocument(
            subject=subject,
            body="\n".join(lines).strip(),
            provider_name=self.name,
            model_name="deterministic-fallback",
            used_fallback=True,
            created_at=datetime.now(timezone.utc),
        )

    def extract_crm(self, request: CRMExtractionRequest) -> CRMExtractionResult:
        thread = request.thread
        contact_name = self._first_name(thread.participants[0] if thread.participants else "")
        return CRMExtractionResult(
            contact_name=contact_name or None,
            company=self._infer_company(thread.participants),
            opportunity_type=self._infer_opportunity(thread.subject),
            next_action=thread.analysis.next_action if thread.analysis else None,
            urgency=thread.analysis.urgency if thread.analysis else UrgencyLevel.UNKNOWN,
            provider_name=self.name,
            model_name="deterministic-fallback",
            used_fallback=True,
        )

    def _infer_urgency(self, text: str, waiting_on_us: bool) -> UrgencyLevel:
        if any(marker in text for marker in ("urgent", "asap", "today", "deadline")):
            return UrgencyLevel.HIGH
        if any(marker in text for marker in ("invoice", "payment", "meeting", "review")):
            return UrgencyLevel.MEDIUM
        if waiting_on_us:
            return UrgencyLevel.MEDIUM
        return UrgencyLevel.LOW

    def _infer_category(self, text: str) -> TriageCategory:
        if any(marker in text for marker in ("invoice", "billing", "payment", "finance")):
            return TriageCategory.FINANCE_ADMIN
        if any(marker in text for marker in ("meeting", "schedule", "event", "calendar")):
            return TriageCategory.EVENTS_LOGISTICS
        if any(marker in text for marker in ("urgent", "executive", "security", "deadline")):
            return TriageCategory.URGENT_EXECUTIVE
        if any(marker in text for marker in ("classified", "protected", "tlp", "cui")):
            return TriageCategory.CLASSIFIED_SENSITIVE
        if any(marker in text for marker in ("client", "partner", "customer", "proposal")):
            return TriageCategory.CUSTOMER_PARTNER
        return TriageCategory.FYI_LOW_PRIORITY

    def _build_summary(self, thread) -> str:
        return suggest_summary(thread)

    def _build_status(self, thread) -> str:
        return suggest_current_status(thread)

    def _build_next_action(self, thread, needs_action_today: bool) -> str:
        if thread.resolved_or_closed:
            return "Keep the thread archived unless a new message reopens it."
        if thread.waiting_on_us and needs_action_today:
            return fit_next_action_to_thread("", thread)
        if thread.waiting_on_us:
            return fit_next_action_to_thread("", thread)
        if thread.latest_message_from_me:
            return suggest_next_action(thread)
        return suggest_next_action(thread)

    def _build_draft_body_lines(self, request: DraftReplyRequest) -> list[str]:
        thread = request.thread
        latest_text = self._latest_message_text(thread)
        lines: list[str] = []

        if any(
            marker in latest_text
            for marker in ("did you receive", "did you get this", "confirm receipt")
        ):
            lines.append("Yes, I received it. Thanks for the update.")
        elif any(
            marker in latest_text
            for marker in ("meet.google.com", "google meet", "meeting link", "join link")
        ):
            lines.append("Thanks, I received the link.")
        elif request.selected_date:
            lines.append(f"We are available on {request.selected_date}.")
        elif request.attachment_names:
            lines.append(
                f"I've attached {', '.join(request.attachment_names)} for reference."
            )
        else:
            lines.append("Thanks for the update.")

        if request.user_instructions.strip():
            lines.append(request.user_instructions.strip())
        elif request.selected_date:
            pass
        elif request.attachment_names:
            pass
        elif thread.analysis and thread.analysis.next_action:
            next_action = fit_next_action_to_thread(thread.analysis.next_action, thread)
            if "confirming you received this" in next_action.lower():
                pass
            elif "reply to" in next_action.lower() and "requested confirmation" in next_action.lower():
                lines.append("I'll get back to you with the requested confirmation shortly.")
            elif "meeting link" in next_action.lower():
                lines.append("I'll review the meeting details and follow up if anything else is needed.")

        return lines

    def _latest_message_text(self, thread) -> str:
        latest_message = thread.messages[-1] if thread.messages else None
        return normalize_email_text(
            "\n".join(
                part
                for part in [
                    latest_message.subject if latest_message else thread.subject,
                    latest_message.snippet if latest_message else "",
                    latest_message.cleaned_body if latest_message else thread.combined_thread_text,
                ]
                if part
            )
        ).lower()

    def _first_name(self, raw_value: str) -> str:
        name, email_address = parseaddr(raw_value)
        candidate = (name or email_address.split("@")[0]).strip().strip('"')
        if "," in candidate:
            candidate = candidate.split(",", 1)[1].strip()
        return candidate.split()[0].title() if candidate else ""

    def _infer_company(self, participants: list[str]) -> str | None:
        for participant in participants:
            _, email_address = parseaddr(participant)
            if "@" not in email_address:
                continue
            domain = email_address.split("@", 1)[1]
            if domain.endswith("inter-op.ca"):
                continue
            return domain.split(".")[0].replace("-", " ").title()
        return None

    def _infer_opportunity(self, subject: str) -> str | None:
        lowered = subject.lower()
        if "proposal" in lowered or "quote" in lowered:
            return "Proposal"
        if "meeting" in lowered or "demo" in lowered:
            return "Meeting"
        if "invoice" in lowered:
            return "Billing"
        return None
