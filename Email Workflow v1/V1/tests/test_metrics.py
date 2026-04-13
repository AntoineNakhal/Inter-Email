"""Tests for review metrics and Gmail link helpers."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.metrics import (  # noqa: E402
    build_gmail_links,
    category_confusion,
    common_improvement_tags,
    compute_top_metrics,
    urgency_mismatch_counts,
)


class MetricsTests(unittest.TestCase):
    def test_compute_metrics_and_confusions(self) -> None:
        run_data = {
            "email_count": 3,
            "ai_email_count": 2,
            "filtered_email_count": 1,
            "errors": [{"step": "triage", "used_fallback": True}],
        }
        records = [
            {
                "id": "1",
                "included_in_ai": True,
                "predicted_category": "Finance / Admin",
                "predicted_urgency": "Medium",
            },
            {
                "id": "2",
                "included_in_ai": True,
                "predicted_category": "FYI / Low Priority",
                "predicted_urgency": "Low",
            },
            {
                "id": "3",
                "included_in_ai": False,
                "predicted_category": None,
                "predicted_urgency": None,
            },
        ]
        reviews = {
            "1": {
                "ai_result_correct": "Yes",
                "correct_category": "Finance / Admin",
                "correct_urgency": "Medium",
                "summary_useful": "Yes",
                "improvement_tags": [],
            },
            "2": {
                "ai_result_correct": "No",
                "correct_category": "Customer / Partner",
                "correct_urgency": "High",
                "summary_useful": "Partially",
                "improvement_tags": ["wrong category", "wrong urgency"],
            },
        }

        metrics = compute_top_metrics(run_data, records, reviews)
        self.assertEqual(metrics.total_fetched, 3)
        self.assertEqual(metrics.total_filtered, 1)
        self.assertEqual(metrics.total_sent_to_ai, 2)
        self.assertEqual(metrics.total_fallback_used, 1)
        self.assertEqual(metrics.total_reviewed, 2)
        self.assertEqual(metrics.total_correct, 1)
        self.assertEqual(metrics.total_incorrect, 1)

        confusions = category_confusion(records, reviews)
        self.assertEqual(confusions[0]["count"], 1)
        urgencies = urgency_mismatch_counts(records, reviews)
        self.assertEqual(urgencies[0]["count"], 1)
        tags = common_improvement_tags(reviews)
        self.assertEqual(tags[0]["count"], 1)

    def test_gmail_link_builder(self) -> None:
        open_url, search_url = build_gmail_links(
            {
                "id": "msg_1",
                "thread_id": "thread_1",
                "from_address": "sender@example.com",
                "subject": "Invoice ready",
            }
        )
        self.assertIn("#all/thread_1", open_url or "")
        self.assertIn("#search/", search_url)

        open_url_fallback, _ = build_gmail_links(
            {
                "id": "msg_2",
                "thread_id": "",
                "from_address": "",
                "subject": "",
            }
        )
        self.assertIn("#all/msg_2", open_url_fallback or "")


if __name__ == "__main__":
    unittest.main()

