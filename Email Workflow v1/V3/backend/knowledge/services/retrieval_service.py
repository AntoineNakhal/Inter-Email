"""Retrieval-Augmented Generation: query embedding + top-K chunk lookup.

Public API:
    retrieve_for_text(text)        → list[KbChunkMatch]
    build_context_block(matches)   → str (the formatted PRODUCT CONTEXT)

These are intentionally split so callers can decide whether to inject the
block, log raw matches for debugging, or surface them to the UI.
"""

from __future__ import annotations

import logging

from backend.core.config import AppSettings
from backend.knowledge.domain.chunk import KbChunkMatch
from backend.knowledge.repositories.chunk_repository import KbChunkRepository
from backend.knowledge.services.embedding_service import (
    EmbeddingError,
    EmbeddingService,
)


logger = logging.getLogger(__name__)


# Hard cap on how many characters of chunk text we inject into a prompt.
# Even a top-5 retrieval of 400-token chunks can balloon a prompt; this
# stops a runaway corpus from blowing past the model's context window.
_MAX_CONTEXT_CHARS = 8000


class RagRetrievalService:
    """Embeds a query, finds similar chunks, and formats a context block."""

    def __init__(
        self,
        *,
        chunk_repository: KbChunkRepository,
        embedding_service: EmbeddingService,
        settings: AppSettings,
    ) -> None:
        self.chunk_repository = chunk_repository
        self.embedding_service = embedding_service
        self.settings = settings

    def retrieve_for_text(self, text: str) -> list[KbChunkMatch]:
        """Run a similarity search for the given query text.

        Returns [] when:
          * the query is empty/whitespace-only,
          * no chunk crosses the configured similarity threshold, or
          * the embedding API fails (logged + swallowed — RAG is enrichment,
            not a hard dependency, so a transient OpenAI hiccup must not
            block analysis or drafting).
        """
        cleaned = (text or "").strip()
        if not cleaned:
            return []

        try:
            query_embedding = self.embedding_service.embed_one(cleaned)
        except EmbeddingError as exc:
            logger.warning(
                "RAG retrieval skipped — embedding API failed: %s", exc
            )
            return []

        return self.chunk_repository.search_similar(
            query_embedding=query_embedding,
            top_k=self.settings.kb_top_k,
            similarity_threshold=self.settings.kb_similarity_threshold,
        )

    @staticmethod
    def build_context_block(matches: list[KbChunkMatch]) -> str:
        """Format a list of matches as a PRODUCT CONTEXT block for the prompt.

        Returns an empty string when there are no matches, so callers can
        unconditionally concatenate the result.
        """
        if not matches:
            return ""

        lines: list[str] = [
            "PRODUCT CONTEXT (from internal knowledge base — use this to ground "
            "your answer in product-specific facts; cite implicitly without "
            "naming source files):",
        ]
        running_chars = 0
        for index, match in enumerate(matches, start=1):
            doc_label = match.document_product_name or match.document_title
            header = (
                f"  [{index}] {doc_label} (similarity {match.similarity:.2f})"
            )
            body = match.chunk.content.strip()
            block = f"{header}\n{body}"
            running_chars += len(block) + 2  # +2 for the trailing blank line
            if running_chars > _MAX_CONTEXT_CHARS:
                lines.append(
                    "  ... (additional matches omitted — context budget reached)"
                )
                break
            lines.append(block)

        return "\n\n".join(lines).rstrip() + "\n\n"
