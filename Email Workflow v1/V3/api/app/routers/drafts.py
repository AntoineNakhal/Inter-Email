"""Draft endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.app.dependencies.services import ServiceBundle, get_service_bundle
from api.app.schemas.draft import DraftGenerateRequest, DraftGenerateResponse
from backend.providers.ai.base import AIProviderError


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
    except AIProviderError as exc:
        services.session.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return DraftGenerateResponse.from_domain(draft)


class SendDraftRequest(BaseModel):
    subject: str
    body: str
    to: str


@router.post("/threads/{thread_id}/draft/send")
def send_draft(
    thread_id: str,
    payload: SendDraftRequest,
    services: ServiceBundle = Depends(get_service_bundle),
) -> dict[str, str]:
    thread = services.queue_service.get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found.")

    gmail_client = services.sync_service.gmail_client
    try:
        signature = gmail_client.get_signature()
        sent_id = gmail_client.send_reply(
            thread_id=thread_id,
            to=payload.to,
            subject=payload.subject,
            body=payload.body,
            signature_html=signature,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Gmail send failed: {exc}") from exc

    runtime_settings = services.runtime_settings_service.get()
    sender_email = runtime_settings.gmail_mailbox_email.strip() or gmail_client.get_profile_email() or "me"
    updated_thread = services.review_service.thread_repository.append_outgoing_message(
        external_thread_id=thread_id,
        external_message_id=sent_id,
        sender=sender_email,
        recipients=[payload.to],
        subject=payload.subject,
        body=payload.body,
        sent_at=datetime.now(timezone.utc),
    )
    services.review_service.thread_repository.clear_draft(thread_id)

    updated_thread.included_in_ai = True
    services.analysis_service.analyze_threads(
        [updated_thread],
        user_email=runtime_settings.gmail_mailbox_email.strip() or None,
    )
    services.session.commit()

    return {"status": "sent", "message_id": sent_id}
