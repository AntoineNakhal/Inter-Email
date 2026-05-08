"""Ingestion orchestration — extract → chunk → embed → store → metadata.

This is the workhorse the Arq worker calls. It is INTENTIONALLY a single
service, not five chained ones, because the steps share state (the doc
row's status transitions, the rollback semantics on failure) and pulling
them apart would make rollback harder, not simpler.

Failure model:
  * Any step raising → mark the document `failed` with the error message,
    re-raise to the worker for logging.
  * Chunks already inserted before the failure remain attached to the
    failed document. They're invisible to retrieval (status filter), and
    re-ingesting the doc later (`delete_for_document` then re-embed) is
    cheap.
"""

from __future__ import annotations

import logging
import time

from sqlalchemy.orm import Session

from backend.core.config import AppSettings
from backend.knowledge.domain.document import KbDocument, KbIngestionStatus
from backend.knowledge.extractors import extract_text
from backend.knowledge.repositories.chunk_repository import KbChunkRepository
from backend.knowledge.repositories.document_repository import KbDocumentRepository
from backend.knowledge.services.chunker import TokenChunker
from backend.knowledge.services.embedding_service import EmbeddingService
from backend.knowledge.services.metadata_service import (
    MetadataExtractionError,
    MetadataExtractionService,
)


logger = logging.getLogger(__name__)


class IngestionError(RuntimeError):
    """Raised when the ingestion pipeline fails for a document."""


class IngestionService:
    """End-to-end ingestion of one uploaded document."""

    def __init__(
        self,
        *,
        session: Session,
        document_repository: KbDocumentRepository,
        chunk_repository: KbChunkRepository,
        chunker: TokenChunker,
        embedding_service: EmbeddingService,
        metadata_service: MetadataExtractionService,
        settings: AppSettings,
    ) -> None:
        self.session = session
        self.document_repository = document_repository
        self.chunk_repository = chunk_repository
        self.chunker = chunker
        self.embedding_service = embedding_service
        self.metadata_service = metadata_service
        self.settings = settings

    def ingest(
        self,
        *,
        document_id: int,
        content: bytes,
        filename: str,
        file_type: str,
    ) -> KbDocument:
        """Run the full pipeline for a single document.

        The document row must already exist (created by the API in PENDING
        state). On success it ends READY with chunks + metadata; on failure
        it ends FAILED with `error_message` populated.
        """
        started = time.perf_counter()
        try:
            self.document_repository.mark_processing(document_id)
            self.session.commit()

            # 1) Extract — pure function over bytes; raises ExtractionError.
            text = extract_text(content, file_type=file_type, filename=filename)
            if not text.strip():
                raise IngestionError(
                    "Extracted text is empty — nothing to embed."
                )

            # 2) Chunk
            text_chunks = self.chunker.chunk(text)
            if not text_chunks:
                raise IngestionError("Chunker produced 0 chunks from non-empty text.")

            # 3) Embed (one batched API call, surfaces EmbeddingError on failure)
            embeddings = self.embedding_service.embed_many(
                [chunk.content for chunk in text_chunks]
            )
            if len(embeddings) != len(text_chunks):
                raise IngestionError(
                    f"Embedding count mismatch: {len(embeddings)} vectors for "
                    f"{len(text_chunks)} chunks."
                )

            # 4) Persist chunks (clears any prior chunks for this doc first
            # so retries-in-place don't double-up).
            self.chunk_repository.delete_for_document(document_id)
            self.chunk_repository.bulk_insert(
                document_id=document_id,
                chunks=[
                    (chunk.index, chunk.content, chunk.token_count, embeddings[i])
                    for i, chunk in enumerate(text_chunks)
                ],
            )

            # 5) Metadata via Haiku. Treated as best-effort: a failed
            # metadata call should NOT lose the embedded chunks (which are
            # the expensive part). So we catch + log + continue.
            metadata = None
            try:
                metadata = self.metadata_service.extract(
                    filename=filename,
                    full_text=text,
                )
            except MetadataExtractionError as exc:
                logger.warning(
                    "Metadata extraction failed for document %s — "
                    "leaving fields blank. Reason: %s",
                    document_id,
                    exc,
                )

            # 6) Park in AWAITING_REVIEW — user must approve via the modal
            #    before the doc becomes visible to RAG retrieval.
            awaiting = self.document_repository.mark_awaiting_review(
                document_id,
                chunk_count=len(text_chunks),
                metadata=metadata,
            )
            self.session.commit()

            logger.info(
                "Ingested document %s (%s chunks) in %.2fs — awaiting user review",
                document_id,
                len(text_chunks),
                time.perf_counter() - started,
            )
            return awaiting

        except Exception as exc:
            # Any pipeline error → mark failed, commit so the UI can read it,
            # then re-raise for worker logging.
            self.session.rollback()
            try:
                self.document_repository.mark_failed(document_id, str(exc))
                self.session.commit()
            except Exception:  # pragma: no cover — last-ditch logging
                logger.exception(
                    "Failed to mark document %s as failed after error",
                    document_id,
                )
            logger.exception("Ingestion failed for document %s", document_id)
            raise IngestionError(str(exc)) from exc
