"""Tests for cache-aware manager behavior."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.manager_agent import TriageManager  # noqa: E402
from config import Settings  # noqa: E402
from schemas import DraftGenerationRequest, EmailMessage, SummaryOutput  # noqa: E402
from services.email_service import EmailService  # noqa: E402
from services.draft_workflow import fallback_generate_reply_draft  # noqa: E402
from services.thread_cache import (  # noqa: E402
    build_summary_signature,
    compute_thread_signature,
    default_thread_cache_payload,
    save_cached_summary,
    save_thread_cache,
    upsert_thread_cache_entry,
)


class ManagerCacheTests(unittest.TestCase):
    def test_manager_reuses_cached_thread_analysis_when_thread_is_unchanged(self) -> None:
        temp_root = PROJECT_ROOT / "data" / "outputs" / "test_manager_cache"
        temp_root.mkdir(parents=True, exist_ok=True)
        try:
            cache_path = temp_root / "thread_cache.json"
            output_path = temp_root / "latest_run.json"

            settings = Settings.model_validate(
                {
                    "OPENAI_API_KEY": "test-key",
                    "OPENAI_MODEL": "gpt-4.1-mini",
                    "GMAIL_CREDENTIALS_FILE": "data/raw/google_credentials.json",
                    "GMAIL_TOKEN_FILE": "data/raw/google_token.json",
                    "GMAIL_THREAD_SOURCE": "anywhere",
                    "GMAIL_MAX_RESULTS": "10",
                    "AI_MAX_EMAILS": "5",
                    "AI_RELEVANCE_THRESHOLD": "3",
                    "AUTO_SEND_MAYBE_THREADS": "false",
                    "PROCESSING_MODE": "ai",
                    "OUTPUT_FILE": str(output_path),
                    "THREAD_CACHE_FILE": str(cache_path),
                }
            )
            service = EmailService(settings)
            manager = TriageManager(settings)

            emails = [
                EmailMessage(
                    id="1",
                    thread_id="thread-1",
                    subject="Contract approval needed",
                    from_address="Partner <legal@partner.com>",
                    to_address="Me <me@example.com>",
                    date="Wed, 08 Apr 2026 10:00:00 GMT",
                    snippet="Can you confirm the latest contract language?",
                    body_text="Please review the contract language and confirm today.",
                    label_ids=[],
                )
            ]
            cached_thread = service.group_messages_by_thread(emails)[0]
            cached_thread.relevance_score = service._score_thread(cached_thread)
            cached_thread.relevance_bucket = "must_review"
            cached_thread.thread_signature = compute_thread_signature(cached_thread)
            cached_thread.predicted_category = "Customer / Partner"
            cached_thread.predicted_urgency = "medium"
            cached_thread.predicted_summary = "Partner is waiting for contract confirmation."
            cached_thread.predicted_status = "Waiting on us to confirm the updated contract language."
            cached_thread.predicted_needs_action_today = True
            cached_thread.predicted_next_action = "Review the contract language and reply today."
            cached_thread.should_draft_reply = True
            cached_thread.draft_needs_date = False
            cached_thread.draft_date_reason = None
            cached_thread.draft_needs_attachment = True
            cached_thread.draft_attachment_reason = (
                "The thread suggests contract documents may need to be attached."
            )
            cached_thread.crm_contact_name = "Partner"
            cached_thread.crm_company = "Partner"
            cached_thread.crm_opportunity_type = "new_business"
            cached_thread.crm_urgency = "medium"
            cached_thread.last_analysis_at = "2026-04-09T12:00:00+00:00"

            cache_payload = default_thread_cache_payload()
            upsert_thread_cache_entry(cache_payload, cached_thread, seen_at="2026-04-09T12:00:00+00:00")
            cached_summary = SummaryOutput(
                top_priorities=["Customer / Partner (medium): Partner is waiting for contract confirmation."],
                executive_summary="One important cached thread still needs attention.",
                next_actions=["Review the contract language and reply today."],
            )
            save_cached_summary(
                cache_payload=cache_payload,
                coverage_signature=build_summary_signature([cached_thread]),
                summary=cached_summary,
                cached_at="2026-04-09T12:00:00+00:00",
            )
            save_thread_cache(cache_payload, cache_path)

            current_threads = service.group_messages_by_thread(emails)

            manager.email_service.fetch_recent_threads = MagicMock(return_value=current_threads)
            manager.triage_agent.run = MagicMock(side_effect=AssertionError("triage should not run"))
            manager.crm_agent.run = MagicMock(side_effect=AssertionError("crm should not run"))
            manager.summary_agent.run = MagicMock(side_effect=AssertionError("summary should not run"))

            with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
                result = manager.run()

            self.assertEqual(result.ai_thread_count, 1)
            self.assertEqual(result.fresh_ai_thread_count, 0)
            self.assertEqual(result.cached_ai_thread_count, 1)
            self.assertEqual(result.summary.executive_summary, cached_summary.executive_summary)
            self.assertEqual(result.threads[0].analysis_status, "cached")
            self.assertEqual(result.threads[0].change_status, "unchanged")
            self.assertEqual(
                result.threads[0].predicted_summary,
                "Partner is waiting for contract confirmation.",
            )
            self.assertTrue(result.threads[0].should_draft_reply)
            self.assertTrue(result.threads[0].draft_needs_attachment)
            self.assertEqual(
                result.threads[0].draft_attachment_reason,
                "The thread suggests contract documents may need to be attached.",
            )
        finally:
            for path in [temp_root / "thread_cache.json", temp_root / "latest_run.json"]:
                if path.exists():
                    path.unlink()
            if temp_root.exists():
                temp_root.rmdir()

    def test_fallback_reply_plan_and_generation_work_for_inbound_action_thread(self) -> None:
        settings = Settings.model_validate(
            {
                "OPENAI_API_KEY": "test-key",
                "OPENAI_MODEL": "gpt-4.1-mini",
                "GMAIL_CREDENTIALS_FILE": "data/raw/google_credentials.json",
                "GMAIL_TOKEN_FILE": "data/raw/google_token.json",
                "GMAIL_THREAD_SOURCE": "anywhere",
                "GMAIL_MAX_RESULTS": "10",
                "AI_MAX_EMAILS": "5",
                "AI_RELEVANCE_THRESHOLD": "3",
                "AUTO_SEND_MAYBE_THREADS": "false",
                "PROCESSING_MODE": "fallback",
                "OUTPUT_FILE": "data/outputs/latest_run.json",
                "THREAD_CACHE_FILE": "data/outputs/thread_cache.json",
            }
        )
        service = EmailService(settings)
        manager = TriageManager(settings)

        emails = [
            EmailMessage(
                id="1",
                thread_id="thread-draft",
                subject="Vendor quote follow-up",
                from_address="Vendor <sales@vendor.com>",
                to_address="Me <me@example.com>",
                date="Wed, 08 Apr 2026 10:00:00 GMT",
                snippet="Can you confirm the revised quote today?",
                body_text="Please review the revised quote and confirm today.",
                label_ids=[],
            )
        ]
        thread = service.group_messages_by_thread(emails)[0]
        thread.predicted_summary = "Vendor is waiting for confirmation on the revised quote."
        thread.predicted_next_action = "Review the revised quote and reply today."
        thread.predicted_needs_action_today = True

        draft_record = manager._fallback_reply_draft(thread)

        self.assertTrue(draft_record.should_draft_reply)
        self.assertFalse(draft_record.needs_date)

        generated = fallback_generate_reply_draft(
            thread,
            DraftGenerationRequest(
                thread_id=thread.thread_id,
                user_instructions="Be polite but brief",
            ),
        )
        self.assertEqual(generated.subject, "Re: Vendor quote follow-up")
        self.assertIn("We will get back to you today", generated.body)

    def test_sensitive_thread_is_guardrailed_before_ai_agents_run(self) -> None:
        settings = Settings.model_validate(
            {
                "OPENAI_API_KEY": "test-key",
                "OPENAI_MODEL": "gpt-4.1-mini",
                "GMAIL_CREDENTIALS_FILE": "data/raw/google_credentials.json",
                "GMAIL_TOKEN_FILE": "data/raw/google_token.json",
                "GMAIL_THREAD_SOURCE": "anywhere",
                "GMAIL_MAX_RESULTS": "10",
                "AI_MAX_EMAILS": "5",
                "AI_RELEVANCE_THRESHOLD": "3",
                "AUTO_SEND_MAYBE_THREADS": "false",
                "PROCESSING_MODE": "ai",
                "OUTPUT_FILE": "data/outputs/latest_run.json",
                "THREAD_CACHE_FILE": "data/outputs/thread_cache.json",
            }
        )
        service = EmailService(settings)
        manager = TriageManager(settings)

        emails = [
            EmailMessage(
                id="1",
                thread_id="thread-sensitive",
                subject="TLP Amber incident note",
                from_address="security@gov.example.ca",
                to_address="me@example.com",
                date="Wed, 08 Apr 2026 10:00:00 GMT",
                snippet="TLP Amber distribution only.",
                body_text="This note is marked TLP Amber and should not go through AI.",
                label_ids=[],
            )
        ]
        threads = service.group_messages_by_thread(emails)
        manager.email_service.fetch_recent_threads = MagicMock(return_value=threads)
        manager.triage_agent.run = MagicMock(side_effect=AssertionError("triage should not run"))
        manager.crm_agent.run = MagicMock(side_effect=AssertionError("crm should not run"))
        manager.reply_draft_agent.run = MagicMock(side_effect=AssertionError("reply draft should not run"))
        manager.summary_agent.run = MagicMock(side_effect=AssertionError("summary should not run"))

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
            result = manager.run()

        self.assertEqual(result.ai_thread_count, 0)
        self.assertEqual(result.filtered_thread_count, 1)
        self.assertEqual(result.threads[0].security_status, "classified")
        self.assertEqual(result.threads[0].analysis_status, "guardrailed")
        self.assertEqual(result.threads[0].predicted_category, "Classified / Sensitive")
        self.assertIn("TLP Amber", result.threads[0].sensitivity_markers)
        self.assertIn("held out of AI", result.summary.executive_summary)


if __name__ == "__main__":
    unittest.main()
