from backend.domain.thread import InboundEmailMessage
from backend.providers.gmail.mapper import group_messages_by_thread


def _message(
    *,
    message_id: str,
    thread_id: str,
    subject: str,
    from_address: str,
    to_address: str,
    date_header: str,
) -> InboundEmailMessage:
    return InboundEmailMessage(
        external_message_id=message_id,
        external_thread_id=thread_id,
        subject=subject,
        from_address=from_address,
        to_address=to_address,
        date_header=date_header,
        snippet=subject,
        body_text=subject,
        label_ids=["INBOX"],
    )


def test_group_messages_by_thread_merges_related_hr_meeting_threads() -> None:
    threads = group_messages_by_thread(
        [
            _message(
                message_id="1",
                thread_id="thread-a",
                subject=(
                    "Invitation: HR Interview following the first meeting @ "
                    "Mon Apr 13, 2026 3pm - 3:30pm (EDT)"
                ),
                from_address="Mohammad <m.elayoubi@inter-op.ca>",
                to_address="Candidate <candidate@example.com>",
                date_header="Mon, 13 Apr 2026 10:00:00 GMT",
            ),
            _message(
                message_id="2",
                thread_id="thread-b",
                subject=(
                    "Accepted: HR Interview following the first meeting @ "
                    "Mon Apr 13, 2026 3pm - 3:30pm (EDT)"
                ),
                from_address="Candidate <candidate@example.com>",
                to_address="Mohammad <m.elayoubi@inter-op.ca>",
                date_header="Mon, 13 Apr 2026 10:15:00 GMT",
            ),
        ]
    )

    assert len(threads) == 1
    assert threads[0].message_count == 2
    assert sorted(threads[0].source_thread_ids) == ["thread-a", "thread-b"]
    assert threads[0].grouping_reason == "subject_merge"
    assert "exact_subject_match" in threads[0].merge_signals


def test_group_messages_by_thread_keeps_repeated_notifications_separate() -> None:
    threads = group_messages_by_thread(
        [
            _message(
                message_id="10",
                thread_id="thread-x",
                subject="Your Weekly HubSpot Recap: Some Wins and What to Try Next",
                from_address="success-agent@hubspot.com",
                to_address="me@example.com",
                date_header="Tue, 07 Apr 2026 10:00:00 GMT",
            ),
            _message(
                message_id="11",
                thread_id="thread-y",
                subject="Your Weekly HubSpot Recap: Some Wins and What to Try Next",
                from_address="success-agent@hubspot.com",
                to_address="me@example.com",
                date_header="Tue, 14 Apr 2026 10:00:00 GMT",
            ),
        ]
    )

    assert len(threads) == 2
