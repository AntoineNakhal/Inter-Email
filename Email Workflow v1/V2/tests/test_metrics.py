"""Tests for review metrics and Gmail link helpers."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.metrics import (  # noqa: E402
    apply_record_filters,
    build_failure_patterns,
    build_gmail_links,
    category_confusion,
    common_improvement_tags,
    compute_top_metrics,
    sort_records,
    urgency_mismatch_counts,
)


class MetricsTests(unittest.TestCase):
    def test_compute_metrics_and_confusions(self) -> None:
        run_data = {
            "thread_count": 3,
            "message_count": 7,
            "ai_thread_count": 2,
            "fresh_ai_thread_count": 1,
            "cached_ai_thread_count": 1,
            "filtered_thread_count": 1,
            "new_thread_count": 1,
            "changed_thread_count": 1,
            "errors": [{"step": "triage", "used_fallback": True}],
        }
        records = [
            {
                "id": "thread-1",
                "message_count": 3,
                "included_in_ai": True,
                "analysis_status": "fresh",
                "change_status": "new",
                "source_thread_ids": ["thread-1", "thread-1b"],
                "predicted_category": "Finance / Admin",
                "predicted_urgency": "Medium",
            },
            {
                "id": "thread-2",
                "message_count": 2,
                "included_in_ai": True,
                "analysis_status": "cached",
                "change_status": "unchanged",
                "source_thread_ids": ["thread-2"],
                "predicted_category": "FYI / Low Priority",
                "predicted_urgency": "Low",
            },
            {
                "id": "thread-3",
                "message_count": 2,
                "included_in_ai": False,
                "analysis_status": "not_requested",
                "change_status": "changed",
                "source_thread_ids": ["thread-3"],
                "predicted_category": None,
                "predicted_urgency": None,
            },
        ]
        reviews = {
            "thread-1": {
                "ai_result_correct": "Yes",
                "merge_correct": "No",
                "correct_category": "Finance / Admin",
                "correct_urgency": "Medium",
                "summary_useful": "Yes",
                "improvement_tags": [],
                "should_have_been_filtered": "Yes",
            },
            "thread-2": {
                "ai_result_correct": "No",
                "merge_correct": "N/A",
                "correct_category": "Customer / Partner",
                "correct_urgency": "High",
                "summary_useful": "Partially",
                "improvement_tags": ["wrong category", "wrong urgency"],
                "should_have_been_filtered": "N/A",
            },
            "thread-3": {
                "ai_result_correct": "Partially",
                "merge_correct": "N/A",
                "correct_category": None,
                "correct_urgency": None,
                "summary_useful": "No",
                "improvement_tags": ["AI should have covered this"],
                "should_have_been_filtered": "No",
            },
        }

        metrics = compute_top_metrics(run_data, records, reviews)
        self.assertEqual(metrics.total_fetched, 3)
        self.assertEqual(metrics.total_messages, 7)
        self.assertEqual(metrics.total_not_auto_analyzed, 1)
        self.assertEqual(metrics.total_ai_covered, 2)
        self.assertEqual(metrics.total_fresh_analysis, 1)
        self.assertEqual(metrics.total_cached_reused, 1)
        self.assertEqual(metrics.total_new_threads, 1)
        self.assertEqual(metrics.total_changed_threads, 1)
        self.assertEqual(metrics.total_fallback_used, 1)
        self.assertEqual(metrics.total_reviewed, 3)
        self.assertEqual(metrics.total_correct, 1)
        self.assertEqual(metrics.total_incorrect, 1)
        self.assertEqual(metrics.total_partial, 1)
        self.assertEqual(metrics.reviewed_merged_threads, 1)
        self.assertEqual(metrics.incorrect_merge_count, 1)
        self.assertEqual(metrics.ai_overreach_count, 1)
        self.assertEqual(metrics.ai_underreach_count, 1)

        confusions = category_confusion(records, reviews)
        self.assertEqual(confusions[0]["count"], 1)
        urgencies = urgency_mismatch_counts(records, reviews)
        self.assertEqual(urgencies[0]["count"], 1)
        tags = common_improvement_tags(reviews)
        self.assertEqual(tags[0]["count"], 1)

        patterns = build_failure_patterns(records, reviews)
        self.assertTrue(any("merged thread" in pattern for pattern in patterns))

    def test_gmail_link_builder(self) -> None:
        open_url, search_url = build_gmail_links(
            {
                "thread_id": "thread_1",
                "participants": ["sender@example.com", "me@example.com"],
                "subject": "Invoice ready",
            }
        )
        self.assertIn("#all/thread_1", open_url or "")
        self.assertIn("#search/", search_url)

        open_url_fallback, _ = build_gmail_links(
            {
                "message_id": "msg_2",
                "thread_id": "",
                "sender": "",
                "subject": "",
            }
        )
        self.assertIn("#all/msg_2", open_url_fallback or "")

    def test_analysis_filter_options_match_analysis_flags(self) -> None:
        records = [
            {"id": "thread-1", "included_in_ai": True, "analysis_status": "fresh", "ai_decision": "must_send_to_ai"},
            {"id": "thread-2", "included_in_ai": True, "analysis_status": "cached", "ai_decision": "good_candidate"},
            {"id": "thread-3", "included_in_ai": False, "analysis_status": "not_requested", "ai_decision": "maybe"},
        ]
        reviews: dict[str, dict[str, str]] = {}

        cached_threads = apply_record_filters(
            unified_records=records,
            reviews_by_message_id=reviews,
            review_state="All threads",
            ai_filter_state="Only cached",
            category_filter="All",
            urgency_filter="All",
            tag_filter="All",
        )
        ai_covered = apply_record_filters(
            unified_records=records,
            reviews_by_message_id=reviews,
            review_state="All threads",
            ai_filter_state="Only AI-covered",
            category_filter="All",
            urgency_filter="All",
            tag_filter="All",
        )
        maybe_threads = apply_record_filters(
            unified_records=records,
            reviews_by_message_id=reviews,
            review_state="All threads",
            ai_filter_state="All threads",
            category_filter="All",
            urgency_filter="All",
            tag_filter="All",
            ai_decision_filter="maybe",
        )

        self.assertEqual([item["id"] for item in cached_threads], ["thread-2"])
        self.assertEqual([item["id"] for item in ai_covered], ["thread-1", "thread-2"])
        self.assertEqual([item["id"] for item in maybe_threads], ["thread-3"])

    def test_sort_records_latest_first(self) -> None:
        records = [
            {
                "id": "thread-1",
                "latest_message_date": "Mon, 06 Apr 2026 10:00:00 GMT",
                "relevance_score": 2,
            },
            {
                "id": "thread-2",
                "latest_message_date": "Tue, 07 Apr 2026 10:00:00 GMT",
                "relevance_score": 1,
            },
            {
                "id": "thread-3",
                "latest_message_date": "Sun, 05 Apr 2026 10:00:00 GMT",
                "relevance_score": 5,
            },
        ]

        sorted_records = sort_records(records, "Latest first")

        self.assertEqual([item["id"] for item in sorted_records], ["thread-2", "thread-1", "thread-3"])

    def test_sort_records_priority_first(self) -> None:
        records = [
            {
                "id": "thread-1",
                "latest_message_date": "Mon, 06 Apr 2026 10:00:00 GMT",
                "relevance_bucket": "maybe",
                "predicted_needs_action_today": False,
                "predicted_urgency": "Low",
                "relevance_score": 5,
            },
            {
                "id": "thread-2",
                "latest_message_date": "Tue, 07 Apr 2026 10:00:00 GMT",
                "relevance_bucket": "important",
                "predicted_needs_action_today": False,
                "predicted_urgency": "Medium",
                "relevance_score": 3,
            },
            {
                "id": "thread-3",
                "latest_message_date": "Wed, 08 Apr 2026 10:00:00 GMT",
                "relevance_bucket": "must_review",
                "predicted_needs_action_today": True,
                "predicted_urgency": "High",
                "relevance_score": 2,
            },
        ]

        sorted_records = sort_records(records, "Priority first")

        self.assertEqual([item["id"] for item in sorted_records], ["thread-3", "thread-2", "thread-1"])

    def test_security_filter_can_show_only_classified_threads(self) -> None:
        records = [
            {"id": "thread-1", "security_status": "classified"},
            {"id": "thread-2", "security_status": "standard"},
        ]
        reviews: dict[str, dict[str, str]] = {}

        classified_only = apply_record_filters(
            unified_records=records,
            reviews_by_message_id=reviews,
            review_state="All threads",
            ai_filter_state="All threads",
            category_filter="All",
            urgency_filter="All",
            tag_filter="All",
            security_filter="Only classified / sensitive",
        )

        self.assertEqual([item["id"] for item in classified_only], ["thread-1"])


if __name__ == "__main__":
    unittest.main()
