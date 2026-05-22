"""Sync endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from api.app.dependencies.services import build_service_bundle_for_user_id, get_service_bundle
from api.app.dependencies.services import ServiceBundle
from api.app.schemas.sync import SyncRequest, SyncStatusResponse
from backend.core.config import get_settings
from backend.core.database import get_session_factory
from backend.persistence.repositories.sync_repository import SyncRepository


router = APIRouter()
logger = logging.getLogger(__name__)


def _run_sync_job_inline(run_id: int, source: str, max_results: int, lookback_days: int) -> None:
    """Fallback: run the sync in-process via FastAPI BackgroundTasks (no Redis)."""
    session_factory = get_session_factory()
    session = session_factory()
    try:
        run_model = SyncRepository(session).get_run_model(run_id)
        if run_model is None:
            raise ValueError(f"Sync run `{run_id}` was not found.")
        services = build_service_bundle_for_user_id(session, run_model.user_id)
        services.sync_service.sync_recent_threads(
            run_id=run_id,
            source=source,
            max_results=max_results,
            lookback_days=lookback_days,
        )
        topic = services.settings.gmail_pubsub_topic
        if topic:
            services.sync_service.ensure_watch(topic)
        # After the Gmail run completes, silently sync any other connected accounts
        # (Outlook, iCloud, IMAP). Failures are logged but never abort the Gmail run.
        try:
            supplemental_count = services.sync_service.sync_supplemental_accounts(
                lookback_days=lookback_days,
                max_results=max_results,
            )
            if supplemental_count:
                logger.info(
                    "Sync run %s: %s additional thread(s) from supplemental accounts.",
                    run_id,
                    supplemental_count,
                )
        except Exception:
            logger.warning(
                "Sync run %s: supplemental account sync failed (non-fatal).", run_id, exc_info=True
            )
    except Exception:
        logger.exception("Gmail sync failed")
    finally:
        session.close()


async def _enqueue_sync_job(run_id: int, source: str, max_results: int, lookback_days: int) -> None:
    """Enqueue the sync job via Arq when Redis is configured."""
    import arq
    from backend.jobs.worker import get_redis_settings
    redis = await arq.create_pool(get_redis_settings())
    await redis.enqueue_job("run_sync", run_id, source, max_results, lookback_days)
    await redis.close()


@router.post(
    "/sync",
    response_model=SyncStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_sync(
    payload: SyncRequest,
    background_tasks: BackgroundTasks,
    services: ServiceBundle = Depends(get_service_bundle),
) -> SyncStatusResponse:
    running = services.sync_service.get_running_run()
    if running is not None:
        return SyncStatusResponse.from_domain(running)

    source = payload.source or services.settings.gmail_thread_source
    max_results = payload.max_results or services.settings.gmail_max_results
    lookback_days = payload.lookback_days
    run = services.sync_service.create_run(source)

    if get_settings().redis_url:
        # Worker process is available — enqueue via Arq for full process isolation.
        await _enqueue_sync_job(run.run_id, source, max_results, lookback_days)
        logger.info("Sync run %s enqueued via Arq", run.run_id)
    else:
        # No Redis — fall back to in-process BackgroundTasks (local dev default).
        background_tasks.add_task(
            _run_sync_job_inline,
            run.run_id,
            source,
            max_results,
            lookback_days,
        )
        logger.info("Sync run %s started via BackgroundTasks (no Redis)", run.run_id)

    return SyncStatusResponse.from_domain(run)


@router.get("/sync/runs/latest", response_model=SyncStatusResponse)
def get_latest_sync_run(
    services: ServiceBundle = Depends(get_service_bundle),
) -> SyncStatusResponse:
    result = services.sync_service.get_latest_run_status()
    if result is None:
        raise HTTPException(status_code=404, detail="No sync runs found.")
    return SyncStatusResponse.from_domain(result)


@router.get("/sync/runs/{run_id}", response_model=SyncStatusResponse)
def get_sync_run(
    run_id: int,
    services: ServiceBundle = Depends(get_service_bundle),
) -> SyncStatusResponse:
    result = services.sync_service.get_run_status(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Sync run not found.")
    return SyncStatusResponse.from_domain(result)


@router.post("/sync/runs/{run_id}/cancel", response_model=SyncStatusResponse)
def cancel_sync_run(
    run_id: int,
    services: ServiceBundle = Depends(get_service_bundle),
) -> SyncStatusResponse:
    result = services.sync_service.cancel_run(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Running sync not found.")
    return SyncStatusResponse.from_domain(result)
