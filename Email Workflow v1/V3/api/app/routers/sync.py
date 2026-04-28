"""Sync endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from api.app.dependencies.services import build_service_bundle, get_service_bundle
from api.app.dependencies.services import ServiceBundle
from api.app.schemas.sync import SyncRequest, SyncStatusResponse
from backend.core.database import get_session_factory


router = APIRouter()
logger = logging.getLogger(__name__)


def _run_sync_job(run_id: int, source: str, max_results: int, lookback_days: int) -> None:
    session_factory = get_session_factory()
    session = session_factory()
    try:
        services = build_service_bundle(session)
        services.sync_service.sync_recent_threads(
            run_id=run_id,
            source=source,
            max_results=max_results,
            lookback_days=lookback_days,
        )
    except Exception:
        logger.exception("Gmail sync failed")
    finally:
        session.close()


@router.post(
    "/sync",
    response_model=SyncStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def run_sync(
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
    background_tasks.add_task(
        _run_sync_job,
        run.run_id,
        source,
        max_results,
        lookback_days,
    )
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
