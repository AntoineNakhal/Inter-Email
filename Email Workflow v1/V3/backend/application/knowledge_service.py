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
from pathlib import Path
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
    VIDEO_FILE_TYPE,
    file_type_for_filename,
)
from backend.knowledge.repositories.chunk_repository import KbChunkRepository
from backend.knowledge.repositories.document_repository import KbDocumentRepository
from backend.knowledge.services.chunker import TokenChunker
from backend.knowledge.services.embedding_service import (
    EmbeddingError,
    EmbeddingService,
)
from backend.knowledge.services.ingestion_service import build_embedding_input


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

    def create_pending_document_from_path(
        self,
        *,
        filename: str,
        file_path: Path,
        source_url: str | None = None,
    ) -> KbDocument:
        """Streaming-friendly variant — the file is already on disk.

        Used by the upload route to skip the in-memory buffer step that
        used to OOM on 1 GB+ video uploads. We get the size from the
        filesystem rather than from `len(bytes)`, and we never read the
        file contents here — that's the worker's job.

        The caller is responsible for placing the file at its final
        staging path; we just validate type, size, and write the row.
        """
        self._require_enabled()

        if not filename:
            raise KnowledgeServiceError("Filename is required.")
        if not file_path.exists():
            raise KnowledgeServiceError(f"Staged file is missing: {file_path}")

        size_bytes = file_path.stat().st_size
        if size_bytes <= 0:
            raise KnowledgeServiceError("Uploaded file is empty.")

        file_type = file_type_for_filename(filename)
        if file_type is None:
            raise KnowledgeServiceError(
                f"Unsupported file type for '{filename}'. "
                f"Supported types: {', '.join(SUPPORTED_FILE_TYPES)}."
            )

        max_bytes = (
            self.settings.kb_video_max_upload_bytes
            if file_type == VIDEO_FILE_TYPE
            else self.settings.kb_max_upload_bytes
        )
        if size_bytes > max_bytes:
            raise KnowledgeServiceError(
                f"File exceeds the {max_bytes}-byte upload limit for "
                f"{file_type} files."
            )

        with self._kb_session() as session:
            document = KbDocumentRepository(session).create_pending(
                filename=filename,
                file_type=file_type,
                size_bytes=size_bytes,
                source_url=source_url,
            )
            session.commit()
            return document

    def create_pending_document(
        self,
        *,
        filename: str,
        content: bytes,
        source_url: str | None = None,
    ) -> KbDocument:
        """Validate the file, write a PENDING row, return its ID.

        Two size ceilings apply depending on file type:
          * Video files: `kb_video_max_upload_bytes` (default 500 MB).
          * Text-based files: `kb_max_upload_bytes` (default 100 MB).

        The actual ingestion (chunk + embed + metadata, or video pipeline
        for videos) is deliberately NOT done here — that's the worker's
        job. Splitting the two means the HTTP request returns quickly.
        """
        self._require_enabled()

        if not filename:
            raise KnowledgeServiceError("Filename is required.")
        if not content:
            raise KnowledgeServiceError("Uploaded file is empty.")

        file_type = file_type_for_filename(filename)
        if file_type is None:
            raise KnowledgeServiceError(
                f"Unsupported file type for '{filename}'. "
                f"Supported types: {', '.join(SUPPORTED_FILE_TYPES)}."
            )

        # Pick the right ceiling for this file type.
        max_bytes = (
            self.settings.kb_video_max_upload_bytes
            if file_type == VIDEO_FILE_TYPE
            else self.settings.kb_max_upload_bytes
        )
        if len(content) > max_bytes:
            raise KnowledgeServiceError(
                f"File exceeds the {max_bytes}-byte upload limit for "
                f"{file_type} files."
            )

        with self._kb_session() as session:
            document = KbDocumentRepository(session).create_pending(
                filename=filename,
                file_type=file_type,
                size_bytes=len(content),
                source_url=source_url,
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

        If the user's edit changes `search_aliases`, we re-embed every
        chunk of this document so the new aliases take effect at
        retrieval time. The chunks' textual content is untouched — only
        the embedding vectors are recomputed.
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
            updated, aliases_changed = repo.finalize(
                document_id, metadata=metadata
            )
            session.commit()
            if aliases_changed:
                self._reembed_document_chunks(updated)
            return updated

    def _reembed_document_chunks(self, document: KbDocument) -> None:
        """Recompute every chunk's embedding using the current doc
        metadata (title / product / aliases).

        Called from finalize_document only when aliases actually
        changed — otherwise it's wasted API cost. One bulk embedding
        call covers the whole doc; cost scales linearly with chunk
        count but is dominated by API latency, not money.
        """
        logger.info(
            "Re-embedding chunks for document %s after alias change.",
            document.id,
        )
        embedding_service = EmbeddingService(self.settings)
        with self._kb_session() as session:
            chunk_repo = KbChunkRepository(session)
            chunks = chunk_repo.list_for_document(document.id)
            if not chunks:
                return
            inputs = [
                build_embedding_input(
                    chunk_content=chunk.content,
                    doc_title=document.title,
                    doc_product_name=document.product_name,
                    doc_search_aliases=document.search_aliases,
                )
                for chunk in chunks
            ]
            try:
                new_embeddings = embedding_service.embed_many(inputs)
            except EmbeddingError as exc:
                # Don't roll back the doc's metadata save — aliases are
                # still useful in the UI even if re-embed fails. Surface
                # the error so the user can retry by saving again.
                raise KnowledgeServiceError(
                    f"Aliases saved, but re-embedding failed: {exc}"
                ) from exc
            for chunk, embedding in zip(chunks, new_embeddings):
                chunk_repo.update_content(
                    chunk.id,
                    content=chunk.content,
                    token_count=chunk.token_count,
                    embedding=embedding,
                )
            session.commit()

    def create_youtube_document(self, *, url: str) -> tuple[KbDocument, str]:
        """Stage a YouTube URL for ingestion.

        Downloads the audio stream synchronously (yt-dlp is fast enough
        for typical lengths that we don't need to background it before
        even creating the doc row). The downloaded audio path is
        returned alongside the new KbDocument so the caller can stash
        it where the worker will read it later.

        Note: the audio file ends up named per yt-dlp's template — e.g.
        `<video_id>.webm`. The caller is responsible for relocating it
        to the staging directory and triggering the ingestion job.
        """
        self._require_enabled()

        from backend.knowledge.video import (  # local import to avoid pulling
            YouTubeDownloadError,             # yt-dlp on every cold start
            download_youtube_audio,
        )

        if not url or not url.strip():
            raise KnowledgeServiceError("YouTube URL is required.")
        cleaned_url = url.strip()
        if not (
            cleaned_url.startswith("http://") or cleaned_url.startswith("https://")
        ):
            raise KnowledgeServiceError("URL must start with http:// or https://.")

        # Download into the cache dir's youtube subfolder. We don't put
        # it in the kb_uploads staging dir yet because we want to record
        # the doc row first (so the user sees something processing) and
        # only THEN move the audio file to the staging location.
        download_dir = Path(self.settings.cache_dir) / "youtube_downloads"
        try:
            # Pass the (optional) cookies file path so yt-dlp can
            # bypass YouTube's bot-detection challenge when needed.
            result = download_youtube_audio(
                cleaned_url,
                download_dir,
                cookies_file=self.settings.kb_youtube_cookies_file or None,
            )
        except YouTubeDownloadError as exc:
            raise KnowledgeServiceError(
                f"Failed to download YouTube audio: {exc}"
            ) from exc

        size_bytes = result.audio_path.stat().st_size if result.audio_path.exists() else 0
        if size_bytes > self.settings.kb_video_max_upload_bytes:
            # Clean up the oversized file so we don't leak disk space.
            try:
                result.audio_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise KnowledgeServiceError(
                f"YouTube audio is {size_bytes} bytes, exceeding the "
                f"{self.settings.kb_video_max_upload_bytes}-byte limit. "
                f"This usually means the video is very long."
            )

        with self._kb_session() as session:
            document = KbDocumentRepository(session).create_pending(
                # Use the yt-dlp-resolved title as the filename so the
                # UI shows something meaningful. The audio file on disk
                # has a different name (the YouTube video ID).
                filename=f"{result.title}.{result.audio_path.suffix.lstrip('.') or 'webm'}",
                file_type=VIDEO_FILE_TYPE,
                size_bytes=size_bytes,
                title=result.title,
                source_url=result.source_url,
            )
            session.commit()
            return document, str(result.audio_path)

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
