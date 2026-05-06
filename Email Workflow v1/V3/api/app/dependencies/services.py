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
from backend.application.queue_service import QueueService
from backend.application.review_service import ReviewService
from backend.application.runtime_settings_service import RuntimeSettingsService
from backend.application.sync_progress_store import SyncProgressStore
from backend.application.thread_analysis_service import ThreadAnalysisService
from backend.core.config import AppSettings, get_settings
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
    analysis_service = ThreadAnalysisService(
        provider_router,
        thread_repository,
        crm_service,
    )
    draft_service = DraftService(
        provider_router,
        thread_repository,
        draft_repository,
        runtime_settings,
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
    )


def get_service_bundle(
    session: Session = Depends(get_db_session),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> ServiceBundle:
    return build_service_bundle(session, current_user)


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
