"""Review persistence helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.thread import ReviewDecision
from backend.persistence.models.review import ReviewDecisionModel
from backend.persistence.models.thread import EmailThreadModel


class ReviewRepository:
    """Repository for saving internal review decisions."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, external_thread_id: str, review: ReviewDecision) -> ReviewDecision:
        thread = self.session.scalar(
            select(EmailThreadModel).where(
                EmailThreadModel.external_thread_id == external_thread_id
            )
        )
        if thread is None:
            raise ValueError(f"Thread `{external_thread_id}` was not found.")

        model = thread.review
        if model is None:
            model = ReviewDecisionModel(thread=thread)
            self.session.add(model)

        model.queue_belongs = review.queue_belongs
        model.merge_correct = review.merge_correct
        model.summary_useful = review.summary_useful
        model.next_action_useful = review.next_action_useful
        model.draft_useful = review.draft_useful
        model.crm_useful = review.crm_useful
        model.notes = review.notes
        model.improvement_tags_json = json.dumps(
            review.improvement_tags,
            ensure_ascii=False,
        )
        model.reviewed_at = datetime.now(timezone.utc)
        self.session.flush()
        return ReviewDecision(
            **review.model_dump(),
            updated_at=model.reviewed_at,
        )
