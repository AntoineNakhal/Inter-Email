"""Thread and queue endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.app.dependencies.services import ServiceBundle, get_service_bundle
from api.app.schemas.thread import (
    QueueDashboardResponse,
    QueueSummaryResponse,
    ThreadListResponse,
    ThreadResponse,
)


router = APIRouter()


@router.get("/threads", response_model=ThreadListResponse)
def list_threads(
    services: ServiceBundle = Depends(get_service_bundle),
) -> ThreadListResponse:
    threads = services.queue_service.list_threads()
    return ThreadListResponse(
        threads=[ThreadResponse.from_domain(thread) for thread in threads]
    )


@router.get("/threads/{thread_id}", response_model=ThreadResponse)
def get_thread(
    thread_id: str,
    services: ServiceBundle = Depends(get_service_bundle),
) -> ThreadResponse:
    thread = services.queue_service.get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found.")
    return ThreadResponse.from_domain(thread)


@router.get("/queue/summary", response_model=QueueDashboardResponse)
def get_queue_dashboard(
    services: ServiceBundle = Depends(get_service_bundle),
) -> QueueDashboardResponse:
    threads = services.queue_service.list_threads()
    summary = services.queue_service.summarize_threads(threads)
    return QueueDashboardResponse(
        threads=[ThreadResponse.from_domain(thread) for thread in threads],
        summary=QueueSummaryResponse.from_domain(summary),
    )
