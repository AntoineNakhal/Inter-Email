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
    KbDocumentListResponse,
    KbDocumentResponse,
    KbFinalizeRequest,
    KbUploadResponse,
)
from backend.application.knowledge_service import KnowledgeServiceError
from backend.core.config import get_settings
from backend.knowledge.database import KnowledgeBaseDisabledError
from backend.knowledge.domain.document import KbDocumentMetadata


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
    try:
        content = await file.read()
        document = services.knowledge_service.create_pending_document(
            filename=file.filename or "untitled",
            content=content,
        )
    except KnowledgeBaseDisabledError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KnowledgeServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Stage the bytes to disk so the worker process can read them. We use
    # the same `data/` volume that's mounted into both api and worker
    # containers so any worker (Arq or inline) can pick them up.
    settings = services.settings
    staging_dir = Path(settings.cache_dir) / "kb_uploads"
    staging_dir.mkdir(parents=True, exist_ok=True)
    staging_path = staging_dir / f"{document.id}__{document.filename}"
    staging_path.write_bytes(content)

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
            ),
        )
    except KnowledgeBaseDisabledError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KnowledgeServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return KbDocumentResponse.from_domain(document)


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
        content = path.read_bytes()
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
