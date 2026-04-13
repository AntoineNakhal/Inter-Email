"""Basic smoke tests for project imports and core thread objects."""

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class SmokeTest(unittest.TestCase):
    def test_imports_and_thread_instantiation(self) -> None:
        from agents.manager_agent import TriageManager
        from config import Settings
        from gmail_client import GmailReadonlyClient
        from schemas import AgentThread, EmailMessage
        from services.email_service import EmailService

        settings = Settings.model_validate(
            {
                "OPENAI_API_KEY": "test-key",
                "OPENAI_MODEL": "gpt-5.4-mini",
                "GMAIL_CREDENTIALS_FILE": "data/raw/google_credentials.json",
                "GMAIL_TOKEN_FILE": "data/raw/google_token.json",
                "GMAIL_THREAD_SOURCE": "received",
                "GMAIL_MAX_RESULTS": 9,
                "AI_MAX_EMAILS": 4,
                "AI_RELEVANCE_THRESHOLD": 3,
                "PROCESSING_MODE": "fallback",
                "OUTPUT_FILE": "data/outputs/latest_run.json",
            }
        )

        service = EmailService(settings)
        email_one = EmailMessage(
            id="123",
            thread_id="thread-1",
            subject="Quarterly update",
            from_address="leader@outside.com",
            to_address="team@example.com",
            date="Tue, 08 Apr 2026 09:00:00 -0400",
            snippet="Please review the latest metrics.",
            body_text="Please review the latest metrics and action items.",
            label_ids=[],
        )
        email_two = EmailMessage(
            id="124",
            thread_id="thread-1",
            subject="Re: Quarterly update",
            from_address="team@example.com",
            to_address="leader@outside.com",
            date="Tue, 08 Apr 2026 10:00:00 -0400",
            snippet="We can reply today.",
            body_text="Reply today with the final approval and next steps.",
            label_ids=[],
        )
        promo_email = EmailMessage(
            id="125",
            thread_id="thread-2",
            subject="Weekly digest and discount offer",
            from_address="Deals <newsletter@shop.example.com>",
            to_address="me@example.com",
            date="Tue, 08 Apr 2026 11:00:00 -0400",
            snippet="Unsubscribe anytime for more promotions.",
            body_text="Limited time sale and offers.",
            label_ids=[],
        )

        threads = service.group_messages_by_thread([email_one, email_two, promo_email])
        selected_threads = service.select_threads_for_ai(threads)

        self.assertEqual(TriageManager(settings).settings.openai_model, "gpt-4.1-mini")
        self.assertEqual(TriageManager(settings).settings.processing_mode, "fallback")
        self.assertEqual(TriageManager(settings).settings.gmail_thread_source, "received")
        self.assertEqual(GmailReadonlyClient.build_query("sent"), "in:sent")
        self.assertEqual(len(threads), 2)
        self.assertEqual(threads[0].thread_id, "thread-2")
        self.assertEqual(next(t for t in threads if t.thread_id == "thread-1").message_count, 2)
        self.assertIsInstance(selected_threads[0], AgentThread)
        self.assertTrue(any(not item.included_in_ai for item in threads))


if __name__ == "__main__":
    unittest.main()
