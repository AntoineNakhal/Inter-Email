"""Simple CLI runner for local backend syncs."""

from __future__ import annotations

from backend.application.crm_service import CRMService
from backend.application.gmail_sync_service import GmailSyncService
from backend.application.queue_service import QueueService
from backend.application.thread_analysis_service import ThreadAnalysisService
from backend.core.config import get_settings
from backend.core.database import get_session_factory, init_database
from backend.providers.ai.registry import build_provider_registry
from backend.providers.ai.router import AIProviderRouter
from backend.providers.gmail.client import GmailReadonlyClient
from backend.persistence.repositories.sync_repository import SyncRepository
from backend.persistence.repositories.thread_repository import ThreadRepository


def main() -> None:
    settings = get_settings()
    init_database(settings)
    session_factory = get_session_factory()
    registry = build_provider_registry(settings)
    router = AIProviderRouter(settings, registry)

    with session_factory() as session:
        thread_repository = ThreadRepository(session)
        queue_service = QueueService(router, thread_repository)
        crm_service = CRMService(router)
        analysis_service = ThreadAnalysisService(router, thread_repository, crm_service)
        sync_service = GmailSyncService(
            session=session,
            gmail_client=GmailReadonlyClient(settings),
            thread_repository=thread_repository,
            sync_repository=SyncRepository(session),
            analysis_service=analysis_service,
            queue_service=queue_service,
        )
        result = sync_service.sync_recent_threads(
            source=settings.gmail_thread_source,
            max_results=settings.gmail_max_results,
        )
        print(
            f"Completed sync run {result.run_id} with {result.thread_count} thread(s) "
            f"and {result.ai_thread_count} AI-covered thread(s)."
        )


if __name__ == "__main__":
    main()
