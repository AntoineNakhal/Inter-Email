"""Review workflow service."""

from __future__ import annotations

from backend.domain.thread import ReviewDecision
from backend.persistence.repositories.review_repository import ReviewRepository
from backend.persistence.repositories.thread_repository import ThreadRepository


class ReviewService:
    """Owns the thread review workflow."""

    def __init__(
        self,
        review_repository: ReviewRepository,
        thread_repository: ThreadRepository,
    ) -> None:
        self.review_repository = review_repository
        self.thread_repository = thread_repository

    def save_review(self, external_thread_id: str, review: ReviewDecision) -> ReviewDecision:
        return self.review_repository.save(external_thread_id, review)

    def mark_seen(self, external_thread_id: str, seen: bool) -> None:
        thread = self.thread_repository.get_thread(external_thread_id)
        if thread is None:
            raise ValueError(f"Thread `{external_thread_id}` was not found.")
        version = thread.signature or thread.compute_signature()
        self.thread_repository.mark_seen(external_thread_id, seen, version)

    def mark_pinned(self, external_thread_id: str, pinned: bool) -> None:
        thread = self.thread_repository.get_thread(external_thread_id)
        if thread is None:
            raise ValueError(f"Thread `{external_thread_id}` was not found.")
        self.thread_repository.mark_pinned(external_thread_id, pinned)
