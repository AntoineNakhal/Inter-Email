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

from api.app.dependencies.services import build_service_bundle_for_user_id
from backend.core.config import get_settings
from backend.core.database import get_session_factory, init_database
from backend.persistence.repositories.sync_repository import SyncRepository
from backend.persistence.repositories.user_repository import UserRepository


def main() -> None:
    settings = get_settings()
    settings.ensure_runtime_directories()
    init_database(settings)
    session_factory = get_session_factory()
    with session_factory() as session:
        connected_users = UserRepository(session).list_connected_users()
        if not connected_users:
            raise RuntimeError("No authenticated Gmail users are connected.")
        services = build_service_bundle_for_user_id(session, connected_users[0].id)
        sync_service = services.sync_service
        sync_repository = SyncRepository(session)

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
