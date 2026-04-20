"""Service wiring for API routes."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends
from sqlalchemy.orm import Session

from api.app.dependencies.db import get_db_session
from backend.application.crm_service import CRMService
from backend.application.draft_service import DraftService
from backend.application.gmail_connection_service import (
    GmailConnectionService,
    GmailConnectionStateStore,
)
from backend.application.gmail_sync_service import GmailSyncService
from backend.application.queue_service import QueueService
from backend.application.review_service import ReviewService
from backend.application.sync_progress_store import SyncProgressStore
from backend.application.thread_analysis_service import ThreadAnalysisService
from backend.core.config import AppSettings, get_settings
from backend.persistence.repositories.draft_repository import DraftRepository
from backend.persistence.repositories.review_repository import ReviewRepository
from backend.persistence.repositories.sync_repository import SyncRepository
from backend.persistence.repositories.thread_repository import ThreadRepository
from backend.providers.ai.registry import build_provider_registry
from backend.providers.ai.router import AIProviderRouter
from backend.providers.gmail.client import GmailReadonlyClient


@dataclass
class ServiceBundle:
    settings: AppSettings
    session: Session
    gmail_connection_service: GmailConnectionService
    queue_service: QueueService
    review_service: ReviewService
    draft_service: DraftService
    sync_service: GmailSyncService


GMAIL_CONNECTION_STATE_STORE = GmailConnectionStateStore()
SYNC_PROGRESS_STORE = SyncProgressStore()


def build_service_bundle(session: Session) -> ServiceBundle:
    settings = get_settings()
    registry = build_provider_registry(settings)
    provider_router = AIProviderRouter(settings, registry)
    gmail_client = GmailReadonlyClient(settings)
    thread_repository = ThreadRepository(session)
    review_repository = ReviewRepository(session)
    draft_repository = DraftRepository(session)
    queue_service = QueueService(provider_router, thread_repository)
    crm_service = CRMService(provider_router)
    analysis_service = ThreadAnalysisService(
        provider_router,
        thread_repository,
        crm_service,
    )
    draft_service = DraftService(provider_router, thread_repository, draft_repository)
    review_service = ReviewService(review_repository, thread_repository)
    gmail_connection_service = GmailConnectionService(
        gmail_client=gmail_client,
        state_store=GMAIL_CONNECTION_STATE_STORE,
    )
    sync_service = GmailSyncService(
        session=session,
        gmail_client=gmail_client,
        thread_repository=thread_repository,
        sync_repository=SyncRepository(session),
        analysis_service=analysis_service,
        queue_service=queue_service,
        progress_store=SYNC_PROGRESS_STORE,
    )
    return ServiceBundle(
        settings=settings,
        session=session,
        gmail_connection_service=gmail_connection_service,
        queue_service=queue_service,
        review_service=review_service,
        draft_service=draft_service,
        sync_service=sync_service,
    )


def get_service_bundle(
    session: Session = Depends(get_db_session),
) -> ServiceBundle:
    return build_service_bundle(session)
