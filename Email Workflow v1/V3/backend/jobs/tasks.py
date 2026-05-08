"""Arq task definitions.

Each function here is an async task that Arq enqueues and the worker executes.
They import the same backend package as the API — no business logic duplication.

The ctx dict is injected by Arq and carries shared state set up in WorkerSettings
(currently unused, kept for future connection pooling).
"""

from __future__ import annotations

import logging
from pathlib import Path

from backend.core.config import get_settings
from backend.core.database import get_session_factory
from api.app.dependencies.services import build_service_bundle_for_user_id
from backend.knowledge.database import get_kb_session_factory
from backend.knowledge.repositories.chunk_repository import KbChunkRepository
from backend.knowledge.repositories.document_repository import KbDocumentRepository
from backend.knowledge.services.chunker import TokenChunker
from backend.knowledge.services.embedding_service import EmbeddingService
from backend.knowledge.services.ingestion_service import IngestionService
from backend.knowledge.services.metadata_service import MetadataExtractionService
from backend.persistence.repositories.sync_repository import SyncRepository


logger = logging.getLogger(__name__)


async def ingest_kb_document(
    ctx: dict,
    document_id: int,
    file_path: str,
    filename: str,
    file_type: str,
) -> None:
    """Run the KB ingestion pipeline for one uploaded file.

    `file_path` is a path inside the shared `data/` volume — the API writes
    bytes there before enqueuing this job, the worker reads them, then we
    delete the staging file once ingestion finishes (success or failure).

    The session lifecycle is owned here, mirroring run_sync above.
    """
    path = Path(file_path)
    settings = get_settings()
    session = get_kb_session_factory()()
    try:
        if not path.exists():
            raise FileNotFoundError(f"KB staging file missing: {path}")

        content = path.read_bytes()
        ingestion = IngestionService(
            session=session,
            document_repository=KbDocumentRepository(session),
            chunk_repository=KbChunkRepository(session),
            chunker=TokenChunker(),
            embedding_service=EmbeddingService(settings),
            metadata_service=MetadataExtractionService(settings),
            settings=settings,
        )
        ingestion.ingest(
            document_id=document_id,
            content=content,
            filename=filename,
            file_type=file_type,
        )
    except Exception:
        # IngestionService already marks the doc FAILED + commits, so all
        # we need here is structured logging.
        logger.exception(
            "KB ingestion failed for document_id=%s file=%s",
            document_id,
            filename,
        )
    finally:
        session.close()
        # Best-effort cleanup of the staging file — leaving it around is
        # not catastrophic but it bloats the data volume.
        try:
            if path.exists():
                path.unlink()
        except OSError:
            logger.warning("Failed to delete KB staging file %s", path)


async def run_sync(
    ctx: dict,
    run_id: int,
    source: str,
    max_results: int,
    lookback_days: int,
) -> None:
    """Execute a Gmail sync run inside the Arq worker process."""
    session_factory = get_session_factory()
    session = session_factory()
    services = None
    try:
        run_model = SyncRepository(session).get_run_model(run_id)
        if run_model is None:
            raise ValueError(f"Sync run `{run_id}` was not found.")
        services = build_service_bundle_for_user_id(session, run_model.user_id)
        # The API created this run in its own in-memory progress_store.
        # The worker has a separate empty store — register the run here so
        # every progress_store.update() call returns a valid summary and
        # _persist_stage_progress() writes live progress to the DB.
        services.sync_service.progress_store.start(run_id, source)
        services.sync_service.sync_recent_threads(
            run_id=run_id,
            source=source,
            max_results=max_results,
            lookback_days=lookback_days,
        )
        topic = services.settings.gmail_pubsub_topic
        if topic:
            services.sync_service.ensure_watch(topic)
    except Exception:
        logger.exception("Gmail sync failed in worker (run_id=%s)", run_id)
    finally:
        if services is not None:
            services.close()  # closes any KB session opened for RAG.
        session.close()
