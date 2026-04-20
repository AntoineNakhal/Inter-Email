from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from backend.domain.thread import EmailThread, ThreadMessage
from backend.persistence.models import Base
from backend.persistence.models.thread import ThreadMessageModel
from backend.persistence.repositories.thread_repository import ThreadRepository


def _build_thread(snippet: str) -> EmailThread:
    return EmailThread(
        external_thread_id="thread-1",
        subject="Status update",
        participants=["alice@example.com", "bob@example.com"],
        message_count=1,
        latest_message_date=datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc),
        messages=[
            ThreadMessage(
                external_message_id="message-1",
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
    finally:
        session.close()
        engine.dispose()
