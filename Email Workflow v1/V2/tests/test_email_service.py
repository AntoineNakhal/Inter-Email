"""Tests for conservative thread filtering, scoring, and grouping."""

from __future__ import annotations

from datetime import datetime, timezone
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
        fixed_now = datetime(2026, 4, 13, 9, 0, tzinfo=timezone.utc)
        self.assertEqual(
            GmailReadonlyClient.build_query("anywhere", now=fixed_now),
            "in:anywhere after:2026/04/06",
        )
        self.assertEqual(
            GmailReadonlyClient.build_query("sent", now=fixed_now),
            "in:sent after:2026/04/06",
        )
        self.assertEqual(
            GmailReadonlyClient.build_query("received", now=fixed_now),
            "-in:sent after:2026/04/06",
        )

    def test_gmail_client_paginates_all_recent_results_without_hard_cap(self) -> None:
        client = GmailReadonlyClient(
            credentials_path=Path("data/raw/google_credentials.json"),
            token_path=Path("data/raw/google_token.json"),
        )

        def raw_message(
            message_id: str,
            thread_id: str,
            subject: str,
            date: str,
        ) -> dict[str, object]:
            return {
                "id": message_id,
                "threadId": thread_id,
                "labelIds": [],
                "snippet": f"Snippet for {message_id}",
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": subject},
                        {"name": "From", "value": "sender@example.com"},
                        {"name": "To", "value": "me@example.com"},
                        {"name": "Date", "value": date},
                    ],
                    "body": {},
                },
            }

        class FakeRequest:
            def __init__(self, payload: dict[str, object]) -> None:
                self.payload = payload

            def execute(self) -> dict[str, object]:
                return self.payload

        class FakeMessagesResource:
            def __init__(self) -> None:
                self.page_tokens: list[str | None] = []

            def list(
                self,
                userId: str,
                maxResults: int,
                q: str,
                pageToken: str | None = None,
            ) -> FakeRequest:
                self.page_tokens.append(pageToken)
                if pageToken is None:
                    return FakeRequest(
                        {
                            "messages": [
                                {"id": "ref-1", "threadId": "thread-1"},
                            ],
                            "nextPageToken": "page-2",
                        }
                    )
                return FakeRequest(
                    {
                        "messages": [
                            {"id": "ref-2", "threadId": "thread-2"},
                            {"id": "ref-3", "threadId": "thread-1"},
                        ]
                    }
                )

            def get(self, userId: str, id: str, format: str) -> FakeRequest:
                return FakeRequest(raw_message(id, id, f"Subject {id}", "Mon, 06 Apr 2026 12:00:00 GMT"))

        class FakeThreadsResource:
            def __init__(self) -> None:
                self.requested_thread_ids: list[str] = []

            def get(self, userId: str, id: str, format: str) -> FakeRequest:
                self.requested_thread_ids.append(id)
                return FakeRequest(
                    {
                        "messages": [
                            raw_message(
                                f"{id}-msg",
                                id,
                                f"Subject {id}",
                                "Mon, 06 Apr 2026 12:00:00 GMT",
                            )
                        ]
                    }
                )

        class FakeUsersResource:
            def __init__(self) -> None:
                self.messages_resource = FakeMessagesResource()
                self.threads_resource = FakeThreadsResource()

            def messages(self) -> FakeMessagesResource:
                return self.messages_resource

            def threads(self) -> FakeThreadsResource:
                return self.threads_resource

        class FakeService:
            def __init__(self) -> None:
                self.users_resource = FakeUsersResource()

            def users(self) -> FakeUsersResource:
                return self.users_resource

        fake_service = FakeService()
        client._build_service = lambda: fake_service

        messages = client.list_recent_messages(max_results=1, source="anywhere")

        self.assertEqual(len(messages), 2)
        self.assertEqual(
            fake_service.users_resource.messages_resource.page_tokens,
            [None, "page-2"],
        )
        self.assertEqual(
            fake_service.users_resource.threads_resource.requested_thread_ids,
            ["thread-1", "thread-2"],
        )

    def test_fetch_recent_emails_keeps_older_child_messages_in_recent_threads(self) -> None:
        service = build_service()

        class FakeClient:
            def list_recent_messages(
                self, max_results: int = 10, source: str = "anywhere"
            ) -> list[dict[str, str | list[str]]]:
                return [
                    {
                        "id": "old-1",
                        "thread_id": "thread-recent",
                        "subject": "Recent thread with older history",
                        "from_address": "older@example.com",
                        "to_address": "me@example.com",
                        "date": "Sun, 05 Apr 2026 12:00:00 GMT",
                        "snippet": "Older message",
                        "body_text": "This older child message should stay in the thread.",
                        "label_ids": [],
                    },
                    {
                        "id": "new-1",
                        "thread_id": "thread-recent",
                        "subject": "Recent thread with older history",
                        "from_address": "current@example.com",
                        "to_address": "me@example.com",
                        "date": "Mon, 06 Apr 2026 12:00:00 GMT",
                        "snippet": "Recent message",
                        "body_text": "This recent child message caused the thread to be fetched.",
                        "label_ids": [],
                    },
                ]

        service.client = FakeClient()

        emails = service.fetch_recent_emails(max_results=10)

        self.assertEqual(len(emails), 2)
        self.assertEqual([email.id for email in emails], ["old-1", "new-1"])

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

    def test_sensitive_markers_force_classified_hold_outside_ai(self) -> None:
        service = build_service()
        emails = [
            EmailMessage(
                id="s-1",
                thread_id="thread-sensitive",
                subject="Protected B contract follow-up",
                from_address="PSPC <contracts@gov.example.ca>",
                to_address="me@example.com",
                date="Wed, 08 Apr 2026 12:00:00 GMT",
                snippet="Protected B material attached for review.",
                body_text="This message includes Protected B information.",
                label_ids=[],
            )
        ]

        threads = service.group_messages_by_thread(emails)
        selected = service.select_threads_for_ai(threads)
        thread = threads[0]

        self.assertEqual(thread.security_status, "classified")
        self.assertEqual(thread.predicted_category, None)
        self.assertEqual(thread.analysis_status, "guardrailed")
        self.assertFalse(thread.included_in_ai)
        self.assertEqual(thread.relevance_bucket, "must_review")
        self.assertEqual(thread.relevance_score, 5)
        self.assertIn("Protected B", thread.sensitivity_markers)
        self.assertEqual(thread.ai_decision, "blocked_sensitive")
        self.assertEqual(len(selected), 0)

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
        self.assertEqual(thread.ai_decision, "must_send_to_ai")
        self.assertEqual(len(selected), 1)

    def test_score_two_thread_is_now_auto_analyzed(self) -> None:
        service = build_service()
        emails = [
            EmailMessage(
                id="60",
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
                id="61",
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
        selected = service.select_threads_for_ai(threads)
        thread = threads[0]

        self.assertEqual(thread.relevance_bucket, "maybe")
        self.assertEqual(thread.relevance_score, 2)
        self.assertTrue(thread.included_in_ai)
        self.assertEqual(thread.ai_decision, "good_candidate")
        self.assertEqual(len(selected), 1)

    def test_score_one_noise_thread_stays_out_of_ai(self) -> None:
        service = build_service()
        emails = [
            EmailMessage(
                id="62",
                thread_id="thread-noise",
                subject="Team newsletter",
                from_address="Updates <newsletter@inside.example.com>",
                to_address="Me <me@example.com>",
                date="Wed, 08 Apr 2026 15:00:00 GMT",
                snippet="General updates for this week.",
                body_text="Here are the general internal updates for this week.",
                label_ids=[],
            )
        ]

        threads = service.group_messages_by_thread(emails)
        selected = service.select_threads_for_ai(threads)
        thread = threads[0]

        self.assertFalse(thread.included_in_ai)
        self.assertEqual(thread.analysis_status, "skipped")
        self.assertEqual(thread.ai_decision, "skip")
        self.assertEqual(len(selected), 0)

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
        self.assertEqual(threads[0].merge_confidence, "high")
        self.assertIn("exact_subject_match", threads[0].merge_signals)
        self.assertIn("participant_overlap", threads[0].merge_signals)

    def test_shared_subject_identifier_can_merge_without_exact_subject_match(self) -> None:
        service = build_service()
        emails = [
            EmailMessage(
                id="12",
                thread_id="thread-c",
                subject="Radio Mast RFQ Solicitation No. W8475-265582",
                from_address="Mohammad <mohammad@example.com>",
                to_address="Mehdi <mehdi@vendor.com>",
                date="Wed, 08 Apr 2026 09:00:00 GMT",
                snippet="Initial RFQ message.",
                body_text="Please review the attached RFQ.",
                label_ids=[],
            ),
            EmailMessage(
                id="13",
                thread_id="thread-d",
                subject="[External] Guidance needed on W8475 265582 response",
                from_address="Jim <jim@example.com>",
                to_address="Mehdi <mehdi@vendor.com>",
                date="Wed, 08 Apr 2026 11:00:00 GMT",
                snippet="Can we align on the response?",
                body_text="Forwarding the RFQ context so we can answer consistently.",
                label_ids=[],
            ),
        ]

        threads = service.group_messages_by_thread(emails)

        self.assertEqual(len(threads), 1)
        self.assertEqual(threads[0].message_count, 2)
        self.assertEqual(sorted(threads[0].source_thread_ids), ["thread-c", "thread-d"])
        self.assertEqual(threads[0].grouping_reason, "subject_merge")
        self.assertEqual(threads[0].merge_confidence, "high")
        self.assertIn("shared_subject_identifier", threads[0].merge_signals)

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

    def test_exact_subject_without_anchor_signal_does_not_merge(self) -> None:
        service = build_service()
        emails = [
            EmailMessage(
                id="30-a",
                thread_id="thread-one",
                subject="Quarterly update",
                from_address="Alice <alice@outside-one.com>",
                to_address="Bob <bob@outside-one.com>",
                date="Tue, 07 Apr 2026 10:00:00 GMT",
                snippet="Status update for quarter one.",
                body_text="Sharing a simple quarterly update.",
                label_ids=[],
            ),
            EmailMessage(
                id="30-b",
                thread_id="thread-two",
                subject="Quarterly update",
                from_address="Carol <carol@outside-two.com>",
                to_address="Dan <dan@outside-two.com>",
                date="Wed, 08 Apr 2026 10:00:00 GMT",
                snippet="Status update for quarter two.",
                body_text="Another simple quarterly update.",
                label_ids=[],
            ),
        ]

        threads = service.group_messages_by_thread(emails)

        self.assertEqual(len(threads), 2)

    def test_calendar_interview_threads_do_not_merge_with_business_threads(self) -> None:
        service = build_service()
        emails = [
            EmailMessage(
                id="40-a",
                thread_id="thread-maple",
                subject="Re: Canada working Group 2026 / Ex Maple Resolve 26",
                from_address="Safar, Jim Peter <jp.safar@inter-op.ca>",
                to_address="Greg <greg@example.com>, Mohammad <mohammad@inter-op.ca>",
                date="Fri, 10 Apr 2026 10:00:00 GMT",
                snippet="Please see the Ex Maple Resolve details.",
                body_text="Please keep this close-hold and review the attached exercise details.",
                label_ids=[],
            ),
            EmailMessage(
                id="40-b",
                thread_id="thread-hr",
                subject="Accepted: HR Interview following the first meeting @ Mon Apr 13, 2026 3pm - 3:30pm (EDT) (m.elayoubi@inter-op.ca)",
                from_address="Riad Safar <riad@inter-op.ca>",
                to_address="Mohammad <mohammad@inter-op.ca>",
                date="Fri, 10 Apr 2026 11:00:00 GMT",
                snippet="HR Interview following the first meeting.",
                body_text="Google Calendar acceptance for the HR interview.",
                label_ids=[],
            ),
        ]

        threads = service.group_messages_by_thread(emails)

        self.assertEqual(len(threads), 2)

    def test_shared_year_token_does_not_merge_unrelated_threads(self) -> None:
        service = build_service()
        emails = [
            EmailMessage(
                id="41-a",
                thread_id="thread-ex",
                subject="Canada working Group 2026 / Ex Maple Resolve 26",
                from_address="Safar, Jim Peter <jp.safar@inter-op.ca>",
                to_address="Mohammad <mohammad@inter-op.ca>",
                date="Thu, 09 Apr 2026 10:00:00 GMT",
                snippet="Exercise planning details.",
                body_text="Please review the exercise planning notes for 2026.",
                label_ids=[],
            ),
            EmailMessage(
                id="41-b",
                thread_id="thread-slsa",
                subject="Fwd: SLSA No.: 076 Quarterly report (Q4 - January 1 2026 to March 31 2026)",
                from_address="Safar, Jim Peter <jp.safar@inter-op.ca>",
                to_address="Mohammad <mohammad@inter-op.ca>",
                date="Thu, 09 Apr 2026 11:00:00 GMT",
                snippet="Please send the report when you are back.",
                body_text="Forwarding the quarterly report reminder for action later.",
                label_ids=[],
            ),
        ]

        threads = service.group_messages_by_thread(emails)

        self.assertEqual(len(threads), 2)


if __name__ == "__main__":
    unittest.main()
