"""Draft persistence helpers."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.thread import DraftDocument
from backend.persistence.models.draft import DraftModel
from backend.persistence.models.thread import EmailThreadModel


class DraftRepository:
    """Repository for generated draft responses."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, external_thread_id: str, draft: DraftDocument) -> DraftDocument:
        thread = self.session.scalar(
            select(EmailThreadModel).where(
                EmailThreadModel.external_thread_id == external_thread_id
            )
        )
        if thread is None:
            raise ValueError(f"Thread `{external_thread_id}` was not found.")

        model = DraftModel(
            thread=thread,
            subject=draft.subject,
            body=draft.body,
            provider_name=draft.provider_name,
            model_name=draft.model_name,
            used_fallback=draft.used_fallback,
        )
        self.session.add(model)
        self.session.flush()
        return DraftDocument(
            subject=model.subject,
            body=model.body,
            provider_name=model.provider_name,
            model_name=model.model_name,
            used_fallback=model.used_fallback,
            created_at=model.created_at,
        )

    def latest_for_thread(self, external_thread_id: str) -> DraftDocument | None:
        query = (
            select(DraftModel)
            .join(EmailThreadModel, DraftModel.thread_id == EmailThreadModel.id)
            .where(EmailThreadModel.external_thread_id == external_thread_id)
            .order_by(DraftModel.created_at.desc())
        )
        model = self.session.scalar(query)
        if model is None:
            return None
        return DraftDocument(
            subject=model.subject,
            body=model.body,
            provider_name=model.provider_name,
            model_name=model.model_name,
            used_fallback=model.used_fallback,
            created_at=model.created_at,
        )
