"""Thread and queue endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from backend.domain.thread import AnalysisStatus

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


@router.post("/threads/{thread_id}/analyze", response_model=ThreadResponse)
def analyze_thread(
    thread_id: str,
    services: ServiceBundle = Depends(get_service_bundle),
) -> ThreadResponse:
    """Force re-analysis of a single thread using the active AI provider."""
    thread = services.queue_service.get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found.")

    # Force the thread through AI regardless of relevance score.
    thread.included_in_ai = True
    thread.analysis_status = AnalysisStatus.PENDING

    mailbox_email = services.runtime_settings_service.get().gmail_mailbox_email.strip() or None
    analyzed = services.analysis_service.analyze_threads(
        [thread],
        user_email=mailbox_email,
    )
    services.session.commit()

    updated = services.queue_service.get_thread(thread_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Thread not found after analysis.")
    return ThreadResponse.from_domain(updated)


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
