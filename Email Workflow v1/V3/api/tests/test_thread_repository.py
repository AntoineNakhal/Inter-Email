from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from backend.domain.thread import (
    DraftDocument,
    EmailThread,
    ReviewDecision,
    SeenState,
    ThreadAnalysis,
    ThreadMessage,
    TriageCategory,
    UrgencyLevel,
)
from backend.persistence.models import Base
from backend.persistence.models.thread import EmailThreadModel, ThreadMessageModel
from backend.persistence.repositories.thread_repository import ThreadRepository


def _build_thread(
    snippet: str,
    *,
    thread_id: str = "thread-1",
    message_id: str = "message-1",
) -> EmailThread:
    return EmailThread(
        external_thread_id=thread_id,
        subject="Status update",
        participants=["alice@example.com", "bob@example.com"],
        message_count=1,
        latest_message_date=datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc),
        messages=[
            ThreadMessage(
                external_message_id=message_id,
                sender="alice@example.com",
                recipients=["bob@example.com"],
                subject="Status update",
                sent_at=datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc),
                snippet=snippet,
                cleaned_body=f"{snippet} body",
                label_ids=["INBOX"],
            )
        ],
        signature="sig",
    )


def test_upsert_thread_updates_existing_messages_without_duplicates() -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        class_=Session,
    )
    session = session_factory()

    try:
        repository = ThreadRepository(session)
        repository.upsert_thread(_build_thread("first snippet"))
        session.commit()

        updated_thread = repository.upsert_thread(_build_thread("updated snippet"))
        session.commit()

        messages = session.scalars(select(ThreadMessageModel)).all()
        assert len(messages) == 1
        assert messages[0].external_message_id == "message-1"
        assert messages[0].snippet == "updated snippet"
        assert len(updated_thread.messages) == 1
        assert updated_thread.messages[0].snippet == "updated snippet"

        thread_models = session.scalars(select(EmailThreadModel)).all()
        assert len(thread_models) == 1
    finally:
        session.close()
        engine.dispose()


def test_upsert_thread_reuses_existing_message_from_previous_thread_group() -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        class_=Session,
    )
    session = session_factory()

    try:
        repository = ThreadRepository(session)
        repository.upsert_thread(
            _build_thread(
                "first grouping",
                thread_id="thread-a",
                message_id="shared-message",
            )
        )
        session.commit()

        regrouped_thread = repository.upsert_thread(
            _build_thread(
                "regrouped snippet",
                thread_id="thread-b",
                message_id="shared-message",
            )
        )
        session.commit()

        messages = session.scalars(select(ThreadMessageModel)).all()
        assert len(messages) == 1
        assert messages[0].external_message_id == "shared-message"
        assert messages[0].snippet == "regrouped snippet"

        stored_threads = session.scalars(
            select(EmailThreadModel).order_by(EmailThreadModel.external_thread_id)
        ).all()
        assert [thread.external_thread_id for thread in stored_threads] == ["thread-b"]
        assert len(regrouped_thread.messages) == 1
        assert regrouped_thread.messages[0].external_message_id == "shared-message"
    finally:
        session.close()
        engine.dispose()


def test_restore_threads_snapshot_restores_seen_review_and_draft() -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        class_=Session,
    )
    session = session_factory()

    try:
        repository = ThreadRepository(session)
        snapshot_thread = _build_thread(
            "snapshot snippet",
            thread_id="thread-snapshot",
            message_id="message-snapshot",
        )
        snapshot_thread.analysis = ThreadAnalysis(
            category=TriageCategory.CUSTOMER_PARTNER,
            urgency=UrgencyLevel.MEDIUM,
            summary="Snapshot summary",
            current_status="Waiting on us",
            next_action="Reply to the customer.",
        )
        snapshot_thread.seen_state = SeenState(
            seen=True,
            seen_version="version-1",
            seen_at=datetime(2026, 4, 20, 12, 30, tzinfo=timezone.utc),
        )
        snapshot_thread.review = ReviewDecision(
            queue_belongs="yes",
            merge_correct="yes",
            summary_useful="yes",
            next_action_useful="yes",
            draft_useful="yes",
            crm_useful="not_applicable",
            notes="Looks good.",
            improvement_tags=["clear"],
            updated_at=datetime(2026, 4, 20, 12, 31, tzinfo=timezone.utc),
        )
        snapshot_thread.latest_draft = DraftDocument(
            subject="Re: Status update",
            body="Thanks for the update.",
            provider_name="heuristic",
            model_name="deterministic-fallback",
            used_fallback=False,
            created_at=datetime(2026, 4, 20, 12, 32, tzinfo=timezone.utc),
        )

        repository.restore_threads_snapshot([snapshot_thread])
        session.commit()

        restored = repository.get_thread("thread-snapshot")

        assert restored is not None
        assert restored.seen_state is not None and restored.seen_state.seen is True
        assert restored.seen_state.seen_version == "version-1"
        assert restored.review is not None
        assert restored.review.notes == "Looks good."
        assert restored.review.improvement_tags == ["clear"]
        assert restored.latest_draft is not None
        assert restored.latest_draft.subject == "Re: Status update"
        assert restored.analysis is not None
        assert restored.analysis.summary == "Snapshot summary"
    finally:
        session.close()
        engine.dispose()
