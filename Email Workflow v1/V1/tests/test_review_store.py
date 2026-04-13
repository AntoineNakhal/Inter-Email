"""Tests for review result persistence helpers."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.review_store import (  # noqa: E402
    load_review_results,
    save_review_results,
    upsert_review_result,
)


class ReviewStoreTests(unittest.TestCase):
    def test_round_trip_review_store(self) -> None:
        path = PROJECT_ROOT / "data" / "outputs" / "review_results.test.json"
        data: dict[str, dict[str, object]] = {}

        upsert_review_result(
            data,
            "abc123",
            {
                "ai_result_correct": "Yes",
                "correct_category": "Finance / Admin",
                "correct_urgency": "Medium",
                "summary_useful": "Partially",
                "next_action_useful": "No",
                "crm_useful": "Not applicable",
                "should_have_been_filtered": "Yes",
                "notes": "Needs cleaner summary wording.",
                "improvement_tags": ["summary too vague"],
            },
        )
        save_review_results(data, path)
        loaded = load_review_results(path)

        self.assertIn("abc123", loaded)
        self.assertEqual(loaded["abc123"]["ai_result_correct"], "Yes")
        self.assertEqual(loaded["abc123"]["should_have_been_filtered"], "Yes")
        self.assertIn("updated_at", loaded["abc123"])

        if path.exists():
            path.unlink()


if __name__ == "__main__":
    unittest.main()
