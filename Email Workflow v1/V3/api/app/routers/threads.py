"""Thread and queue endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from backend.domain.thread import AnalysisStatus
from backend.domain.override import ThreadOverride
from backend.domain.thread import RelevanceBucket, TriageCategory, UrgencyLevel
from backend.persistence.repositories.override_repository import ThreadOverrideRepository

from api.app.dependencies.services import ServiceBundle, get_service_bundle
from api.app.schemas.thread import (
    QueueDashboardResponse,
    QueueSummaryResponse,
    ThreadListResponse,
    ThreadOverrideRequest,
    ThreadOverrideResponse,
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


@router.put("/threads/{thread_id}/override", response_model=ThreadOverrideResponse)
def save_override(
    thread_id: str,
    payload: ThreadOverrideRequest,
    services: ServiceBundle = Depends(get_service_bundle),
) -> ThreadOverrideResponse:
    """Save user manual overrides for a thread's analysis fields.

    Overrides are passed as soft hints to the AI on next re-analysis.
    The AI may disagree — disagreements are tracked in analysis.ai_override_disagreements.
    """
    thread = services.queue_service.get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found.")

    repo = ThreadOverrideRepository(services.session)
    # Resolve the DB thread id from the external thread id
    from sqlalchemy import select
    from backend.persistence.models.thread import EmailThreadModel
    model = services.session.scalar(
        select(EmailThreadModel).where(
            EmailThreadModel.external_thread_id == thread_id
        )
    )
    if model is None:
        raise HTTPException(status_code=404, detail="Thread not found.")

    override = ThreadOverride(
        category=TriageCategory(payload.category) if payload.category else None,
        urgency=UrgencyLevel(payload.urgency) if payload.urgency else None,
        needs_action_today=payload.needs_action_today,
        waiting_on_us=payload.waiting_on_us,
        needs_next_action=payload.needs_next_action,
        should_draft_reply=payload.should_draft_reply,
        relevance_bucket=RelevanceBucket(payload.relevance_bucket) if payload.relevance_bucket else None,
        notes=payload.notes,
    )
    saved = repo.upsert(thread_id=model.id, user_id=services.current_user.id, override=override)
    services.session.commit()

    return ThreadOverrideResponse(
        category=saved.category.value if saved.category else None,
        urgency=saved.urgency.value if saved.urgency else None,
        needs_action_today=saved.needs_action_today,
        waiting_on_us=saved.waiting_on_us,
        needs_next_action=saved.needs_next_action,
        should_draft_reply=saved.should_draft_reply,
        relevance_bucket=saved.relevance_bucket.value if saved.relevance_bucket else None,
        notes=saved.notes,
        overridden_at=saved.overridden_at,
        updated_at=saved.updated_at,
    )


@router.delete("/threads/{thread_id}/override", status_code=204)
def delete_override(
    thread_id: str,
    services: ServiceBundle = Depends(get_service_bundle),
) -> None:
    """Remove all user overrides for a thread — AI values will be used exclusively."""
    from sqlalchemy import select
    from backend.persistence.models.thread import EmailThreadModel
    model = services.session.scalar(
        select(EmailThreadModel).where(
            EmailThreadModel.external_thread_id == thread_id
        )
    )
    if model is None:
        raise HTTPException(status_code=404, detail="Thread not found.")

    repo = ThreadOverrideRepository(services.session)
    repo.delete(thread_id=model.id, user_id=services.current_user.id)
    services.session.commit()


@router.post("/threads/{thread_id}/split", response_model=list[ThreadResponse])
def split_thread(
    thread_id: str,
    services: ServiceBundle = Depends(get_service_bundle),
) -> list[ThreadResponse]:
    """Split a merged thread back into its original Gmail threads.

    Only available when the thread was merged from multiple Gmail threads
    (grouping_reason != 'gmail_thread_id' and len(source_thread_ids) > 1).
    """
    try:
        new_threads = services.thread_repository.split_thread(
            external_thread_id=thread_id,
            user_id=services.current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    services.session.commit()
    return [ThreadResponse.from_domain(t) for t in new_threads]


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
