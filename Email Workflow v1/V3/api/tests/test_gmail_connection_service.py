"""Regression tests for GmailConnectionService account isolation.

P0 correctness guarantee: switching to a different Gmail mailbox must wipe
all data for the previous account before loading the new one. If this breaks,
one account could see another account's threads.

These tests are pure Python — no DB, no HTTP, no Gmail credentials needed.
"""

from __future__ import annotations

from backend.application.gmail_connection_service import (
    GmailConnectionService,
    GmailConnectionStateStore,
)
from backend.domain.gmail import GmailConnectionStatus
from backend.domain.runtime_settings import RuntimeSettings


# ---------------------------------------------------------------------------
# Stubs — minimal fakes, no mocking framework needed
# ---------------------------------------------------------------------------


class _StubGmailClient:
    """Stand-in for GmailReadonlyClient; _synchronize_mailbox_scope never calls it."""

    def get_connection_status(self, connect_url=None) -> GmailConnectionStatus:
        return GmailConnectionStatus(connected=False)

    def generate_code_verifier(self) -> str:
        return "verifier"

    def build_authorization_url(self, **_kwargs) -> str:
        return "http://auth"


class _TrackingThreadRepository:
    def __init__(self) -> None:
        self.clear_all_count = 0

    def clear_all(self) -> None:
        self.clear_all_count += 1


class _TrackingSyncRepository:
    def __init__(self) -> None:
        self.delete_all_count = 0

    def delete_all(self) -> None:
        self.delete_all_count += 1


class _TrackingProgressStore:
    def __init__(self) -> None:
        self.clear_count = 0

    def clear(self) -> None:
        self.clear_count += 1


class _TrackingRuntimeSettingsService:
    def __init__(self, current_email: str = "") -> None:
        self._current_email = current_email
        self.set_calls: list[str] = []
        self.display_name_calls: list[str] = []
        self.history_ids: list[str] = []
        self.watch_cleared = 0

    def get(self) -> RuntimeSettings:
        return RuntimeSettings(gmail_mailbox_email=self._current_email)

    def set_gmail_mailbox_email(self, email: str) -> None:
        self._current_email = email
        self.set_calls.append(email)

    def set_gmail_mailbox_name(self, gmail_mailbox_name: str) -> None:
        self.display_name_calls.append(gmail_mailbox_name)

    def update_gmail_history_id(self, gmail_history_id: str) -> None:
        self.history_ids.append(gmail_history_id)

    def clear_gmail_watch(self) -> None:
        self.watch_cleared += 1


class _TrackingSession:
    def __init__(self) -> None:
        self.commit_count = 0

    def commit(self) -> None:
        self.commit_count += 1


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_service(
    *,
    current_email: str,
    thread_repo: _TrackingThreadRepository,
    sync_repo: _TrackingSyncRepository,
    progress_store: _TrackingProgressStore,
    settings_service: _TrackingRuntimeSettingsService,
    session: _TrackingSession,
) -> GmailConnectionService:
    return GmailConnectionService(
        gmail_client=_StubGmailClient(),
        state_store=GmailConnectionStateStore(),
        runtime_settings_service=settings_service,
        thread_repository=thread_repo,
        sync_repository=sync_repo,
        progress_store=progress_store,
        session=session,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_switching_mailbox_clears_all_data() -> None:
    """Switching from account A → B must wipe threads, runs, and progress."""
    thread_repo = _TrackingThreadRepository()
    sync_repo = _TrackingSyncRepository()
    progress_store = _TrackingProgressStore()
    settings_service = _TrackingRuntimeSettingsService(current_email="alice@example.com")
    session = _TrackingSession()

    service = _make_service(
        current_email="alice@example.com",
        thread_repo=thread_repo,
        sync_repo=sync_repo,
        progress_store=progress_store,
        settings_service=settings_service,
        session=session,
    )

    service._synchronize_mailbox_scope(
        GmailConnectionStatus(connected=True, email_address="bob@example.com")
    )

    assert thread_repo.clear_all_count == 1, "thread_repository.clear_all() must be called on mailbox switch"
    assert sync_repo.delete_all_count == 1, "sync_repository.delete_all() must be called on mailbox switch"
    assert progress_store.clear_count == 1, "progress_store.clear() must be called on mailbox switch"
    assert "bob@example.com" in settings_service.set_calls, "new mailbox email must be persisted"
    assert session.commit_count == 1, "session must be committed after the switch"


def test_same_mailbox_does_not_wipe_data() -> None:
    """Re-connecting the same account must never trigger a data wipe."""
    thread_repo = _TrackingThreadRepository()
    sync_repo = _TrackingSyncRepository()
    progress_store = _TrackingProgressStore()
    settings_service = _TrackingRuntimeSettingsService(current_email="alice@example.com")
    session = _TrackingSession()

    service = _make_service(
        current_email="alice@example.com",
        thread_repo=thread_repo,
        sync_repo=sync_repo,
        progress_store=progress_store,
        settings_service=settings_service,
        session=session,
    )

    service._synchronize_mailbox_scope(
        GmailConnectionStatus(connected=True, email_address="alice@example.com")
    )

    assert thread_repo.clear_all_count == 0, "same account — threads must NOT be cleared"
    assert sync_repo.delete_all_count == 0, "same account — sync runs must NOT be deleted"
    assert progress_store.clear_count == 0, "same account — progress must NOT be cleared"
    assert settings_service.set_calls == [], "same account — email setting must NOT be re-written"


def test_first_connection_sets_email_without_clearing_data() -> None:
    """When no account was previously connected, data must not be wiped."""
    thread_repo = _TrackingThreadRepository()
    sync_repo = _TrackingSyncRepository()
    progress_store = _TrackingProgressStore()
    settings_service = _TrackingRuntimeSettingsService(current_email="")
    session = _TrackingSession()

    service = _make_service(
        current_email="",
        thread_repo=thread_repo,
        sync_repo=sync_repo,
        progress_store=progress_store,
        settings_service=settings_service,
        session=session,
    )

    service._synchronize_mailbox_scope(
        GmailConnectionStatus(connected=True, email_address="alice@example.com")
    )

    assert thread_repo.clear_all_count == 0, "first connection — no prior data to wipe"
    assert sync_repo.delete_all_count == 0
    assert progress_store.clear_count == 0
    assert "alice@example.com" in settings_service.set_calls, "email must be persisted on first connect"
    assert session.commit_count == 1


def test_disconnected_status_is_a_noop() -> None:
    """A disconnected Gmail status must not trigger any state change."""
    thread_repo = _TrackingThreadRepository()
    settings_service = _TrackingRuntimeSettingsService(current_email="alice@example.com")

    service = GmailConnectionService(
        gmail_client=_StubGmailClient(),
        state_store=GmailConnectionStateStore(),
        runtime_settings_service=settings_service,
        thread_repository=thread_repo,
    )

    service._synchronize_mailbox_scope(
        GmailConnectionStatus(connected=False, email_address=None)
    )

    assert thread_repo.clear_all_count == 0, "disconnected status — must not clear threads"
    assert settings_service.set_calls == [], "disconnected status — must not write email"
