"""Review and seen-state endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.app.dependencies.services import ServiceBundle, get_service_bundle
from api.app.schemas.review import ReviewRequest, SeenStateRequest


router = APIRouter()


@router.post("/threads/{thread_id}/review")
def save_review(
    thread_id: str,
    payload: ReviewRequest,
    services: ServiceBundle = Depends(get_service_bundle),
) -> dict[str, str]:
    try:
        services.review_service.save_review(thread_id, payload.to_domain())
        services.session.commit()
    except ValueError as exc:
        services.session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "saved"}


@router.post("/threads/{thread_id}/seen")
def mark_seen(
    thread_id: str,
    payload: SeenStateRequest,
    services: ServiceBundle = Depends(get_service_bundle),
) -> dict[str, str]:
    try:
        services.review_service.mark_seen(thread_id, payload.seen)
        services.session.commit()
    except ValueError as exc:
        services.session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "saved"}
