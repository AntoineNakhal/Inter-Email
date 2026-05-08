"""Service wiring for API routes."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends
from sqlalchemy.orm import Session

from api.app.dependencies.auth import build_auth_service, get_current_user
from api.app.dependencies.db import get_db_session
from backend.application.auth_service import AuthService
from backend.application.crm_service import CRMService
from backend.application.draft_service import DraftService
from backend.application.gmail_connection_service import (
    GmailConnectionService,
    GmailConnectionStateStore,
)
from backend.application.gmail_sync_service import GmailSyncService
from backend.application.knowledge_service import KnowledgeService
from backend.application.queue_service import QueueService
from backend.application.review_service import ReviewService
from backend.application.runtime_settings_service import RuntimeSettingsService
from backend.application.sync_progress_store import SyncProgressStore
from backend.application.thread_analysis_service import ThreadAnalysisService
from backend.core.config import AppSettings, get_settings
from backend.knowledge.database import (
    get_kb_session_factory,
    is_kb_enabled,
)
from backend.knowledge.repositories.chunk_repository import KbChunkRepository
from backend.knowledge.services.embedding_service import EmbeddingService
from backend.knowledge.services.retrieval_service import RagRetrievalService
from backend.domain.user import AuthenticatedUser
from backend.persistence.repositories.contact_repository import ContactRepository
from backend.persistence.repositories.draft_repository import DraftRepository
from backend.persistence.repositories.eta_progress_repository import EtaProgressRepository
from backend.persistence.repositories.review_repository import ReviewRepository
from backend.persistence.repositories.runtime_settings_repository import (
    RuntimeSettingsRepository,
)
from backend.persistence.repositories.sync_repository import SyncRepository
from backend.persistence.repositories.thread_repository import ThreadRepository
from backend.persistence.repositories.user_repository import UserRepository
from backend.providers.ai.registry import build_provider_registry
from backend.providers.ai.router import AIProviderRouter
from backend.providers.gmail.client import GmailReadonlyClient


@dataclass
class ServiceBundle:
    settings: AppSettings
    session: Session
    current_user: AuthenticatedUser
    auth_service: AuthService
    runtime_settings_service: RuntimeSettingsService
    gmail_connection_service: GmailConnectionService
    queue_service: QueueService
    review_service: ReviewService
    draft_service: DraftService
    sync_service: GmailSyncService
    analysis_service: ThreadAnalysisService
    contact_repository: ContactRepository
    knowledge_service: KnowledgeService
    # Optional KB session held open for the duration of the request so the
    # RagRetrievalService injected into analysis/draft services has a live
    # transaction. Closed by `get_service_bundle()` after the request body
    # finishes. None when the KB feature is disabled.
    kb_session: Session | None = None

    def close(self) -> None:
        """Release any resources owned by the bundle.

        Called by the FastAPI dependency teardown for HTTP requests, and
        manually by the Arq worker after each job. The main DB session is
        managed by `get_db_session` / the worker's own try-finally block,
        so we only handle the KB session here.
        """
        if self.kb_session is not None:
            try:
                self.kb_session.close()
            except Exception:  # pragma: no cover — best-effort cleanup
                pass
            self.kb_session = None


GMAIL_CONNECTION_STATE_STORE = GmailConnectionStateStore()
SYNC_PROGRESS_STORE = SyncProgressStore()


def build_service_bundle(
    session: Session,
    current_user: AuthenticatedUser,
) -> ServiceBundle:
    settings = get_settings()
    auth_service = build_auth_service(session)
    gmail_credentials = auth_service.decrypt_user_gmail_token(current_user)
    gmail_client = GmailReadonlyClient(
        settings,
        credentials_json=gmail_credentials,
        persist_credentials=lambda payload: _persist_user_gmail_credentials(
            session=session,
            settings=settings,
            user_id=current_user.id,
            credentials_json=payload,
        ),
    )
    runtime_settings_service = RuntimeSettingsService(
        RuntimeSettingsRepository(session, current_user.id)
    )
    runtime_settings = runtime_settings_service.get()
    registry = build_provider_registry(settings, runtime_settings)
    provider_router = AIProviderRouter(settings, registry, runtime_settings)
    thread_repository = ThreadRepository(session, current_user.id)
    review_repository = ReviewRepository(session, current_user.id)
    draft_repository = DraftRepository(session, current_user.id)
    sync_repository = SyncRepository(session, current_user.id)
    eta_progress_repository = EtaProgressRepository(session, current_user.id)
    queue_service = QueueService(provider_router, thread_repository, runtime_settings)
    crm_service = CRMService(provider_router)

    # KB / RAG. We build the retrieval service only when KB_DATABASE_URL is
    # set, so the rest of the app keeps working in environments where the
    # KB feature is intentionally turned off (CI, smoke tests, ...). We
    # also need to track the session we open for it so we can close it at
    # the end of the request.
    rag_service, kb_session = _build_rag_service_or_none(settings)

    analysis_service = ThreadAnalysisService(
        provider_router,
        thread_repository,
        crm_service,
        rag_service=rag_service,
    )
    draft_service = DraftService(
        provider_router,
        thread_repository,
        draft_repository,
        runtime_settings,
        rag_service=rag_service,
    )
    review_service = ReviewService(review_repository, thread_repository)
    gmail_connection_service = GmailConnectionService(
        gmail_client=gmail_client,
        state_store=GMAIL_CONNECTION_STATE_STORE,
        runtime_settings_service=runtime_settings_service,
        thread_repository=thread_repository,
        sync_repository=sync_repository,
        progress_store=SYNC_PROGRESS_STORE,
        session=session,
    )
    sync_service = GmailSyncService(
        session=session,
        runtime_settings=runtime_settings,
        gmail_client=gmail_client,
        thread_repository=thread_repository,
        sync_repository=sync_repository,
        analysis_service=analysis_service,
        queue_service=queue_service,
        progress_store=SYNC_PROGRESS_STORE,
        eta_progress_repository=eta_progress_repository,
    )
    return ServiceBundle(
        settings=settings,
        session=session,
        current_user=current_user,
        auth_service=auth_service,
        runtime_settings_service=runtime_settings_service,
        gmail_connection_service=gmail_connection_service,
        queue_service=queue_service,
        review_service=review_service,
        draft_service=draft_service,
        sync_service=sync_service,
        analysis_service=analysis_service,
        contact_repository=ContactRepository(session, current_user.id),
        knowledge_service=KnowledgeService(settings),
        kb_session=kb_session,
    )


def _build_rag_service_or_none(
    settings: AppSettings,
) -> tuple[RagRetrievalService | None, Session | None]:
    """Construct a RagRetrievalService bound to its own KB session.

    Returns (None, None) when KB_DATABASE_URL is not configured. Otherwise
    returns (service, session) — the caller is responsible for closing the
    session when the request finishes.

    Wrapped in try/except so a transient KB outage never breaks analysis
    or drafting — those services accept None and skip context injection.
    """
    if not is_kb_enabled(settings):
        return None, None
    try:
        kb_session = get_kb_session_factory()()
    except Exception:
        # Surface to logs but don't break the request — RAG is enrichment.
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "Failed to open KB session — RAG disabled for this request.",
            exc_info=True,
        )
        return None, None
    service = RagRetrievalService(
        chunk_repository=KbChunkRepository(kb_session),
        embedding_service=EmbeddingService(settings),
        settings=settings,
    )
    return service, kb_session


def get_service_bundle(
    session: Session = Depends(get_db_session),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Yield-style dependency so we can close the KB session post-request.

    FastAPI runs everything before the `yield` before the route, and
    everything after when the response is finished. Without this teardown
    the KB session would leak a Postgres connection per request.
    """
    bundle = build_service_bundle(session, current_user)
    try:
        yield bundle
    finally:
        bundle.close()


def build_service_bundle_for_user_id(
    session: Session,
    user_id: int,
) -> ServiceBundle:
    user = UserRepository(session).get_by_id(user_id)
    if user is None:
        raise ValueError(f"User `{user_id}` was not found.")
    return build_service_bundle(session, user)


def _persist_user_gmail_credentials(
    *,
    session: Session,
    settings: AppSettings,
    user_id: int,
    credentials_json: str,
) -> None:
    from backend.core.crypto import encrypt_text

    model = UserRepository(session).get_model_by_id(user_id)
    if model is None:
        raise ValueError(f"User `{user_id}` was not found.")
    model.gmail_token_encrypted = encrypt_text(
        credentials_json,
        settings.auth_token_encryption_key,
    )
    session.flush()
