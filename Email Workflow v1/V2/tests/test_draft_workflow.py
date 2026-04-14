"""Tests for the end-user draft workflow helpers."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from schemas import EmailThread, ThreadMessage  # noqa: E402
from services.draft_workflow import (  # noqa: E402
    draft_steps_for_record,
    fallback_reply_plan,
)


class DraftWorkflowTests(unittest.TestCase):
    def test_draft_steps_only_include_needed_optional_steps(self) -> None:
        record = {
            "draft_needs_date": True,
            "draft_needs_attachment": False,
        }

        self.assertEqual(
            draft_steps_for_record(record),
            ["date", "instructions", "preview"],
        )

    def test_fallback_reply_plan_flags_date_and_attachment_context(self) -> None:
        thread = EmailThread(
            thread_id="thread-1",
            subject="Meeting follow-up with attached proposal",
            participants=["Partner <partner@example.com>"],
            message_count=1,
            latest_message_date="Tue, 14 Apr 2026 09:00:00 GMT",
            messages=[
                ThreadMessage(
                    message_id="msg-1",
                    sender="Partner <partner@example.com>",
                    subject="Meeting follow-up with attached proposal",
                    date="Tue, 14 Apr 2026 09:00:00 GMT",
                    snippet="Can we meet next Tuesday? See attached proposal.",
                    cleaned_body="Can we meet next Tuesday? See attached proposal.",
                )
            ],
            combined_thread_text="Can we meet next Tuesday? See attached proposal.",
            latest_message_from_external=True,
            latest_message_has_question=True,
            waiting_on_us=True,
            predicted_category="Events / Logistics",
            predicted_next_action="Reply with availability and send the proposal.",
            predicted_needs_action_today=True,
        )

        plan = fallback_reply_plan(thread)

        self.assertTrue(plan.should_draft_reply)
        self.assertTrue(plan.needs_date)
        self.assertTrue(plan.needs_attachment)
        self.assertIsNotNone(plan.date_reason)
        self.assertIsNotNone(plan.attachment_reason)


if __name__ == "__main__":
    unittest.main()
