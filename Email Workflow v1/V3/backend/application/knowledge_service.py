"""Knowledge Base application service — facade for routers + worker.

This is what the FastAPI router talks to. It hides the fact that the KB
runs on its own database (separate engine, separate session) and exposes
plain CRUD-flavoured methods.

The session lifecycle is per-call: each method opens a fresh KB session,
commits or rolls back, then closes. We do NOT reuse the main app's
`Depends(get_db_session)` here because that session is bound to the main
DB engine.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from backend.core.config import AppSettings
from backend.knowledge.database import (
    KnowledgeBaseDisabledError,
    get_kb_session_factory,
    is_kb_enabled,
)
from backend.knowledge.domain.chunk import KbChunk
from backend.knowledge.domain.document import (
    KbDocument,
    KbDocumentMetadata,
    KbIngestionStatus,
)
from backend.knowledge.extractors import (
    SUPPORTED_FILE_TYPES,
    file_type_for_filename,
)
from backend.knowledge.repositories.chunk_repository import KbChunkRepository
from backend.knowledge.repositories.document_repository import KbDocumentRepository
from backend.knowledge.services.chunker import TokenChunker
from backend.knowledge.services.embedding_service import (
    EmbeddingError,
    EmbeddingService,
)


logger = logging.getLogger(__name__)


class KnowledgeServiceError(RuntimeError):
    """Validation / business-rule failure exposed to the API as 400."""


class KnowledgeService:
    """Facade over the KB persistence + ingestion pipeline."""

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    # ── public API ────────────────────────────────────────────────────────
    def list_documents(self) -> list[KbDocument]:
        self._require_enabled()
        with self._kb_session() as session:
            return KbDocumentRepository(session).list_all()

    def get_document(self, document_id: int) -> KbDocument | None:
        self._require_enabled()
        with self._kb_session() as session:
            return KbDocumentRepository(session).get(document_id)

    def list_chunks(self, document_id: int) -> list[KbChunk]:
        """Return every chunk for a document, ordered by index.

        Used by the review modal's chunk explorer. Embedding vectors are
        excluded by the repository so we don't ship 1.4 MB of floats per
        document just to show the text.
        """
        self._require_enabled()
        with self._kb_session() as session:
            return KbChunkRepository(session).list_for_document(document_id)

    def update_chunk(
        self,
        document_id: int,
        chunk_id: int,
        *,
        content: str,
    ) -> KbChunk:
        """Rewrite a chunk's text. The embedding is recomputed automatically.

        Invariant: text and embedding stay in sync. We never persist new
        text without also persisting the matching embedding, otherwise
        retrieval would silently return wrong-but-confidently-ranked hits.

        Cost: one OpenAI embeddings API call per save (~$0.000008 for a
        ~400-token chunk). Latency ~200-500 ms.
        """
        self._require_enabled()

        cleaned = (content or "").strip()
        if not cleaned:
            raise KnowledgeServiceError("Chunk content cannot be empty.")

        # Token count using the same encoder as ingestion so the displayed
        # number matches what the embedding actually saw.
        chunker = TokenChunker()
        token_count = len(chunker._encoder().encode(cleaned))

        # Re-embed via the same service / model used during initial ingestion.
        try:
            embedding = EmbeddingService(self.settings).embed_one(cleaned)
        except EmbeddingError as exc:
            raise KnowledgeServiceError(
                f"Failed to re-embed chunk: {exc}"
            ) from exc

        with self._kb_session() as session:
            chunk_repo = KbChunkRepository(session)
            chunk_model = chunk_repo.get(chunk_id)
            if chunk_model is None:
                raise KnowledgeServiceError(
                    f"Chunk `{chunk_id}` was not found."
                )
            if chunk_model.document_id != document_id:
                # Defense in depth — the route already binds doc_id, but
                # we don't trust path params alone.
                raise KnowledgeServiceError(
                    f"Chunk `{chunk_id}` does not belong to document "
                    f"`{document_id}`."
                )
            updated = chunk_repo.update_content(
                chunk_id,
                content=cleaned,
                token_count=token_count,
                embedding=embedding,
            )
            session.commit()
            return updated

    def delete_chunk(self, document_id: int, chunk_id: int) -> bool:
        """Drop one chunk. Decrements the document's chunk_count so the
        list view stays accurate without needing a separate recount query."""
        self._require_enabled()
        with self._kb_session() as session:
            chunk_repo = KbChunkRepository(session)
            doc_repo = KbDocumentRepository(session)
            chunk_model = chunk_repo.get(chunk_id)
            if chunk_model is None:
                return False
            if chunk_model.document_id != document_id:
                raise KnowledgeServiceError(
                    f"Chunk `{chunk_id}` does not belong to document "
                    f"`{document_id}`."
                )
            deleted = chunk_repo.delete(chunk_id)
            if deleted:
                doc_repo.adjust_chunk_count(document_id, -1)
                session.commit()
            return deleted

    def create_pending_document(
        self,
        *,
        filename: str,
        content: bytes,
    ) -> KbDocument:
        """Validate the file, write a PENDING row, return its ID.

        The actual ingestion (chunk + embed + metadata) is deliberately
        NOT done here — that's the worker's job. Splitting the two means
        the HTTP request returns in <1s even for 50-page PDFs.
        """
        self._require_enabled()

        if not filename:
            raise KnowledgeServiceError("Filename is required.")
        if not content:
            raise KnowledgeServiceError("Uploaded file is empty.")
        if len(content) > self.settings.kb_max_upload_bytes:
            raise KnowledgeServiceError(
                f"File exceeds the {self.settings.kb_max_upload_bytes}-byte upload limit."
            )

        file_type = file_type_for_filename(filename)
        if file_type is None:
            raise KnowledgeServiceError(
                f"Unsupported file type for '{filename}'. "
                f"Supported types: {', '.join(SUPPORTED_FILE_TYPES)}."
            )

        with self._kb_session() as session:
            document = KbDocumentRepository(session).create_pending(
                filename=filename,
                file_type=file_type,
                size_bytes=len(content),
            )
            session.commit()
            return document

    def finalize_document(
        self,
        document_id: int,
        *,
        metadata: KbDocumentMetadata,
    ) -> KbDocument:
        """User-approved review → flip the doc to READY.

        Refuses to finalize a doc that's still mid-pipeline (PENDING /
        PROCESSING) — the user can only approve metadata that's actually
        been extracted. FAILED docs likewise can't be finalized; the user
        should re-upload instead.
        """
        self._require_enabled()
        with self._kb_session() as session:
            repo = KbDocumentRepository(session)
            current = repo.get(document_id)
            if current is None:
                raise KnowledgeServiceError(
                    f"Document `{document_id}` was not found."
                )
            if current.status not in (
                KbIngestionStatus.AWAITING_REVIEW,
                KbIngestionStatus.READY,
            ):
                raise KnowledgeServiceError(
                    f"Document `{document_id}` cannot be finalized while in "
                    f"status {current.status.value!r}."
                )
            updated = repo.finalize(document_id, metadata=metadata)
            session.commit()
            return updated

    def delete_document(self, document_id: int) -> bool:
        self._require_enabled()
        with self._kb_session() as session:
            deleted = KbDocumentRepository(session).delete(document_id)
            if deleted:
                session.commit()
            return deleted

    # ── helpers ───────────────────────────────────────────────────────────
    def _require_enabled(self) -> None:
        if not is_kb_enabled(self.settings):
            raise KnowledgeBaseDisabledError(
                "Knowledge Base is disabled — set KB_DATABASE_URL to enable."
            )

    @contextmanager
    def _kb_session(self) -> Iterator:
        """Open a KB session, ensure it's closed even on error."""
        session = get_kb_session_factory()()
        try:
            yield session
        finally:
            session.close()
