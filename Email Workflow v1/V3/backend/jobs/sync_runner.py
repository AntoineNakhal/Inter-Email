"""CLI entry point for triggering a Gmail sync directly from the terminal.

This is a developer/debugging utility — **not** the canonical path for
production syncs (those go through the FastAPI sync router so the frontend
receives live progress events).

Usage:
    python -m backend.jobs.sync_runner

The runner mirrors the same service wiring as `api/app/dependencies/services.py`
so it exercises the exact same code path as a frontend-triggered sync.
"""

from __future__ import annotations

from backend.application.crm_service import CRMService
from backend.application.gmail_sync_service import GmailSyncService
from backend.application.queue_service import QueueService
from backend.application.runtime_settings_service import RuntimeSettingsService
from backend.application.sync_progress_store import SyncProgressStore
from backend.application.thread_analysis_service import ThreadAnalysisService
from backend.core.config import get_settings
from backend.core.database import get_session_factory, init_database
from backend.persistence.repositories.runtime_settings_repository import (
    RuntimeSettingsRepository,
)
from backend.persistence.repositories.sync_repository import SyncRepository
from backend.persistence.repositories.thread_repository import ThreadRepository
from backend.providers.ai.registry import build_provider_registry
from backend.providers.ai.router import AIProviderRouter
from backend.providers.gmail.client import GmailReadonlyClient


def main() -> None:
    settings = get_settings()
    settings.ensure_runtime_directories()
    init_database(settings)
    session_factory = get_session_factory()
    progress_store = SyncProgressStore()

    with session_factory() as session:
        runtime_settings_service = RuntimeSettingsService(
            RuntimeSettingsRepository(session)
        )
        runtime_settings = runtime_settings_service.get()

        registry = build_provider_registry(settings, runtime_settings)
        router = AIProviderRouter(settings, registry, runtime_settings)

        thread_repository = ThreadRepository(session)
        sync_repository = SyncRepository(session)
        crm_service = CRMService(router)
        analysis_service = ThreadAnalysisService(router, thread_repository, crm_service)
        queue_service = QueueService(router, thread_repository, runtime_settings)

        sync_service = GmailSyncService(
            session=session,
            runtime_settings=runtime_settings,
            gmail_client=GmailReadonlyClient(settings),
            thread_repository=thread_repository,
            sync_repository=sync_repository,
            analysis_service=analysis_service,
            queue_service=queue_service,
            progress_store=progress_store,
        )

        # Interrupt any orphaned runs before creating a new one.
        sync_repository.interrupt_stale_runs()
        session.commit()

        # create_run() enforces the per-account single-active-run lock.
        run_summary = sync_service.create_run(source=settings.gmail_thread_source)
        run_id = run_summary.run_id

        result = sync_service.sync_recent_threads(
            run_id=run_id,
            source=settings.gmail_thread_source,
            max_results=settings.gmail_max_results,
        )

        print(
            f"Completed sync run {result.run_id} — "
            f"{result.thread_count} thread(s), "
            f"{result.ai_thread_count} AI-analyzed."
        )


if __name__ == "__main__":
    main()
