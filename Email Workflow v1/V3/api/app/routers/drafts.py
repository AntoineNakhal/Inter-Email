"""Draft endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.app.dependencies.services import ServiceBundle, get_service_bundle
from api.app.schemas.draft import DraftGenerateRequest, DraftGenerateResponse


router = APIRouter()


@router.get("/threads/{thread_id}/draft", response_model=DraftGenerateResponse | None)
def get_latest_draft(
    thread_id: str,
    services: ServiceBundle = Depends(get_service_bundle),
) -> DraftGenerateResponse | None:
    draft = services.draft_service.latest_draft(thread_id)
    if draft is None:
        return None
    return DraftGenerateResponse.from_domain(draft)


@router.post("/threads/{thread_id}/draft", response_model=DraftGenerateResponse)
def generate_draft(
    thread_id: str,
    payload: DraftGenerateRequest,
    services: ServiceBundle = Depends(get_service_bundle),
) -> DraftGenerateResponse:
    try:
        draft = services.draft_service.generate_draft(
            external_thread_id=thread_id,
            selected_date=payload.selected_date,
            attachment_names=payload.attachment_names,
            user_instructions=payload.user_instructions,
        )
        services.session.commit()
    except ValueError as exc:
        services.session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DraftGenerateResponse.from_domain(draft)
