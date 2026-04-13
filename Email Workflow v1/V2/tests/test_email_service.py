"""Tests for conservative thread filtering, scoring, and grouping."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import Settings  # noqa: E402
from gmail_client import GmailReadonlyClient  # noqa: E402
from schemas import EmailMessage  # noqa: E402
from services.email_service import EmailService  # noqa: E402


def build_service(
    ai_max_emails: int = 5,
    auto_send_maybe_threads: bool = False,
) -> EmailService:
    settings = Settings.model_validate(
        {
            "OPENAI_API_KEY": "test-key",
            "OPENAI_MODEL": "gpt-4.1-mini",
            "GMAIL_CREDENTIALS_FILE": "data/raw/google_credentials.json",
            "GMAIL_TOKEN_FILE": "data/raw/google_token.json",
            "GMAIL_THREAD_SOURCE": "anywhere",
            "GMAIL_MAX_RESULTS": "10",
            "AI_MAX_EMAILS": str(ai_max_emails),
            "AI_RELEVANCE_THRESHOLD": "3",
            "AUTO_SEND_MAYBE_THREADS": str(auto_send_maybe_threads).lower(),
            "PROCESSING_MODE": "ai",
            "OUTPUT_FILE": "data/outputs/latest_run.json",
            "THREAD_CACHE_FILE": "data/outputs/thread_cache.json",
        }
    )
    return EmailService(settings)


class EmailServiceTests(unittest.TestCase):
    def test_query_builder_supports_anywhere_sent_and_received(self) -> None:
        self.assertEqual(GmailReadonlyClient.build_query("anywhere"), "in:anywhere")
        self.assertEqual(GmailReadonlyClient.build_query("sent"), "in:sent")
        self.assertEqual(GmailReadonlyClient.build_query("received"), "-in:sent")

    def test_obvious_promotional_thread_is_filtered(self) -> None:
        service = build_service()
        emails = [
            EmailMessage(
                id="1",
                thread_id="thread-1",
                subject="Weekly digest and discount offer",
                from_address="Deals <newsletter@shop.example.com>",
                to_address="me@example.com",
                date="Wed, 08 Apr 2026 12:00:00 GMT",
                snippet="Unsubscribe anytime for more promotions.",
                body_text="Limited time sale and offers.",
                label_ids=[],
            )
        ]
        thread = service.group_messages_by_thread(emails)[0]

        self.assertIsNotNone(service._filter_reason(thread))

    def test_important_thread_is_not_filtered_and_groups_messages(self) -> None:
        service = build_service()
        emails = [
            EmailMessage(
                id="2",
                thread_id="thread-2",
                subject="Security alert",
                from_address="Google <no-reply@accounts.google.com>",
                to_address="me@example.com",
                date="Wed, 08 Apr 2026 12:00:00 GMT",
                snippet="We detected a new sign-in.",
                body_text="Please review your account activity.",
                label_ids=[],
            ),
            EmailMessage(
                id="3",
                thread_id="thread-2",
                subject="Re: Security alert",
                from_address="me@example.com",
                to_address="Google <no-reply@accounts.google.com>",
                date="Wed, 08 Apr 2026 12:10:00 GMT",
                snippet="I reviewed the activity.",
                body_text="I reviewed it and no further action is needed.",
                label_ids=["SENT"],
            ),
        ]
        thread = service.group_messages_by_thread(emails)[0]

        self.assertEqual(thread.message_count, 2)
        self.assertEqual(thread.messages[0].message_id, "2")
        self.assertEqual(thread.messages[1].message_id, "3")
        self.assertIsNone(service._filter_reason(thread))
        self.assertTrue(thread.latest_message_from_me)
        self.assertTrue(thread.resolved_or_closed)
        self.assertFalse(thread.waiting_on_us)
        self.assertLessEqual(service._score_thread(thread), 2)

    def test_inbound_question_sets_waiting_on_us_signal(self) -> None:
        service = build_service()
        emails = [
            EmailMessage(
                id="30",
                thread_id="thread-30",
                subject="Quote follow-up",
                from_address="Vendor <sales@vendor.com>",
                to_address="Me <me@example.com>",
                date="Wed, 08 Apr 2026 12:00:00 GMT",
                snippet="Can you review the revised quote?",
                body_text="Please review the revised quote and confirm today.",
                label_ids=[],
            )
        ]

        thread = service.group_messages_by_thread(emails)[0]

        self.assertFalse(thread.latest_message_from_me)
        self.assertTrue(thread.latest_message_from_external)
        self.assertTrue(thread.latest_message_has_question)
        self.assertTrue(thread.latest_message_has_action_request)
        self.assertTrue(thread.waiting_on_us)
        self.assertFalse(thread.resolved_or_closed)
        self.assertGreaterEqual(service._score_thread(thread), 4)

    def test_resolved_latest_message_reduces_relevance(self) -> None:
        service = build_service()
        emails = [
            EmailMessage(
                id="40",
                thread_id="thread-40",
                subject="Contract update",
                from_address="Partner <legal@partner.com>",
                to_address="Me <me@example.com>",
                date="Wed, 08 Apr 2026 12:00:00 GMT",
                snippet="Can you confirm the final clause?",
                body_text="Please confirm the final clause so we can close this.",
                label_ids=[],
            ),
            EmailMessage(
                id="41",
                thread_id="thread-40",
                subject="Re: Contract update",
                from_address="Me <me@example.com>",
                to_address="Partner <legal@partner.com>",
                date="Wed, 08 Apr 2026 13:00:00 GMT",
                snippet="All set on our side.",
                body_text="All set on our side. No further action is needed.",
                label_ids=["SENT"],
            ),
        ]

        thread = service.group_messages_by_thread(emails)[0]

        self.assertTrue(thread.latest_message_from_me)
        self.assertFalse(thread.latest_message_from_external)
        self.assertFalse(thread.waiting_on_us)
        self.assertTrue(thread.resolved_or_closed)
        self.assertLessEqual(service._score_thread(thread), 2)

    def test_bucketed_selection_marks_must_review_thread(self) -> None:
        service = build_service()
        emails = [
            EmailMessage(
                id="50",
                thread_id="thread-50",
                subject="Customer contract follow-up",
                from_address="Customer <buyer@customer.com>",
                to_address="Me <me@example.com>",
                date="Wed, 08 Apr 2026 15:00:00 GMT",
                snippet="Can you approve the contract update today?",
                body_text="Please review the contract update and confirm today.",
                label_ids=[],
            )
        ]

        threads = service.group_messages_by_thread(emails)
        selected = service.select_threads_for_ai(threads)
        thread = threads[0]

        self.assertEqual(thread.relevance_bucket, "must_review")
        self.assertTrue(thread.included_in_ai)
        self.assertEqual(len(selected), 1)

    def test_maybe_threads_stay_visible_but_are_not_auto_analyzed_by_default(self) -> None:
        service = build_service()
        emails = [
            EmailMessage(
                id="60",
                thread_id="thread-important",
                subject="Contract review update",
                from_address="Me <me@example.com>",
                to_address="Partner <legal@partner.com>",
                date="Wed, 08 Apr 2026 15:00:00 GMT",
                snippet="Sharing our latest contract edits.",
                body_text="Please review the attached contract edits when you can.",
                label_ids=["SENT"],
            ),
            EmailMessage(
                id="61",
                thread_id="thread-maybe",
                subject="Quarterly market notes",
                from_address="Analyst <analyst@research.com>",
                to_address="Me <me@example.com>",
                date="Wed, 08 Apr 2026 14:00:00 GMT",
                snippet="Sharing the latest market notes for your reference.",
                body_text="Attached are the latest market notes and trend highlights.",
                label_ids=[],
            ),
            EmailMessage(
                id="62",
                thread_id="thread-maybe",
                subject="Re: Quarterly market notes",
                from_address="Me <me@example.com>",
                to_address="Analyst <analyst@research.com>",
                date="Wed, 08 Apr 2026 14:10:00 GMT",
                snippet="Thanks for sending this over.",
                body_text="Thanks for sending this over. We will read the notes internally.",
                label_ids=["SENT"],
            ),
        ]

        threads = service.group_messages_by_thread(emails)
        service.select_threads_for_ai(threads)
        by_id = {thread.thread_id: thread for thread in threads}

        self.assertEqual(by_id["thread-important"].relevance_bucket, "important")
        self.assertTrue(by_id["thread-important"].included_in_ai)
        self.assertEqual(by_id["thread-maybe"].relevance_bucket, "maybe")
        self.assertFalse(by_id["thread-maybe"].included_in_ai)

    def test_same_subject_split_threads_can_merge_into_one_conversation(self) -> None:
        service = build_service()
        emails = [
            EmailMessage(
                id="10",
                thread_id="thread-a",
                subject="Radio Mast RFQ Solicitation No. W8475-265582",
                from_address="Mohammad <mohammad@example.com>",
                to_address="Mehdi <mehdi@vendor.com>",
                date="Wed, 08 Apr 2026 09:00:00 GMT",
                snippet="Initial RFQ message.",
                body_text="Please review the attached RFQ.",
                label_ids=[],
            ),
            EmailMessage(
                id="11",
                thread_id="thread-b",
                subject="Fwd: Radio Mast RFQ Solicitation No. W8475-265582",
                from_address="Mohammad <mohammad@example.com>",
                to_address="Jim <jim@example.com>",
                date="Wed, 08 Apr 2026 10:00:00 GMT",
                snippet="Can you advise what to answer?",
                body_text="Forwarding the RFQ so we can align on the reply.",
                label_ids=[],
            ),
        ]

        threads = service.group_messages_by_thread(emails)

        self.assertEqual(len(threads), 1)
        self.assertEqual(threads[0].message_count, 2)
        self.assertEqual(sorted(threads[0].source_thread_ids), ["thread-a", "thread-b"])
        self.assertEqual(threads[0].grouping_reason, "subject_merge")

    def test_repeated_notification_subjects_stay_separate(self) -> None:
        service = build_service()
        emails = [
            EmailMessage(
                id="20",
                thread_id="thread-x",
                subject="Your Weekly HubSpot Recap: Some Wins and What to Try Next",
                from_address="success-agent@hubspot.com",
                to_address="me@example.com",
                date="Tue, 07 Apr 2026 10:00:00 GMT",
                snippet="Week 1 recap.",
                body_text="Week 1 recap body.",
                label_ids=[],
            ),
            EmailMessage(
                id="21",
                thread_id="thread-y",
                subject="Your Weekly HubSpot Recap: Some Wins and What to Try Next",
                from_address="success-agent@hubspot.com",
                to_address="me@example.com",
                date="Tue, 14 Apr 2026 10:00:00 GMT",
                snippet="Week 2 recap.",
                body_text="Week 2 recap body.",
                label_ids=[],
            ),
        ]

        threads = service.group_messages_by_thread(emails)

        self.assertEqual(len(threads), 2)


if __name__ == "__main__":
    unittest.main()
