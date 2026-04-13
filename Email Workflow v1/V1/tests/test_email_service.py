"""Tests for conservative email filtering and scoring."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import Settings  # noqa: E402
from schemas import EmailMessage  # noqa: E402
from services.email_service import EmailService  # noqa: E402


def build_service() -> EmailService:
    settings = Settings.model_validate(
        {
            "OPENAI_API_KEY": "test-key",
            "OPENAI_MODEL": "gpt-4.1-mini",
            "GMAIL_CREDENTIALS_FILE": "data/raw/google_credentials.json",
            "GMAIL_TOKEN_FILE": "data/raw/google_token.json",
            "GMAIL_MAX_RESULTS": "10",
            "AI_MAX_EMAILS": "5",
            "AI_RELEVANCE_THRESHOLD": "3",
            "PROCESSING_MODE": "ai",
            "OUTPUT_FILE": "data/outputs/latest_run.json",
        }
    )
    return EmailService(settings)


class EmailServiceTests(unittest.TestCase):
    def test_obvious_promotional_mail_is_filtered(self) -> None:
        service = build_service()
        email = EmailMessage(
            id="1",
            thread_id="1",
            subject="Weekly digest and discount offer",
            from_address="Deals <newsletter@shop.example.com>",
            to_address="me@example.com",
            date="Wed, 08 Apr 2026 12:00:00 GMT",
            snippet="Unsubscribe anytime for more promotions.",
            body_text="Limited time sale and offers.",
            label_ids=["CATEGORY_PROMOTIONS"],
        )

        self.assertIsNotNone(service._filter_reason(email))

    def test_important_account_mail_is_not_filtered(self) -> None:
        service = build_service()
        email = EmailMessage(
            id="2",
            thread_id="2",
            subject="Security alert",
            from_address="Google <no-reply@accounts.google.com>",
            to_address="me@example.com",
            date="Wed, 08 Apr 2026 12:00:00 GMT",
            snippet="We detected a new sign-in.",
            body_text="Please review your account activity.",
            label_ids=["CATEGORY_UPDATES"],
        )

        self.assertIsNone(service._filter_reason(email))
        self.assertGreaterEqual(service._score_email(email), 3)


if __name__ == "__main__":
    unittest.main()
