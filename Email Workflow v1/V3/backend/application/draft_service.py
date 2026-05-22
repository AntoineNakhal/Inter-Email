"""Draft generation workflow service."""

from __future__ import annotations

import logging

from backend.domain.analysis import DraftReplyRequest
from backend.domain.runtime_settings import RuntimeSettings
from backend.domain.thread import DraftDocument, EmailThread, KbDraftSource
from backend.knowledge.domain.chunk import KbChunkMatch
from backend.knowledge.services.retrieval_service import RagRetrievalService
from backend.persistence.repositories.draft_repository import DraftRepository
from backend.persistence.repositories.thread_repository import ThreadRepository
from backend.providers.ai.base import AIProviderError
from backend.providers.ai.router import AIProviderRouter


logger = logging.getLogger(__name__)


class DraftService:
    """Coordinates provider-backed draft generation."""

    def __init__(
        self,
        provider_router: AIProviderRouter,
        thread_repository: ThreadRepository,
        draft_repository: DraftRepository,
        runtime_settings: RuntimeSettings,
        rag_service: RagRetrievalService | None = None,
    ) -> None:
        self.provider_router = provider_router
        self.thread_repository = thread_repository
        self.draft_repository = draft_repository
        self.runtime_settings = runtime_settings
        self.rag_service = rag_service

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

        # Pull the connected mailbox owner so the draft is written FROM
        # that user's perspective. Empty / unset → None → providers skip
        # the user-perspective preamble.
        user_email = self.runtime_settings.gmail_mailbox_email.strip() or None
        # Explicit display name avoids the AI guessing the name from the
        # email address prefix (e.g. "a.nakhal" → wrong first name guess).
        user_name = self.runtime_settings.gmail_mailbox_name.strip() or None

        # Resolve KB matches once and reuse them for both the prompt and
        # the audit trail. Returning ([] , "") when RAG is off keeps the
        # downstream code branch-free.
        kb_matches, kb_context = self._build_kb_context(thread, user_instructions)
        request = DraftReplyRequest(
            thread=thread,
            selected_date=selected_date,
            attachment_names=attachment_names,
            user_instructions=user_instructions,
            user_email=user_email,
            user_name=user_name,
            kb_context=kb_context,
        )
        provider = self.provider_router.provider_for_task("draft_reply")
        try:
            draft = provider.draft_reply(request)
            if not self._has_meaningful_draft(draft):
                raise AIProviderError("Primary provider returned an empty draft.")
        except AIProviderError:
            draft = self.provider_router.fallback_provider().draft_reply(request)
            if not self._has_meaningful_draft(draft):
                raise AIProviderError("Draft generation returned empty content.")
        # Attach the source list AFTER the provider returns. Providers
        # can't fabricate this — it always reflects what we actually
        # retrieved, regardless of what the model claims to have used.
        draft.kb_sources = _matches_to_sources(kb_matches)
        logger.info(
            "RAG: persisting draft for thread %s with %s source(s) "
            "(kb_matches=%s).",
            external_thread_id,
            len(draft.kb_sources),
            len(kb_matches),
        )
        return self.draft_repository.save(external_thread_id, draft)

    def latest_draft(self, external_thread_id: str) -> DraftDocument | None:
        return self.draft_repository.latest_for_thread(external_thread_id)

    @staticmethod
    def _has_meaningful_draft(draft: DraftDocument) -> bool:
        return bool(draft.subject.strip() or draft.body.strip())

    def _build_kb_context(
        self,
        thread: EmailThread,
        user_instructions: str,
    ) -> tuple[list[KbChunkMatch], str]:
        """Look up product context in the KB for this draft.

        Returns BOTH the raw matches (for audit trail / persistence as
        kb_sources on the draft) and the formatted prompt block. Both
        are derived from the same retrieval call so they can never drift.
        """
        if self.rag_service is None:
            logger.info(
                "RAG: skipped for draft on thread %s — rag_service is None "
                "(KB disabled or KB session failed to open).",
                thread.external_thread_id,
            )
            return [], ""
        query_text = "\n\n".join(
            part for part in [
                thread.subject or "",
                thread.combined_thread_text,
                user_instructions or "",
            ] if part
        )
        logger.info(
            "RAG: invoking retrieval for draft on thread %s (query length=%s chars).",
            thread.external_thread_id,
            len(query_text),
        )
        try:
            matches = self.rag_service.retrieve_for_text(query_text)
        except Exception:
            logger.exception(
                "RAG retrieval raised for draft on thread %s — proceeding without context.",
                thread.external_thread_id,
            )
            return [], ""
        logger.info(
            "RAG: retrieval returned %s matches for draft on thread %s.",
            len(matches),
            thread.external_thread_id,
        )
        return matches, self.rag_service.build_context_block(matches)


# ── helpers ────────────────────────────────────────────────────────────
# Module-level so the function is unit-testable without spinning up the
# full DraftService dependency chain.
def _matches_to_sources(matches: list[KbChunkMatch]) -> list[KbDraftSource]:
    """Convert retrieval matches into the audit-trail shape we persist.

    We snapshot the chunk content (truncated) at this moment so the
    "Sources" panel still tells a coherent story even if the user later
    edits or deletes the chunk in the KB.
    """
    sources: list[KbDraftSource] = []
    for match in matches:
        sources.append(
            KbDraftSource(
                document_id=match.chunk.document_id,
                document_title=match.document_title,
                product_name=match.document_product_name,
                chunk_id=match.chunk.id,
                chunk_index=match.chunk.chunk_index,
                similarity=round(match.similarity, 4),
                content_preview=_preview(match.chunk.content, 280),
            )
        )
    return sources


def _preview(text: str, max_chars: int) -> str:
    collapsed = " ".join((text or "").split())
    if len(collapsed) <= max_chars:
        return collapsed
    return collapsed[: max_chars - 1].rstrip() + "…"
