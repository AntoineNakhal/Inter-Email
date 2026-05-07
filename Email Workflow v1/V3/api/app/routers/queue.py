"""Queue endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from api.app.dependencies.services import ServiceBundle, get_service_bundle
from api.app.schemas.thread import QueueDashboardResponse, QueueSummaryResponse, ThreadResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/queue/summary", response_model=QueueDashboardResponse)
def get_queue_summary(
    services: ServiceBundle = Depends(get_service_bundle),
) -> QueueDashboardResponse:
    """Return the sorted thread list plus an AI-generated queue summary."""
    threads = services.queue_service.list_threads()
    summary = services.queue_service.summarize_threads(threads)
    return QueueDashboardResponse(
        threads=[ThreadResponse.from_domain(t) for t in threads],
        summary=QueueSummaryResponse.from_domain(summary),
    )
