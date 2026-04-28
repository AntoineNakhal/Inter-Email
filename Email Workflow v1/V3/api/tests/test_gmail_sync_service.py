from datetime import datetime, timezone

from backend.application.gmail_sync_service import GmailSyncService
from backend.domain.runtime_settings import AIMode, RuntimeSettings
from backend.domain.thread import EmailThread, SecurityStatus, ThreadMessage


def _thread(thread_id: str) -> EmailThread:
    return EmailThread(
        external_thread_id=thread_id,
        subject="Status update",
        participants=["alice@example.com"],
        message_count=1,
        latest_message_date=datetime(2026, 4, 22, 12, 0, tzinfo=timezone.utc),
        security_status=SecurityStatus.STANDARD,
        messages=[
            ThreadMessage(
                external_message_id=f"{thread_id}-message",
                sender="alice@example.com",
                recipients=["team@example.com"],
                subject="Status update",
                sent_at=datetime(2026, 4, 22, 12, 0, tzinfo=timezone.utc),
                snippet="hello",
                cleaned_body="hello body",
                label_ids=["INBOX"],
            )
        ],
    )


def test_local_ai_mode_sends_every_fetched_thread_to_ai() -> None:
    service = GmailSyncService(
        session=None,
        runtime_settings=RuntimeSettings(
            ai_mode=AIMode.LOCAL,
            local_ai_force_all_threads=False,
        ),
        gmail_client=None,
        thread_repository=None,
        sync_repository=None,
        analysis_service=None,
        queue_service=None,
        progress_store=None,
    )

    threads = service._apply_runtime_ai_strategy([_thread("thread-1"), _thread("thread-2")])

    assert all(thread.included_in_ai for thread in threads)
    assert all(thread.ai_decision == "local_ai_all_threads" for thread in threads)


class _CommitTrackingSession:
    def __init__(self) -> None:
        self.commit_count = 0

    def commit(self) -> None:
        self.commit_count += 1


class _RecordingProgressStore:
    def update(self, *_args, **_kwargs) -> None:
        return None

    def is_cancel_requested(self, _run_id: int) -> bool:
        return False


class _PassThroughThreadRepository:
    def upsert_thread(self, thread: EmailThread, message_progress_callback=None) -> EmailThread:
        if message_progress_callback is not None:
            message_progress_callback(len(thread.messages), len(thread.messages))
        return thread

    def delete_threads(self, _external_thread_ids: list[str]) -> None:
        return None


def test_persist_threads_commits_after_each_thread() -> None:
    session = _CommitTrackingSession()
    service = GmailSyncService(
        session=session,
        runtime_settings=RuntimeSettings(ai_mode=AIMode.OPENAI),
        gmail_client=None,
        thread_repository=_PassThroughThreadRepository(),
        sync_repository=None,
        analysis_service=None,
        queue_service=None,
        progress_store=_RecordingProgressStore(),
    )

    saved_threads = service._persist_threads_with_progress(
        run_id=1,
        grouped_threads=[_thread("thread-1"), _thread("thread-2")],
        fetched_message_count=2,
    )

    assert len(saved_threads) == 2
    assert session.commit_count == 2
