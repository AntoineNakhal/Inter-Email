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
from pathlib import Path

from sqlalchemy.orm import Session

from backend.core.config import AppSettings
from backend.knowledge.domain.document import KbDocument, KbIngestionStatus
from backend.knowledge.extractors import VIDEO_FILE_TYPE, extract_text
from backend.knowledge.models.document import KbDocumentModel
from backend.knowledge.repositories.chunk_repository import KbChunkRepository
from backend.knowledge.repositories.document_repository import KbDocumentRepository
from backend.knowledge.services.chunker import TokenChunker
from backend.knowledge.services.embedding_service import EmbeddingService
from backend.knowledge.services.metadata_service import (
    MetadataExtractionError,
    MetadataExtractionService,
)
from backend.knowledge.video import VideoIngestionError, VideoIngestionExtractor


def build_embedding_input(
    *,
    chunk_content: str,
    doc_title: str = "",
    doc_product_name: str | None = None,
    doc_search_aliases: str = "",
) -> str:
    """Compose the text that's actually sent to the embedding API.

    We prefix every chunk with its parent document's title, product, and
    user-provided aliases. This is the cheapest possible "metadata
    fusion" technique: it makes a chunk retrievable by terms that appear
    *anywhere* in the doc's metadata, even when those terms aren't in
    the chunk's body. The chunk's `content` column stays untouched —
    only the embedding sees the prefix.

    Tradeoff: any change to a doc's title / product / aliases requires
    re-embedding every chunk for that doc. We pay this cost on finalize
    when aliases change. Cost per re-embed: $0.02 / 1M tokens × ~80k
    tokens for a 200-chunk doc = $0.0016 and ~5 s wall time.
    """
    header_parts: list[str] = []
    if doc_title:
        header_parts.append(f"Document: {doc_title}")
    if doc_product_name:
        header_parts.append(f"Product: {doc_product_name}")
    if doc_search_aliases:
        header_parts.append(f"Also known as: {doc_search_aliases}")
    if not header_parts:
        return chunk_content
    return "[" + " | ".join(header_parts) + "]\n\n" + chunk_content


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
        source_path: Path | None = None,
    ) -> KbDocument:
        """Run the full pipeline for a single document.

        For text-based file types (pdf, pptx, ...) we dispatch to the
        registry which takes raw bytes. For video, we dispatch to the
        VideoIngestionExtractor which needs a file on disk (ffmpeg can't
        consume bytes from memory reliably).

        `source_path` is required for video; for text types we'd accept
        either but we use the bytes path because callers already have
        them in memory.
        """
        started = time.perf_counter()
        try:
            # mark_processing also sets progress_step="extracting" — commit
            # immediately so the polling endpoint sees it within ~1.5 s.
            self.document_repository.mark_processing(document_id)
            self.session.commit()

            # 1) Extract — branches on file_type.
            #    - Text types: registry function over bytes
            #    - Video: dedicated pipeline (audio → transcript → frames → OCR)
            if file_type == VIDEO_FILE_TYPE:
                if source_path is None:
                    raise IngestionError(
                        "Video ingestion requires source_path (on-disk file)."
                    )
                video_extractor = VideoIngestionExtractor(self.settings)
                try:
                    video_result = video_extractor.ingest(source_path)
                except VideoIngestionError as exc:
                    raise IngestionError(str(exc)) from exc
                text = video_result.text
                logger.info(
                    "Video pipeline done: %.1fs duration, %s segments, "
                    "%s frames extracted (%s with text).",
                    video_result.duration_seconds,
                    video_result.transcript_segments,
                    video_result.frames_extracted,
                    video_result.frames_with_text,
                )
            else:
                text = extract_text(content, file_type=file_type, filename=filename)
            if not text.strip():
                raise IngestionError(
                    "Extracted text is empty — nothing to embed."
                )

            # 2) Chunk
            self.document_repository.update_progress_step(document_id, "chunking")
            self.session.commit()
            text_chunks = self.chunker.chunk(text)
            if not text_chunks:
                raise IngestionError("Chunker produced 0 chunks from non-empty text.")

            # 3) Embed — but on metadata-enriched text, not raw chunk
            # content. The doc's title and (eventually) search_aliases
            # are baked in so retrieval can find chunks by alternate
            # names. At first ingestion title/product are still empty
            # (Haiku hasn't run yet), so the prefix is mostly the
            # filename — that's OK, finalize() will re-embed once aliases
            # are set.
            self.document_repository.update_progress_step(document_id, "embedding")
            self.session.commit()
            doc_model = self.session.get(KbDocumentModel, document_id)
            doc_title = doc_model.title if doc_model else ""
            doc_product = doc_model.product_name if doc_model else None
            doc_aliases = doc_model.search_aliases if doc_model else ""
            embedding_inputs = [
                build_embedding_input(
                    chunk_content=chunk.content,
                    doc_title=doc_title,
                    doc_product_name=doc_product,
                    doc_search_aliases=doc_aliases,
                )
                for chunk in text_chunks
            ]
            embeddings = self.embedding_service.embed_many(embedding_inputs)
            if len(embeddings) != len(text_chunks):
                raise IngestionError(
                    f"Embedding count mismatch: {len(embeddings)} vectors for "
                    f"{len(text_chunks)} chunks."
                )

            # 4) Persist chunks (clears any prior chunks for this doc first
            # so retries-in-place don't double-up).
            self.document_repository.update_progress_step(document_id, "persisting")
            self.session.commit()
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
            self.document_repository.update_progress_step(document_id, "metadata")
            self.session.commit()
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
