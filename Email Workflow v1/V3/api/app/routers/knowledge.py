"""Knowledge Base endpoints — upload, list, delete documents.

The upload route deliberately keeps the HTTP request short:
  1. Validate file type + size
  2. Persist a PENDING `kb_documents` row + stash bytes on disk
  3. Enqueue an Arq job (or run inline if Redis isn't configured)
  4. Return the document row immediately (status=PROCESSING).

Frontend polls GET /knowledge/documents to learn when status flips to
READY or FAILED.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)

from api.app.dependencies.services import ServiceBundle, get_service_bundle
from api.app.schemas.knowledge import (
    KbChunkListResponse,
    KbChunkSummary,
    KbChunkUpdateRequest,
    KbDiagnoseMatch,
    KbDiagnoseResponse,
    KbDocumentListResponse,
    KbDocumentResponse,
    KbFinalizeRequest,
    KbUploadResponse,
    KbYouTubeIngestRequest,
)
from backend.application.knowledge_service import KnowledgeServiceError
from backend.core.config import get_settings
from backend.knowledge.database import (
    KnowledgeBaseDisabledError,
    get_kb_session_factory,
    is_kb_enabled,
)
from backend.knowledge.domain.document import KbDocumentMetadata, KbIngestionStatus
from backend.knowledge.repositories.chunk_repository import KbChunkRepository
from backend.knowledge.services.embedding_service import (
    EmbeddingError,
    EmbeddingService,
)
from sqlalchemy import func, select
from backend.knowledge.models.chunk import KbChunkModel
from backend.knowledge.models.document import KbDocumentModel


logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/knowledge/documents", response_model=KbDocumentListResponse)
def list_documents(
    services: ServiceBundle = Depends(get_service_bundle),
) -> KbDocumentListResponse:
    try:
        docs = services.knowledge_service.list_documents()
    except KnowledgeBaseDisabledError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return KbDocumentListResponse(
        documents=[KbDocumentResponse.from_domain(d) for d in docs]
    )


@router.post(
    "/knowledge/documents",
    response_model=KbUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    services: ServiceBundle = Depends(get_service_bundle),
) -> KbUploadResponse:
    """Streaming upload — the request body is copied to disk in 1 MB
    chunks rather than loaded into memory. Critical for video files
    (which can be GB-scale) but cheap enough that we use the same path
    for text uploads too.

    The temp file gets a uuid-ish name during streaming; once we've
    validated type + size we rename it to the final
    `<doc_id>__<filename>` convention the worker reads from.
    """
    import uuid

    settings = services.settings
    staging_dir = Path(settings.cache_dir) / "kb_uploads"
    staging_dir.mkdir(parents=True, exist_ok=True)
    temp_path = staging_dir / f"_upload_{uuid.uuid4().hex}"

    try:
        # Stream from the multipart upload directly to disk. Starlette
        # already spools large uploads to a temp file under the hood,
        # so we're really just copying that temp file to our staging
        # dir without ever loading the full payload into memory.
        with temp_path.open("wb") as fp:
            while True:
                chunk = await file.read(1024 * 1024)  # 1 MB
                if not chunk:
                    break
                fp.write(chunk)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    try:
        document = services.knowledge_service.create_pending_document_from_path(
            filename=file.filename or "untitled",
            file_path=temp_path,
        )
    except KnowledgeBaseDisabledError as exc:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KnowledgeServiceError as exc:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Rename the temp file to the worker-readable convention. Same
    # filesystem so this is an atomic rename, not a copy.
    staging_path = staging_dir / f"{document.id}__{document.filename}"
    try:
        temp_path.replace(staging_path)
    except OSError as exc:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to stage upload: {exc}",
        ) from exc

    if settings.redis_url:
        # Real worker available — enqueue via Arq.
        await _enqueue_kb_ingest_job(
            document_id=document.id,
            file_path=str(staging_path),
            filename=document.filename,
            file_type=document.file_type,
        )
        logger.info(
            "KB ingestion enqueued via Arq for document_id=%s", document.id
        )
    else:
        # Local dev / no Redis — run inline via BackgroundTasks.
        background_tasks.add_task(
            _run_kb_ingest_inline,
            document.id,
            str(staging_path),
            document.filename,
            document.file_type,
        )
        logger.info(
            "KB ingestion started via BackgroundTasks for document_id=%s",
            document.id,
        )

    return KbUploadResponse(document=KbDocumentResponse.from_domain(document))


@router.get("/knowledge/documents/{document_id}", response_model=KbDocumentResponse)
def get_document(
    document_id: int,
    services: ServiceBundle = Depends(get_service_bundle),
) -> KbDocumentResponse:
    """Single-document fetch — used by the review modal to poll for
    extraction completion (PROCESSING → AWAITING_REVIEW)."""
    try:
        document = services.knowledge_service.get_document(document_id)
    except KnowledgeBaseDisabledError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return KbDocumentResponse.from_domain(document)


@router.get(
    "/knowledge/documents/{document_id}/chunks",
    response_model=KbChunkListResponse,
)
def list_chunks(
    document_id: int,
    services: ServiceBundle = Depends(get_service_bundle),
) -> KbChunkListResponse:
    """Return every chunk for a document.

    Used by the review modal's chunk explorer so the user can audit the
    extractor + chunker output before approving the doc. Read-only — we
    don't currently support editing chunks because edits would invalidate
    the embedding (you'd need to re-embed the chunk before saving).
    """
    try:
        # 404 early so the response shape is consistent.
        document = services.knowledge_service.get_document(document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found.")
        chunks = services.knowledge_service.list_chunks(document_id)
    except KnowledgeBaseDisabledError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return KbChunkListResponse(
        document_id=document_id,
        chunks=[
            KbChunkSummary(
                id=chunk.id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                token_count=chunk.token_count,
            )
            for chunk in chunks
        ],
    )


@router.post(
    "/knowledge/documents/{document_id}/finalize",
    response_model=KbDocumentResponse,
)
def finalize_document(
    document_id: int,
    payload: KbFinalizeRequest,
    services: ServiceBundle = Depends(get_service_bundle),
) -> KbDocumentResponse:
    """User-approved review — flip the doc to READY so RAG can use it."""
    try:
        document = services.knowledge_service.finalize_document(
            document_id,
            metadata=KbDocumentMetadata(
                title=payload.title,
                product_name=_normalize_blank(payload.product_name),
                category=_normalize_blank(payload.category),
                description=_normalize_blank(payload.description),
                search_aliases=(payload.search_aliases or "").strip(),
            ),
        )
    except KnowledgeBaseDisabledError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KnowledgeServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return KbDocumentResponse.from_domain(document)


@router.get("/knowledge/diagnose", response_model=KbDiagnoseResponse)
def diagnose_rag(
    query: str = "",
    services: ServiceBundle = Depends(get_service_bundle),
) -> KbDiagnoseResponse:
    """End-to-end RAG self-check.

    Walks every layer the retrieval pipeline depends on and returns a
    structured report:

      1. Is KB enabled in config?
      2. Can we open a KB session?
      3. How many docs by status? How many chunks?
      4. Does the embedding API succeed for the query?
      5. What does pgvector return (top-K, unfiltered)?
      6. What survives the similarity threshold?

    Use this whenever the draft "no sources" panel says no context was
    used and you want to confirm where the chain breaks. A working RAG
    setup will show a non-empty `matches_above_threshold` list and a
    verdict starting with "OK".
    """
    settings = services.settings
    threshold = settings.kb_similarity_threshold
    top_k = settings.kb_top_k
    sample_query = query.strip() or "test query for diagnostics"

    # Layer 1: config
    if not is_kb_enabled(settings):
        return KbDiagnoseResponse(
            kb_enabled=False,
            kb_session_open=False,
            documents_by_status={},
            documents_ready=0,
            chunks_total=0,
            query=sample_query,
            embedding_succeeded=False,
            embedding_dim=0,
            threshold=threshold,
            top_k=top_k,
            unfiltered_matches=[],
            matches_above_threshold=[],
            verdict=(
                "FAIL: KB_DATABASE_URL is not set in this container's "
                "environment. Knowledge Base is disabled."
            ),
        )

    # Layer 2: DB session
    try:
        kb_session = get_kb_session_factory()()
    except Exception as exc:
        return KbDiagnoseResponse(
            kb_enabled=True,
            kb_session_open=False,
            documents_by_status={},
            documents_ready=0,
            chunks_total=0,
            query=sample_query,
            embedding_succeeded=False,
            embedding_dim=0,
            threshold=threshold,
            top_k=top_k,
            unfiltered_matches=[],
            matches_above_threshold=[],
            verdict=(
                f"FAIL: Could not open KB session — {type(exc).__name__}: {exc}. "
                "Check that the kb-postgres container is healthy."
            ),
        )

    try:
        # Layer 3: corpus census
        status_rows = kb_session.execute(
            select(KbDocumentModel.status, func.count(KbDocumentModel.id))
            .group_by(KbDocumentModel.status)
        ).all()
        documents_by_status = {
            (row[0].value if hasattr(row[0], "value") else str(row[0])): row[1]
            for row in status_rows
        }
        documents_ready = documents_by_status.get(
            KbIngestionStatus.READY.value, 0
        )
        chunks_total = kb_session.scalar(
            select(func.count(KbChunkModel.id))
        ) or 0

        # Layer 4: embedding API
        embedding_service = EmbeddingService(settings)
        try:
            query_embedding = embedding_service.embed_one(sample_query)
            embedding_succeeded = True
            embedding_dim = len(query_embedding)
        except EmbeddingError as exc:
            return KbDiagnoseResponse(
                kb_enabled=True,
                kb_session_open=True,
                documents_by_status=documents_by_status,
                documents_ready=documents_ready,
                chunks_total=chunks_total,
                query=sample_query,
                embedding_succeeded=False,
                embedding_dim=0,
                threshold=threshold,
                top_k=top_k,
                unfiltered_matches=[],
                matches_above_threshold=[],
                verdict=f"FAIL: Embedding API call failed — {exc}",
            )

        # Layer 5+6: pgvector search, both unfiltered and filtered
        chunk_repo = KbChunkRepository(kb_session)
        unfiltered = chunk_repo.search_similar(
            query_embedding=query_embedding,
            top_k=top_k,
            similarity_threshold=0.0,
        )
        filtered = [m for m in unfiltered if m.similarity >= threshold]

        def to_match(match) -> KbDiagnoseMatch:
            preview = (match.chunk.content or "").strip().replace("\n", " ")
            if len(preview) > 200:
                preview = preview[:199] + "…"
            return KbDiagnoseMatch(
                chunk_id=match.chunk.id,
                chunk_index=match.chunk.chunk_index,
                document_id=match.chunk.document_id,
                document_title=match.document_title,
                similarity=round(match.similarity, 4),
                preview=preview,
            )

        unfiltered_payload = [to_match(m) for m in unfiltered]
        filtered_payload = [to_match(m) for m in filtered]

        # Layer 7: human-readable verdict
        if documents_ready == 0:
            verdict = (
                "FAIL: No documents are in READY state. RAG only searches "
                "READY documents; everything else is excluded. Approve a "
                "document via the review modal on /technical-info."
            )
        elif chunks_total == 0:
            verdict = (
                "FAIL: There are READY documents but no chunks in the "
                "kb_chunks table. Ingestion never finished — check worker "
                "logs."
            )
        elif not unfiltered:
            verdict = (
                "FAIL: pgvector returned 0 candidates even with no "
                "threshold. Likely cause: status filter mismatch. "
                "Investigate the WHERE clause in chunk_repository."
            )
        elif not filtered:
            top_score = unfiltered[0].similarity if unfiltered else 0.0
            verdict = (
                f"WARN: Top match similarity is {top_score:.3f}, below the "
                f"threshold of {threshold:.2f}. Either lower "
                f"KB_SIMILARITY_THRESHOLD or re-check whether the "
                f"document actually contains the queried information."
            )
        else:
            top_score = filtered[0].similarity
            verdict = (
                f"OK: RAG is working. Top match similarity {top_score:.3f}, "
                f"{len(filtered)} chunks above threshold {threshold:.2f}."
            )

        return KbDiagnoseResponse(
            kb_enabled=True,
            kb_session_open=True,
            documents_by_status=documents_by_status,
            documents_ready=documents_ready,
            chunks_total=chunks_total,
            query=sample_query,
            embedding_succeeded=embedding_succeeded,
            embedding_dim=embedding_dim,
            threshold=threshold,
            top_k=top_k,
            unfiltered_matches=unfiltered_payload,
            matches_above_threshold=filtered_payload,
            verdict=verdict,
        )
    finally:
        kb_session.close()


@router.post(
    "/knowledge/youtube",
    response_model=KbUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_youtube(
    payload: KbYouTubeIngestRequest,
    background_tasks: BackgroundTasks,
    services: ServiceBundle = Depends(get_service_bundle),
) -> KbUploadResponse:
    """Ingest a YouTube video by URL.

    Synchronously downloads the audio (yt-dlp) so we can validate the
    URL and surface errors immediately to the user, then enqueues the
    same ingestion job as a file upload — the video pipeline takes
    over from there.
    """
    try:
        document, audio_path_str = services.knowledge_service.create_youtube_document(
            url=payload.url,
        )
    except KnowledgeBaseDisabledError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KnowledgeServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Move the downloaded audio into the kb_uploads staging dir so the
    # ingest job finds it via the same convention as uploaded files.
    from pathlib import Path as _Path
    source_audio = _Path(audio_path_str)
    settings = services.settings
    staging_dir = _Path(settings.cache_dir) / "kb_uploads"
    staging_dir.mkdir(parents=True, exist_ok=True)
    staging_path = staging_dir / f"{document.id}__{source_audio.name}"
    try:
        source_audio.replace(staging_path)
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to stage downloaded audio: {exc}",
        ) from exc

    if settings.redis_url:
        await _enqueue_kb_ingest_job(
            document_id=document.id,
            file_path=str(staging_path),
            filename=document.filename,
            file_type=document.file_type,
        )
    else:
        background_tasks.add_task(
            _run_kb_ingest_inline,
            document.id,
            str(staging_path),
            document.filename,
            document.file_type,
        )
    logger.info(
        "YouTube ingestion enqueued for document_id=%s url=%s",
        document.id,
        payload.url,
    )
    return KbUploadResponse(document=KbDocumentResponse.from_domain(document))


@router.delete("/knowledge/documents/{document_id}", status_code=204)
def delete_document(
    document_id: int,
    services: ServiceBundle = Depends(get_service_bundle),
) -> None:
    try:
        deleted = services.knowledge_service.delete_document(document_id)
    except KnowledgeBaseDisabledError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found.")


@router.patch(
    "/knowledge/documents/{document_id}/chunks/{chunk_id}",
    response_model=KbChunkSummary,
)
def update_chunk(
    document_id: int,
    chunk_id: int,
    payload: KbChunkUpdateRequest,
    services: ServiceBundle = Depends(get_service_bundle),
) -> KbChunkSummary:
    """Edit one chunk's content. Embedding is regenerated automatically."""
    try:
        chunk = services.knowledge_service.update_chunk(
            document_id,
            chunk_id,
            content=payload.content,
        )
    except KnowledgeBaseDisabledError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KnowledgeServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return KbChunkSummary(
        id=chunk.id,
        chunk_index=chunk.chunk_index,
        content=chunk.content,
        token_count=chunk.token_count,
    )


@router.delete(
    "/knowledge/documents/{document_id}/chunks/{chunk_id}",
    status_code=204,
)
def delete_chunk(
    document_id: int,
    chunk_id: int,
    services: ServiceBundle = Depends(get_service_bundle),
) -> None:
    try:
        deleted = services.knowledge_service.delete_chunk(document_id, chunk_id)
    except KnowledgeBaseDisabledError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KnowledgeServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Chunk not found.")


def _normalize_blank(value: str | None) -> str | None:
    """Treat all-whitespace strings as null so the DB stores cleanly."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


# ──────────────────────────────────────────────────────────────────────────
# Job dispatch helpers
# ──────────────────────────────────────────────────────────────────────────
async def _enqueue_kb_ingest_job(
    *,
    document_id: int,
    file_path: str,
    filename: str,
    file_type: str,
) -> None:
    import arq
    from backend.jobs.worker import get_redis_settings

    redis = await arq.create_pool(get_redis_settings())
    await redis.enqueue_job(
        "ingest_kb_document",
        document_id,
        file_path,
        filename,
        file_type,
    )
    await redis.close()


def _run_kb_ingest_inline(
    document_id: int,
    file_path: str,
    filename: str,
    file_type: str,
) -> None:
    """Sync fallback for local dev when Redis isn't configured.

    Mirrors the Arq path in `backend.jobs.tasks.ingest_kb_document` but
    drives it from a plain function so FastAPI's BackgroundTasks can run it.
    """
    from pathlib import Path as _Path

    from backend.knowledge.database import get_kb_session_factory
    from backend.knowledge.repositories.chunk_repository import KbChunkRepository
    from backend.knowledge.repositories.document_repository import KbDocumentRepository
    from backend.knowledge.services.chunker import TokenChunker
    from backend.knowledge.services.embedding_service import EmbeddingService
    from backend.knowledge.services.ingestion_service import IngestionService
    from backend.knowledge.services.metadata_service import MetadataExtractionService

    settings = get_settings()
    path = _Path(file_path)
    session = get_kb_session_factory()()
    try:
        if not path.exists():
            logger.error("KB staging file vanished before ingestion: %s", path)
            return
        from backend.knowledge.extractors import VIDEO_FILE_TYPE
        is_video = file_type == VIDEO_FILE_TYPE
        content = b"" if is_video else path.read_bytes()
        IngestionService(
            session=session,
            document_repository=KbDocumentRepository(session),
            chunk_repository=KbChunkRepository(session),
            chunker=TokenChunker(),
            embedding_service=EmbeddingService(settings),
            metadata_service=MetadataExtractionService(settings),
            settings=settings,
        ).ingest(
            document_id=document_id,
            content=content,
            filename=filename,
            file_type=file_type,
            source_path=path if is_video else None,
        )
    except Exception:
        logger.exception(
            "KB inline ingestion failed for document_id=%s", document_id
        )
    finally:
        session.close()
        try:
            if path.exists():
                path.unlink()
        except OSError:
            logger.warning("Failed to delete KB staging file %s", path)
