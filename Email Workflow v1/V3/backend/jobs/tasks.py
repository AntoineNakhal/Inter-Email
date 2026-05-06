"""Arq task definitions.

Each function here is an async task that Arq enqueues and the worker executes.
They import the same backend package as the API — no business logic duplication.

The ctx dict is injected by Arq and carries shared state set up in WorkerSettings
(currently unused, kept for future connection pooling).
"""

from __future__ import annotations

import logging

from backend.core.database import get_session_factory
from api.app.dependencies.services import build_service_bundle_for_user_id
from backend.persistence.repositories.sync_repository import SyncRepository


logger = logging.getLogger(__name__)


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
        session.close()
