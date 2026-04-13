"""Basic smoke tests for project imports and core objects."""

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class SmokeTest(unittest.TestCase):
    def test_imports_and_schema_instantiation(self) -> None:
        from agents.manager_agent import TriageManager
        from config import Settings
        from schemas import AgentEmail, EmailMessage
        from services.email_service import EmailService

        settings = Settings.model_validate(
            {
                "OPENAI_API_KEY": "test-key",
                "OPENAI_MODEL": "gpt-5.4-mini",
                "GMAIL_CREDENTIALS_FILE": "data/raw/google_credentials.json",
                "GMAIL_TOKEN_FILE": "data/raw/google_token.json",
                "GMAIL_MAX_RESULTS": 9,
                "AI_MAX_EMAILS": 4,
                "AI_RELEVANCE_THRESHOLD": 3,
                "PROCESSING_MODE": "fallback",
                "OUTPUT_FILE": "data/outputs/latest_run.json",
            }
        )

        email = EmailMessage(
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

        self.assertEqual(email.subject, "Quarterly update")
        self.assertEqual(TriageManager(settings).settings.openai_model, "gpt-4.1-mini")
        self.assertEqual(TriageManager(settings).settings.processing_mode, "fallback")

        service = EmailService(settings)
        cleaned = service._sanitize_email(
            {
                "id": "abc",
                "thread_id": "thread",
                "subject": "X" * 300,
                "from_address": "sender@example.com",
                "to_address": "to@example.com",
                "date": "today",
                "snippet": "<b>Hello</b>" + ("Y" * 800),
                "body_text": "<html><body>Hi https://example.com " + ("Z" * 2000) + "</body></html>",
                "label_ids": ["CATEGORY_UPDATES"],
            }
        )
        processed, selection = service.select_emails_for_ai(
            [EmailMessage.model_validate(cleaned), email]
        )
        agent_email = processed[0]

        self.assertIsInstance(agent_email, AgentEmail)
        self.assertLessEqual(len(cleaned["subject"]), 200)
        self.assertLessEqual(len(cleaned["snippet"]), 500)
        self.assertLessEqual(len(cleaned["body_text"]), 1000)
        self.assertGreaterEqual(agent_email.relevance_score, 1)
        self.assertTrue(any(not item.included_in_ai for item in selection))


if __name__ == "__main__":
    unittest.main()
