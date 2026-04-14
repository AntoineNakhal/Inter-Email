"""Deterministic orchestration for the V2 thread-based pipeline."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone

from agents.classified_agent import ClassifiedThreadAgentRunner
from agents.crm_agent import CrmAgentRunner
from agents.reply_draft_agent import ReplyDraftAgentRunner
from agents.summary_agent import SummaryAgentRunner
from agents.triage_agent import TriageAgentRunner
from config import Settings
from schemas import (
    AgentThread,
    EmailThread,
    FinalRunOutput,
    PipelineError,
    SensitiveThreadRecord,
    SummaryActionItem,
    SummaryOutput,
    ThreadCrmBatch,
    ThreadCrmRecord,
    ThreadReplyDraftBatch,
    ThreadReplyDraftRecord,
    ThreadTriageBatch,
    ThreadTriageItem,
)
from services.email_service import EmailService
from services.draft_workflow import (
    extract_first_name,
    fallback_reply_plan,
    fallback_reply_plan_batch,
)
from services.progress_state import WorkflowProgressTracker
from services.thread_cache import (
    apply_cached_predictions,
    build_cached_crm_record,
    build_cached_reply_draft_record,
    build_cached_triage_item,
    build_summary_signature,
    cache_entry_has_predictions,
    compute_thread_signature,
    detect_change_status,
    get_thread_cache_entry,
    load_cached_summary,
    load_thread_cache,
    save_cached_summary,
    save_thread_cache,
    upsert_thread_cache_entry,
)


class TriageManager:
    """Simple manager that runs fetch -> group -> triage -> CRM -> drafting -> summary."""

    def __init__(
        self,
        settings: Settings,
        progress_tracker: WorkflowProgressTracker | None = None,
    ) -> None:
        self.settings = settings
        self.progress_tracker = progress_tracker
        self.email_service = EmailService(settings)
        self.classified_agent = ClassifiedThreadAgentRunner()
        self.triage_agent = TriageAgentRunner(model=settings.openai_model)
        self.summary_agent = SummaryAgentRunner(model=settings.openai_model)
        self.crm_agent = CrmAgentRunner(model=settings.openai_model)
        self.reply_draft_agent = ReplyDraftAgentRunner(model=settings.openai_model)

    def _update_progress(self, phase: str, progress: int, detail: str) -> None:
        """Write a progress update when a tracker is attached."""

        if self.progress_tracker is not None:
            self.progress_tracker.update(phase, progress, detail)

    def run(self) -> FinalRunOutput:
        """Run the full workflow in a deterministic order."""

        self._update_progress("fetching_threads", 8, "Fetching Gmail threads...")
        if self.settings.processing_mode == "ai" and not os.getenv("OPENAI_API_KEY"):
            raise ValueError(
                "OPENAI_API_KEY is missing. Add it to .env before running the app."
            )

        threads = self.email_service.fetch_recent_threads(
            max_results=self.settings.gmail_max_results
        )
        total_messages = sum(thread.message_count for thread in threads)
        self._update_progress(
            "grouping_threads",
            22,
            f"Fetched {len(threads)} thread(s). Grouping conversations...",
        )
        candidate_agent_threads = self.email_service.select_threads_for_ai(threads)
        cache_payload = load_thread_cache(self.settings.resolved_thread_cache_path)
        run_started_at = datetime.now(timezone.utc).isoformat()
        sensitive_threads = [thread for thread in threads if thread.security_status == "classified"]
        self._update_progress(
            "checking_sensitive_and_cache",
            34,
            "Checking sensitive threads and reusable cached analysis...",
        )
        sensitive_records = self.classified_agent.run(sensitive_threads).records
        self._apply_sensitive_predictions(threads=threads, sensitive_records=sensitive_records)

        agent_threads_by_id = {
            thread.thread_id: thread for thread in candidate_agent_threads
        }
        fresh_agent_threads: list[AgentThread] = []
        cached_triage_items: list[ThreadTriageItem] = []
        cached_crm_records: list[ThreadCrmRecord] = []
        cached_reply_draft_records: list[ThreadReplyDraftRecord] = []
        draft_refresh_threads: list[EmailThread] = []

        for thread in threads:
            thread.thread_signature = compute_thread_signature(thread)
            cache_entry = get_thread_cache_entry(cache_payload, thread.thread_id)
            thread.change_status = detect_change_status(
                cache_entry=cache_entry,
                thread_signature=thread.thread_signature,
            )
            if cache_entry.get("last_analysis_at"):
                thread.last_analysis_at = str(cache_entry.get("last_analysis_at"))

            if thread.security_status == "classified":
                thread.analysis_status = "guardrailed"
                thread.last_analysis_at = run_started_at
                continue

            if not thread.included_in_ai:
                if thread.relevance_bucket == "noise":
                    thread.analysis_status = "skipped"
                else:
                    thread.analysis_status = "not_requested"
                continue

            can_reuse_cache = (
                thread.change_status == "unchanged"
                and cache_entry_has_predictions(cache_entry)
            )
            if can_reuse_cache:
                apply_cached_predictions(thread, cache_entry)
                thread.analysis_status = "cached"
                cached_triage_item = build_cached_triage_item(thread.thread_id, cache_entry)
                cached_crm_record = build_cached_crm_record(thread.thread_id, cache_entry)
                cached_reply_draft_record = build_cached_reply_draft_record(
                    thread.thread_id, cache_entry
                )
                if cached_triage_item is not None:
                    cached_triage_items.append(cached_triage_item)
                if cached_crm_record is not None:
                    cached_crm_records.append(cached_crm_record)
                if cached_reply_draft_record is not None:
                    cached_reply_draft_records.append(cached_reply_draft_record)
                else:
                    draft_refresh_threads.append(thread)
                continue

            thread.analysis_status = "fresh"
            thread.last_analysis_at = run_started_at
            fresh_agent_thread = agent_threads_by_id.get(thread.thread_id)
            if fresh_agent_thread is not None:
                fresh_agent_threads.append(fresh_agent_thread)

        covered_threads = [thread for thread in threads if thread.included_in_ai]
        filtered_threads = [thread for thread in threads if not thread.included_in_ai]
        cached_threads = [thread for thread in covered_threads if thread.analysis_status == "cached"]
        fresh_threads = [thread for thread in covered_threads if thread.analysis_status == "fresh"]

        print(
            f"[manager] mode={self.settings.processing_mode} model={self.settings.openai_model} "
            f"covered_threads={len(covered_threads)} fresh={len(fresh_threads)} "
            f"cached={len(cached_threads)} fetched_threads={len(threads)} "
            f"fetched_messages={total_messages} filtered={len(filtered_threads)}"
        )
        for thread in filtered_threads:
            print(
                f"[filter] skipped {thread.thread_id} bucket={thread.relevance_bucket} "
                f"score={thread.relevance_score} "
                f"reason={thread.selection_reason}"
            )

        if not threads:
            return FinalRunOutput(
                thread_count=0,
                message_count=0,
                ai_thread_count=0,
                filtered_thread_count=0,
                threads=[],
                summary=SummaryOutput(
                    top_priorities=[],
                    executive_summary="No recent Gmail threads were returned.",
                    next_actions=[],
                ),
            )

        if not covered_threads:
            self._update_progress(
                "saving_cache",
                88,
                "No AI analysis needed. Saving refreshed queue...",
            )
            sensitive_count = len(sensitive_threads)
            for thread in threads:
                upsert_thread_cache_entry(
                    cache_payload=cache_payload,
                    thread=thread,
                    seen_at=run_started_at,
                )
            save_thread_cache(cache_payload, self.settings.resolved_thread_cache_path)
            return FinalRunOutput(
                thread_count=len(threads),
                message_count=total_messages,
                ai_thread_count=0,
                fresh_ai_thread_count=0,
                cached_ai_thread_count=0,
                filtered_thread_count=len(filtered_threads),
                new_thread_count=len(
                    [thread for thread in threads if thread.change_status == "new"]
                ),
                changed_thread_count=len(
                    [thread for thread in threads if thread.change_status == "changed"]
                ),
                threads=threads,
                summary=SummaryOutput(
                    top_priorities=(
                        [
                            f"{thread.subject}: sensitive/classified hold for manual review."
                            for thread in sensitive_threads[:5]
                        ]
                        if sensitive_threads
                        else []
                    ),
                    executive_summary=(
                        (
                            f"{sensitive_count} sensitive/classified thread(s) were held out "
                            "of AI and need manual review. The review UI still shows them "
                            "alongside maybe and noise threads."
                        )
                        if sensitive_threads
                        else (
                            "No threads landed in the auto-analysis buckets for this run. "
                            "The review UI still shows maybe and noise threads."
                        )
                    ),
                    next_actions=(
                        [
                            "Review sensitive/classified threads manually outside the AI workflow."
                        ]
                        if sensitive_threads
                        else []
                    ),
                    action_items=(
                        [
                            SummaryActionItem(
                                thread_id=thread.thread_id,
                                label=f"Review sensitive/classified hold: {thread.subject}",
                            )
                            for thread in sensitive_threads[:5]
                        ]
                        if sensitive_threads
                        else []
                    ),
                ),
                errors=[],
            )

        errors: list[PipelineError] = []

        fresh_triage_items: list[ThreadTriageItem] = []
        fresh_crm_records: list[ThreadCrmRecord] = []

        if fresh_agent_threads:
            self._update_progress(
                "triage_and_crm",
                52,
                f"Running AI triage on {len(fresh_agent_threads)} conversation(s)...",
            )
            if self.settings.processing_mode == "fallback":
                print("[manager] fallback mode selected. Skipping OpenAI calls.")
                fresh_triage_items = [
                    self._fallback_triage(thread) for thread in fresh_agent_threads
                ]
                fresh_crm_records = self._fallback_crm_batch(fresh_agent_threads).records
                errors.extend(
                    [
                        PipelineError(
                            step="triage",
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
                    fresh_triage_items = self.triage_agent.run(fresh_agent_threads).items
                except RuntimeError as exc:
                    print(f"[triage] failed. Using fallback classification. {exc}")
                    errors.append(
                        PipelineError(step="triage", message=str(exc), used_fallback=True)
                    )
                    fresh_triage_items = [
                        self._fallback_triage(thread) for thread in fresh_agent_threads
                    ]

                try:
                    fresh_crm_records = self.crm_agent.run(fresh_agent_threads).records
                except RuntimeError as exc:
                    print(f"[crm] failed. Using fallback CRM extraction. {exc}")
                    errors.append(
                        PipelineError(step="crm", message=str(exc), used_fallback=True)
                    )
                    fresh_crm_records = self._fallback_crm_batch(fresh_agent_threads).records

        triage_batch = ThreadTriageBatch(items=cached_triage_items + fresh_triage_items)
        crm_batch = ThreadCrmBatch(records=cached_crm_records + fresh_crm_records)

        self._apply_predictions(
            threads=threads,
            triage_items=triage_batch.items,
            crm_records=crm_batch.records,
        )

        reply_draft_batch = ThreadReplyDraftBatch(records=list(cached_reply_draft_records))
        draft_target_threads = list(fresh_threads) + draft_refresh_threads
        if draft_target_threads:
            self._update_progress(
                "reply_drafts",
                68,
                f"Preparing reply suggestions for {len(draft_target_threads)} conversation(s)...",
            )
            fresh_reply_draft_records: list[ThreadReplyDraftRecord] = []
            if self.settings.processing_mode == "fallback":
                fresh_reply_draft_records = self._fallback_reply_draft_batch(
                    draft_target_threads
                ).records
                errors.append(
                    PipelineError(
                        step="reply_draft",
                        message="Processing mode was set to fallback.",
                        used_fallback=True,
                    )
                )
            else:
                try:
                    fresh_reply_draft_records = self.reply_draft_agent.run(
                        draft_target_threads
                    ).records
                except RuntimeError as exc:
                    print(f"[reply_draft] failed. Using fallback drafting. {exc}")
                    errors.append(
                        PipelineError(
                            step="reply_draft",
                            message=str(exc),
                            used_fallback=True,
                        )
                    )
                    fresh_reply_draft_records = self._fallback_reply_draft_batch(
                        draft_target_threads
                    ).records

            reply_draft_batch = ThreadReplyDraftBatch(
                records=reply_draft_batch.records + fresh_reply_draft_records
            )

        self._apply_reply_drafts(threads=threads, draft_records=reply_draft_batch.records)

        covered_agent_threads = [
            agent_threads_by_id[thread.thread_id]
            for thread in covered_threads
            if thread.thread_id in agent_threads_by_id
        ]
        coverage_signature = build_summary_signature(covered_threads)
        cached_summary = load_cached_summary(cache_payload, coverage_signature)

        if cached_summary is not None:
            self._update_progress(
                "summary",
                82,
                "Reusing cached executive summary...",
            )
            summary = cached_summary
        elif self.settings.processing_mode == "fallback":
            self._update_progress(
                "summary",
                82,
                "Building fallback executive summary...",
            )
            summary = self._fallback_summary(triage_batch.items)
            errors.append(
                PipelineError(
                    step="summary",
                    message="Processing mode was set to fallback.",
                    used_fallback=True,
                )
            )
        else:
            self._update_progress(
                "summary",
                82,
                "Building executive summary and top actions...",
            )
            try:
                summary = self.summary_agent.run(covered_agent_threads, triage_batch.items)
            except RuntimeError as exc:
                print(f"[summary] failed. Using fallback summary. {exc}")
                errors.append(
                    PipelineError(step="summary", message=str(exc), used_fallback=True)
                )
                summary = self._fallback_summary(triage_batch.items)

        save_cached_summary(
            cache_payload=cache_payload,
            coverage_signature=coverage_signature,
            summary=summary,
            cached_at=run_started_at,
        )
        self._update_progress(
            "saving_cache",
            92,
            "Saving cache and final workflow state...",
        )
        for thread in threads:
            upsert_thread_cache_entry(
                cache_payload=cache_payload,
                thread=thread,
                seen_at=run_started_at,
            )
        save_thread_cache(cache_payload, self.settings.resolved_thread_cache_path)

        final_summary = summary.model_copy(deep=True)
        if sensitive_threads:
            sensitive_notice = (
                f"{len(sensitive_threads)} sensitive/classified thread(s) were held out "
                "of AI and shown separately for manual review."
            )
            final_summary.top_priorities = [sensitive_notice, *final_summary.top_priorities][:5]
            final_summary.executive_summary = (
                f"{sensitive_notice}\n{final_summary.executive_summary}".strip()
            )
            final_summary.next_actions = [
                "Review the sensitive/classified hold section before acting on AI outputs.",
                *final_summary.next_actions,
            ][:5]
            sensitive_action_items = [
                SummaryActionItem(
                    thread_id=thread.thread_id,
                    label="Review sensitive/classified hold",
                )
                for thread in sensitive_threads[:5]
            ]
            final_summary.action_items = [
                *sensitive_action_items,
                *final_summary.action_items,
            ][:5]

        return FinalRunOutput(
            thread_count=len(threads),
            message_count=total_messages,
            ai_thread_count=len(covered_threads),
            fresh_ai_thread_count=len(fresh_threads),
            cached_ai_thread_count=len(cached_threads),
            filtered_thread_count=len(filtered_threads),
            new_thread_count=len(
                [thread for thread in threads if thread.change_status == "new"]
            ),
            changed_thread_count=len(
                [thread for thread in threads if thread.change_status == "changed"]
            ),
            threads=threads,
            summary=final_summary,
            errors=errors,
        )

    def _apply_predictions(
        self,
        threads: list[EmailThread],
        triage_items: list[ThreadTriageItem],
        crm_records: list[ThreadCrmRecord],
    ) -> None:
        """Merge AI or fallback outputs back onto the stored thread records."""

        triage_map = {item.thread_id: item for item in triage_items}
        crm_map = {record.thread_id: record for record in crm_records}

        for thread in threads:
            triage_item = triage_map.get(thread.thread_id)
            crm_record = crm_map.get(thread.thread_id)

            if triage_item is not None:
                thread.predicted_category = triage_item.category
                thread.predicted_urgency = triage_item.urgency
                thread.predicted_summary = triage_item.summary
                thread.predicted_status = triage_item.current_status
                thread.predicted_needs_action_today = triage_item.needs_action_today

            if crm_record is not None:
                thread.predicted_next_action = crm_record.next_action
                thread.crm_contact_name = crm_record.contact_name
                thread.crm_company = crm_record.company
                thread.crm_opportunity_type = crm_record.opportunity_type
                thread.crm_urgency = crm_record.urgency

    def _apply_sensitive_predictions(
        self,
        threads: list[EmailThread],
        sensitive_records: list[SensitiveThreadRecord],
    ) -> None:
        """Apply local safe-handling outputs to sensitive threads."""

        sensitive_map = {record.thread_id: record for record in sensitive_records}

        for thread in threads:
            sensitive_record = sensitive_map.get(thread.thread_id)
            if sensitive_record is None:
                continue

            thread.predicted_category = "Classified / Sensitive"
            thread.predicted_urgency = sensitive_record.urgency
            thread.predicted_summary = sensitive_record.summary
            thread.predicted_status = sensitive_record.current_status
            thread.predicted_needs_action_today = sensitive_record.needs_action_today
            thread.predicted_next_action = sensitive_record.next_action
            thread.should_draft_reply = False
            thread.draft_needs_date = False
            thread.draft_date_reason = None
            thread.draft_needs_attachment = False
            thread.draft_attachment_reason = None
            thread.predicted_reply_subject = None
            thread.predicted_reply_body = None
            thread.crm_contact_name = None
            thread.crm_company = None
            thread.crm_opportunity_type = None
            thread.crm_urgency = "unknown"

    def _apply_reply_drafts(
        self,
        threads: list[EmailThread],
        draft_records: list[ThreadReplyDraftRecord],
    ) -> None:
        """Merge reply draft suggestions back onto the stored thread records."""

        draft_map = {record.thread_id: record for record in draft_records}

        for thread in threads:
            draft_record = draft_map.get(thread.thread_id)
            if draft_record is None:
                continue
            thread.should_draft_reply = draft_record.should_draft_reply
            thread.draft_needs_date = bool(draft_record.needs_date)
            thread.draft_date_reason = draft_record.date_reason
            thread.draft_needs_attachment = bool(draft_record.needs_attachment)
            thread.draft_attachment_reason = draft_record.attachment_reason
            thread.predicted_reply_subject = None
            thread.predicted_reply_body = None

    def _fallback_triage(self, thread: AgentThread) -> ThreadTriageItem:
        text = f"{thread.subject} {thread.combined_thread_text}".lower()
        category = "FYI / Low Priority"
        summary = self._short_summary(thread)
        current_status = "Informational thread with no urgent action detected."
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
                thread, "Urgent conversation that needs immediate attention."
            )
            current_status = "Latest messages suggest an urgent or executive issue is still open."
        elif any(
            word in text
            for word in ["customer", "client", "partner", "proposal", "deal", "contract"]
        ):
            category = "Customer / Partner"
            needs_action_today = True
            urgency = "medium"
            summary = self._short_summary(
                thread, "Customer or partner conversation with follow-up value."
            )
            current_status = "The thread is active and likely waiting on a business follow-up."
        elif any(
            word in text
            for word in ["event", "meeting", "schedule", "flight", "hotel", "logistics"]
        ):
            category = "Events / Logistics"
            urgency = "medium"
            summary = self._short_summary(
                thread, "Scheduling or logistics-related conversation."
            )
            current_status = "The thread is coordinating scheduling or logistics details."
        elif any(
            word in text
            for word in ["invoice", "payment", "finance", "admin", "billing", "receipt"]
        ):
            category = "Finance / Admin"
            urgency = "medium"
            needs_action_today = "due" in text or "payment" in text
            summary = self._short_summary(
                thread, "Finance or admin conversation that may need review."
            )
            current_status = "The thread contains finance or administrative details under review."

        return ThreadTriageItem(
            thread_id=thread.thread_id,
            category=category,
            summary=summary,
            current_status=current_status,
            urgency=urgency,
            needs_action_today=needs_action_today,
        )

    def _fallback_summary(self, triage_items: list[ThreadTriageItem]) -> SummaryOutput:
        priorities = [
            f"{item.category} ({item.urgency}): {item.summary}"
            for item in triage_items
            if item.needs_action_today
        ][:5]
        if not priorities:
            priorities = ["No urgent thread-level actions were detected by the fallback summary."]

        next_actions = [
            f"Review {item.category.lower()} thread: {item.summary}"
            for item in triage_items
            if item.needs_action_today
        ][:5]
        action_items = [
            SummaryActionItem(
                thread_id=item.thread_id,
                label=f"Review {item.category.lower()} thread: {item.summary}",
            )
            for item in triage_items
            if item.needs_action_today
        ][:5]

        return SummaryOutput(
            top_priorities=priorities,
            executive_summary=(
                f"Processed {len(triage_items)} thread(s). "
                f"{sum(1 for item in triage_items if item.needs_action_today)} need attention today. "
                "The rest are informational or lower priority."
            ),
            next_actions=next_actions,
            action_items=action_items,
        )

    def _fallback_crm_batch(self, threads: list[AgentThread]) -> ThreadCrmBatch:
        records = [self._fallback_crm(thread) for thread in threads]
        return ThreadCrmBatch(records=records)

    def _fallback_crm(self, thread: AgentThread) -> ThreadCrmRecord:
        latest_message = thread.messages[-1] if thread.messages else None
        sender = latest_message.sender if latest_message else ""
        name = sender.split("<")[0].strip().strip('"') if sender else None
        company = self._extract_company(sender)
        text = f"{thread.subject} {thread.combined_thread_text}".lower()

        opportunity_type = None
        if "renewal" in text:
            opportunity_type = "renewal"
        elif any(word in text for word in ["demo", "proposal", "quote", "deal", "rfq"]):
            opportunity_type = "new_business"

        next_action = None
        if any(word in text for word in ["please", "reply", "follow up", "review"]):
            next_action = "Review the latest thread update and send the next response if needed."

        urgency = "unknown"
        if any(word in text for word in ["urgent", "asap"]):
            urgency = "high"
        elif any(word in text for word in ["invoice", "payment", "renewal", "proposal", "rfq"]):
            urgency = "medium"
        elif text:
            urgency = "low"

        return ThreadCrmRecord(
            thread_id=thread.thread_id,
            contact_name=name or None,
            company=company,
            opportunity_type=opportunity_type,
            next_action=next_action,
            urgency=urgency,
        )

    def _fallback_reply_draft_batch(
        self, threads: list[EmailThread]
    ) -> ThreadReplyDraftBatch:
        return fallback_reply_plan_batch(threads)

    def _fallback_reply_draft(self, thread: EmailThread) -> ThreadReplyDraftRecord:
        return fallback_reply_plan(thread)

    def _short_summary(self, thread: AgentThread, fallback: str | None = None) -> str:
        latest_message = thread.messages[-1] if thread.messages else None
        source = (
            fallback
            or (latest_message.snippet if latest_message else "")
            or thread.subject
            or thread.combined_thread_text
        )
        return " ".join(source.split())[:160]

    def _extract_company(self, sender: str) -> str | None:
        match = re.search(r"@([A-Za-z0-9.-]+)", sender or "")
        if not match:
            return None
        parts = [part for part in match.group(1).split(".") if part]
        company_part = parts[-2] if len(parts) >= 2 else parts[0]
        return company_part.replace("-", " ").title()

    def _should_generate_reply_draft(self, thread: EmailThread) -> bool:
        return fallback_reply_plan(thread).should_draft_reply

    def _extract_first_name(self, value: str) -> str:
        return extract_first_name(value)
