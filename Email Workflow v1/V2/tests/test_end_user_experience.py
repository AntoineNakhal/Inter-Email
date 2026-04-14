"""Tests for the end-user queue experience helpers."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.end_user_experience import (  # noqa: E402
    build_dashboard_sections,
    build_priority_sections,
    dashboard_snapshot,
    dashboard_counts,
    display_category,
    next_step_label,
    sort_latest_first,
    trust_signal,
    user_friendly_summary,
    user_priority,
)


class EndUserExperienceTests(unittest.TestCase):
    def test_sensitive_thread_becomes_manual_only(self) -> None:
        record = {
            "security_status": "classified",
            "source_thread_ids": ["thread-1"],
        }

        priority = user_priority(record)
        trust = trust_signal(record)

        self.assertEqual(priority["label"], "Manual only")
        self.assertEqual(trust["label"], "Manual review required")

    def test_waiting_on_us_thread_becomes_today_priority(self) -> None:
        record = {
            "waiting_on_us": True,
            "latest_message_date": "Mon, 13 Apr 2026 10:00:00 GMT",
            "source_thread_ids": ["thread-2"],
        }

        priority = user_priority(record)

        self.assertEqual(priority["label"], "Today")

    def test_low_confidence_merged_thread_gets_grouping_warning(self) -> None:
        record = {
            "source_thread_ids": ["a", "b"],
            "merge_confidence": "low",
            "security_status": "standard",
            "analysis_status": "fresh",
        }

        trust = trust_signal(record)

        self.assertEqual(trust["label"], "Check the grouping")

    def test_next_step_uses_predicted_action_when_present(self) -> None:
        record = {
            "predicted_next_action": "Reply to confirm the meeting time.",
        }

        self.assertEqual(
            next_step_label(record),
            "Reply to confirm the meeting time.",
        )

    def test_display_category_prefers_business_category_and_sensitive_override(self) -> None:
        self.assertEqual(
            display_category({"predicted_category": "Events / Logistics"}),
            "Events / Logistics",
        )
        self.assertEqual(
            display_category({"security_status": "classified", "predicted_category": "Finance / Admin"}),
            "Classified / Sensitive",
        )

    def test_priority_sections_and_counts_match_labels(self) -> None:
        records = [
            {"id": "1", "waiting_on_us": True, "latest_message_date": "Mon, 13 Apr 2026 10:00:00 GMT"},
            {"id": "2", "relevance_bucket": "important", "latest_message_date": "Mon, 13 Apr 2026 09:00:00 GMT"},
            {"id": "3", "change_status": "changed", "latest_message_date": "Sun, 12 Apr 2026 09:00:00 GMT"},
            {"id": "4", "security_status": "classified", "latest_message_date": "Mon, 13 Apr 2026 08:00:00 GMT"},
            {"id": "5", "resolved_or_closed": True, "latest_message_date": "Sat, 11 Apr 2026 09:00:00 GMT"},
        ]

        counts = dashboard_counts(records)
        sections = build_priority_sections(records)

        self.assertEqual(counts["today"], 1)
        self.assertEqual(counts["soon"], 1)
        self.assertEqual(counts["watch"], 1)
        self.assertEqual(counts["manual_only"], 1)
        self.assertEqual(counts["fyi_or_done"], 1)
        self.assertEqual(sections[0]["title"], "Needs attention today")
        self.assertEqual(len(sections[0]["items"]), 1)

    def test_sort_latest_first_uses_latest_message_date(self) -> None:
        records = [
            {"id": "older", "latest_message_date": "Sun, 12 Apr 2026 09:00:00 GMT"},
            {"id": "newest", "latest_message_date": "Mon, 13 Apr 2026 11:00:00 GMT"},
            {"id": "middle", "latest_message_date": "Mon, 13 Apr 2026 10:00:00 GMT"},
        ]

        ordered = sort_latest_first(records)

        self.assertEqual([record["id"] for record in ordered], ["newest", "middle", "older"])

    def test_dashboard_sections_split_daily_work_cleanly(self) -> None:
        records = [
            {"id": "manual", "security_status": "classified", "latest_message_date": "Mon, 13 Apr 2026 12:00:00 GMT"},
            {"id": "today", "waiting_on_us": True, "latest_message_date": "Mon, 13 Apr 2026 11:00:00 GMT"},
            {"id": "new", "change_status": "new", "latest_message_date": "Mon, 13 Apr 2026 10:00:00 GMT"},
            {"id": "changed", "change_status": "changed", "latest_message_date": "Mon, 13 Apr 2026 09:00:00 GMT"},
            {"id": "soon", "relevance_bucket": "important", "latest_message_date": "Mon, 13 Apr 2026 08:00:00 GMT"},
            {"id": "fyi", "latest_message_date": "Mon, 13 Apr 2026 07:00:00 GMT"},
        ]

        sections = build_dashboard_sections(records)
        section_items = {section["title"]: [item["id"] for item in section["items"]] for section in sections}

        self.assertEqual(section_items["Needs attention today"], ["today"])
        self.assertEqual(section_items["New since last run"], ["new"])
        self.assertEqual(section_items["Changed since last run"], ["changed"])
        self.assertEqual(section_items["Sensitive / manual only"], ["manual"])
        self.assertEqual(section_items["Review soon"], ["soon"])
        self.assertEqual(section_items["FYI / done"], ["fyi"])

    def test_dashboard_snapshot_counts_operational_buckets(self) -> None:
        records = [
            {"id": "today", "waiting_on_us": True},
            {"id": "new", "change_status": "new"},
            {"id": "changed", "change_status": "changed"},
            {"id": "manual", "security_status": "classified"},
        ]

        snapshot = dashboard_snapshot(records, seen_records=[{"id": "seen-1"}, {"id": "seen-2"}])

        self.assertEqual(snapshot["today"], 1)
        self.assertEqual(snapshot["new"], 1)
        self.assertEqual(snapshot["changed"], 1)
        self.assertEqual(snapshot["manual_only"], 1)
        self.assertEqual(snapshot["seen"], 2)

    def test_user_friendly_summary_trims_very_long_copy(self) -> None:
        summary = user_friendly_summary(
            {
                "predicted_summary": (
                    "This is a very long summary sentence designed to keep going well past the visual card width "
                    "so that the helper trims it into something cleaner for the dashboard instead of leaving the "
                    "whole paragraph untouched in the queue card for the end user to scan every time."
                )
            }
        )

        self.assertLess(len(summary), 241)


if __name__ == "__main__":
    unittest.main()
