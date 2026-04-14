"""Tests for persisted end-user seen-thread state."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.end_user_state import (  # noqa: E402
    build_thread_version,
    is_thread_seen,
    load_end_user_state,
    mark_thread_seen,
    save_end_user_state,
)


class EndUserStateTests(unittest.TestCase):
    def test_marked_thread_is_seen_for_same_version(self) -> None:
        state = {"seen_threads": {}}
        record = {
            "id": "thread-1",
            "thread_id": "thread-1",
            "subject": "Weekly update",
            "thread_signature": "abc123",
        }

        mark_thread_seen(state, record, scope="ops@example.com")

        self.assertTrue(is_thread_seen(state, record, scope="ops@example.com"))

    def test_seen_thread_reappears_when_signature_changes(self) -> None:
        state = {"seen_threads": {}}
        original = {
            "id": "thread-1",
            "thread_id": "thread-1",
            "subject": "Weekly update",
            "thread_signature": "abc123",
        }
        changed = {
            "id": "thread-1",
            "thread_id": "thread-1",
            "subject": "Weekly update",
            "thread_signature": "xyz999",
        }

        mark_thread_seen(state, original, scope="ops@example.com")

        self.assertFalse(is_thread_seen(state, changed, scope="ops@example.com"))

    def test_state_round_trip_persists_seen_threads(self) -> None:
        state = {"seen_threads": {}}
        record = {
            "id": "thread-2",
            "thread_id": "thread-2",
            "subject": "Customer follow-up",
            "thread_signature": "sig-2",
        }

        mark_thread_seen(state, record, scope="ops@example.com")

        output_path = PROJECT_ROOT / "data" / "outputs" / "test_end_user_state.json"
        try:
            save_end_user_state(state, output_path)
            loaded = load_end_user_state(output_path)
        finally:
            output_path.unlink(missing_ok=True)

        self.assertTrue(is_thread_seen(loaded, record, scope="ops@example.com"))

    def test_version_falls_back_to_date_and_message_count(self) -> None:
        version = build_thread_version(
            {
                "id": "thread-3",
                "thread_id": "thread-3",
                "latest_message_date": "Mon, 13 Apr 2026 10:00:00 GMT",
                "message_count": 4,
            }
        )

        self.assertEqual(version, "thread-3|Mon, 13 Apr 2026 10:00:00 GMT|4")


if __name__ == "__main__":
    unittest.main()
