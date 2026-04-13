"""Deterministic orchestration for the V1 pipeline."""

from __future__ import annotations

import os
import re

from agents.crm_agent import CrmAgentRunner
from agents.summary_agent import SummaryAgentRunner
from agents.triage_agent import TriageAgentRunner
from config import Settings
from schemas import (
    AgentEmail,
    CrmBatch,
    CrmRecord,
    FinalRunOutput,
    PipelineError,
    SummaryOutput,
    TriageBatch,
    TriageItem,
)
from services.email_service import EmailService


class TriageManager:
    """Simple manager that runs fetch -> triage -> summary -> CRM extraction."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.email_service = EmailService(settings)
        self.triage_agent = TriageAgentRunner(model=settings.openai_model)
        self.summary_agent = SummaryAgentRunner(model=settings.openai_model)
        self.crm_agent = CrmAgentRunner(model=settings.openai_model)

    def run(self) -> FinalRunOutput:
        """Run the full workflow in a deterministic order."""

        if self.settings.processing_mode == "ai" and not os.getenv("OPENAI_API_KEY"):
            raise ValueError(
                "OPENAI_API_KEY is missing. Add it to .env before running the app."
            )

        emails = self.email_service.fetch_recent_emails(
            max_results=self.settings.gmail_max_results
        )
        agent_emails, selection_log = self.email_service.select_emails_for_ai(emails)
        filtered_emails = [item for item in selection_log if not item.included_in_ai]

        print(
            f"[manager] mode={self.settings.processing_mode} model={self.settings.openai_model} "
            f"sent_to_ai={len(agent_emails)} fetched={len(emails)} filtered={len(filtered_emails)}"
        )
        for item in filtered_emails:
            print(
                f"[filter] skipped {item.message_id} score={item.relevance_score} "
                f"reason={item.reason}"
            )

        if not emails:
            return FinalRunOutput(
                email_count=0,
                ai_email_count=0,
                filtered_email_count=0,
                emails=[],
                triage=[],
                summary=SummaryOutput(
                    top_priorities=[],
                    executive_summary="No recent emails were returned by Gmail.",
                    next_actions=[],
                ),
                crm_records=[],
                email_selection=[],
            )

        if not agent_emails:
            return FinalRunOutput(
                email_count=len(emails),
                ai_email_count=0,
                filtered_email_count=len(filtered_emails),
                emails=emails,
                triage=[],
                summary=SummaryOutput(
                    top_priorities=[],
                    executive_summary=(
                        "No emails passed the low-value filters and relevance threshold, "
                        "so nothing was sent to the AI pipeline."
                    ),
                    next_actions=[],
                ),
                crm_records=[],
                email_selection=selection_log,
                errors=[],
            )

        errors: list[PipelineError] = []

        if self.settings.processing_mode == "fallback":
            print("[manager] fallback mode selected. Skipping OpenAI calls.")
            triage_batch = TriageBatch(
                items=[self._fallback_triage(email) for email in agent_emails]
            )
            summary = self._fallback_summary(triage_batch.items)
            crm_batch = self._fallback_crm_batch(agent_emails)
            errors.extend(
                [
                    PipelineError(
                        step="triage",
                        message="Processing mode was set to fallback.",
                        used_fallback=True,
                    ),
                    PipelineError(
                        step="summary",
                        message="Processing mode was set to fallback.",
                        used_fallback=True,
                    ),
                    PipelineError(
                        step="crm",
                        message="Processing mode was set to fallback.",
                        used_fallback=True,
                    ),
                ]
            )
        else:
            try:
                triage_batch = self.triage_agent.run(agent_emails)
            except RuntimeError as exc:
                print(f"[triage] failed. Using fallback classification. {exc}")
                errors.append(
                    PipelineError(step="triage", message=str(exc), used_fallback=True)
                )
                triage_batch = TriageBatch(
                    items=[self._fallback_triage(email) for email in agent_emails]
                )

            try:
                summary = self.summary_agent.run(agent_emails, triage_batch.items)
            except RuntimeError as exc:
                print(f"[summary] failed. Using fallback summary. {exc}")
                errors.append(
                    PipelineError(step="summary", message=str(exc), used_fallback=True)
                )
                summary = self._fallback_summary(triage_batch.items)

            try:
                crm_batch = self.crm_agent.run(agent_emails)
            except RuntimeError as exc:
                print(f"[crm] failed. Using fallback CRM extraction. {exc}")
                errors.append(
                    PipelineError(step="crm", message=str(exc), used_fallback=True)
                )
                crm_batch = self._fallback_crm_batch(agent_emails)

        return FinalRunOutput(
            email_count=len(emails),
            ai_email_count=len(agent_emails),
            filtered_email_count=len(filtered_emails),
            emails=emails,
            triage=triage_batch.items,
            summary=summary,
            crm_records=crm_batch.records,
            email_selection=selection_log,
            errors=errors,
        )

    def _fallback_triage(self, email: AgentEmail) -> TriageItem:
        text = f"{email.subject} {email.snippet} {email.body}".lower()
        category = "FYI / Low Priority"
        summary = self._short_summary(email)
        needs_action_today = False
        urgency = "low"

        if any(
            word in text
            for word in ["urgent", "asap", "executive", "security alert", "invoice due"]
        ):
            category = "Urgent / Executive"
            needs_action_today = True
            urgency = "high"
            summary = self._short_summary(
                email, "Urgent or executive item requiring attention."
            )
        elif any(
            word in text
            for word in ["customer", "client", "partner", "proposal", "deal", "contract"]
        ):
            category = "Customer / Partner"
            needs_action_today = True
            urgency = "medium"
            summary = self._short_summary(
                email, "Customer or partner communication with follow-up value."
            )
        elif any(
            word in text
            for word in ["event", "meeting", "schedule", "flight", "hotel", "logistics"]
        ):
            category = "Events / Logistics"
            urgency = "medium"
            summary = self._short_summary(email, "Scheduling or logistics-related update.")
        elif any(
            word in text
            for word in ["invoice", "payment", "finance", "admin", "billing", "receipt"]
        ):
            category = "Finance / Admin"
            urgency = "medium"
            needs_action_today = "due" in text or "payment" in text
            summary = self._short_summary(
                email, "Finance or admin message that may need review."
            )

        return TriageItem(
            message_id=email.id,
            category=category,
            summary=summary,
            urgency=urgency,
            needs_action_today=needs_action_today,
        )

    def _fallback_summary(self, triage_items: list[TriageItem]) -> SummaryOutput:
        priorities = [
            f"{item.category} ({item.urgency}): {item.summary}"
            for item in triage_items
            if item.needs_action_today
        ][:5]
        if not priorities:
            priorities = ["No urgent action items were detected by the fallback summary."]

        next_actions = [
            f"Review {item.category.lower()} email: {item.summary}"
            for item in triage_items
            if item.needs_action_today
        ][:5]

        return SummaryOutput(
            top_priorities=priorities,
            executive_summary=(
                f"Processed {len(triage_items)} email(s). "
                f"{sum(1 for item in triage_items if item.needs_action_today)} need attention today. "
                "The rest are informational or lower priority."
            ),
            next_actions=next_actions,
        )

    def _fallback_crm_batch(self, emails: list[AgentEmail]) -> CrmBatch:
        records = [self._fallback_crm(email) for email in emails]
        return CrmBatch(records=records)

    def _fallback_crm(self, email: AgentEmail) -> CrmRecord:
        sender = email.sender
        name = sender.split("<")[0].strip().strip('"') if sender else None
        company = self._extract_company(sender)
        text = f"{email.subject} {email.snippet} {email.body}".lower()

        opportunity_type = None
        if "renewal" in text:
            opportunity_type = "renewal"
        elif any(word in text for word in ["demo", "proposal", "quote", "deal"]):
            opportunity_type = "new_business"

        next_action = None
        if any(word in text for word in ["please", "reply", "follow up", "review"]):
            next_action = "Review the email and send a response if needed."

        urgency = "unknown"
        if any(word in text for word in ["urgent", "asap"]):
            urgency = "high"
        elif any(word in text for word in ["invoice", "payment", "renewal", "proposal"]):
            urgency = "medium"
        elif text:
            urgency = "low"

        return CrmRecord(
            message_id=email.id,
            contact_name=name or None,
            company=company,
            opportunity_type=opportunity_type,
            next_action=next_action,
            urgency=urgency,
        )

    def _short_summary(self, email: AgentEmail, fallback: str | None = None) -> str:
        source = fallback or email.snippet or email.subject or email.body
        return " ".join(source.split())[:160]

    def _extract_company(self, sender: str) -> str | None:
        match = re.search(r"@([A-Za-z0-9.-]+)", sender or "")
        if not match:
            return None
        parts = [part for part in match.group(1).split(".") if part]
        company_part = parts[-2] if len(parts) >= 2 else parts[0]
        return company_part.replace("-", " ").title()
