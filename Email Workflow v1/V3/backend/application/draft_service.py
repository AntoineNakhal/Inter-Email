"""Draft generation workflow service."""

from __future__ import annotations

from backend.domain.analysis import DraftReplyRequest
from backend.domain.thread import DraftDocument
from backend.persistence.repositories.draft_repository import DraftRepository
from backend.persistence.repositories.thread_repository import ThreadRepository
from backend.providers.ai.base import AIProviderError
from backend.providers.ai.router import AIProviderRouter


class DraftService:
    """Coordinates provider-backed draft generation."""

    def __init__(
        self,
        provider_router: AIProviderRouter,
        thread_repository: ThreadRepository,
        draft_repository: DraftRepository,
    ) -> None:
        self.provider_router = provider_router
        self.thread_repository = thread_repository
        self.draft_repository = draft_repository

    def generate_draft(
        self,
        external_thread_id: str,
        selected_date: str | None,
        attachment_names: list[str],
        user_instructions: str,
    ) -> DraftDocument:
        thread = self.thread_repository.get_thread(external_thread_id)
        if thread is None:
            raise ValueError(f"Thread `{external_thread_id}` was not found.")

        request = DraftReplyRequest(
            thread=thread,
            selected_date=selected_date,
            attachment_names=attachment_names,
            user_instructions=user_instructions,
        )
        provider = self.provider_router.provider_for_task("draft_reply")
        try:
            draft = provider.draft_reply(request)
        except AIProviderError:
            draft = self.provider_router.fallback_provider().draft_reply(request)
        return self.draft_repository.save(external_thread_id, draft)

    def latest_draft(self, external_thread_id: str) -> DraftDocument | None:
        return self.draft_repository.latest_for_thread(external_thread_id)
