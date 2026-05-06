"""Repository for thread user overrides."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.override import ThreadOverride
from backend.domain.thread import RelevanceBucket, TriageCategory, UrgencyLevel
from backend.persistence.models.override import ThreadOverrideModel


class ThreadOverrideRepository:

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, thread_id: int, user_id: int) -> ThreadOverride | None:
        model = self.session.scalar(
            select(ThreadOverrideModel).where(
                ThreadOverrideModel.thread_id == thread_id,
                ThreadOverrideModel.user_id == user_id,
            )
        )
        return self._to_domain(model) if model else None

    def upsert(
        self,
        thread_id: int,
        user_id: int,
        override: ThreadOverride,
    ) -> ThreadOverride:
        model = self.session.scalar(
            select(ThreadOverrideModel).where(
                ThreadOverrideModel.thread_id == thread_id,
                ThreadOverrideModel.user_id == user_id,
            )
        )
        if model is None:
            model = ThreadOverrideModel(thread_id=thread_id, user_id=user_id)
            self.session.add(model)

        model.category = override.category.value if override.category else None
        model.urgency = override.urgency.value if override.urgency else None
        model.needs_action_today = override.needs_action_today
        model.waiting_on_us = override.waiting_on_us
        model.needs_next_action = override.needs_next_action
        model.should_draft_reply = override.should_draft_reply
        model.relevance_bucket = override.relevance_bucket.value if override.relevance_bucket else None
        model.notes = override.notes or ""
        self.session.flush()
        return self._to_domain(model)

    def delete(self, thread_id: int, user_id: int) -> None:
        model = self.session.scalar(
            select(ThreadOverrideModel).where(
                ThreadOverrideModel.thread_id == thread_id,
                ThreadOverrideModel.user_id == user_id,
            )
        )
        if model:
            self.session.delete(model)
            self.session.flush()

    @staticmethod
    def _to_domain(model: ThreadOverrideModel) -> ThreadOverride:
        return ThreadOverride(
            category=TriageCategory(model.category) if model.category else None,
            urgency=UrgencyLevel(model.urgency) if model.urgency else None,
            needs_action_today=model.needs_action_today,
            waiting_on_us=model.waiting_on_us,
            needs_next_action=model.needs_next_action,
            should_draft_reply=model.should_draft_reply,
            relevance_bucket=RelevanceBucket(model.relevance_bucket) if model.relevance_bucket else None,
            notes=model.notes or "",
            overridden_at=model.created_at,
            updated_at=model.updated_at,
        )
