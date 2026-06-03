"""Draft endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.app.dependencies.services import ServiceBundle, get_service_bundle
from api.app.schemas.draft import DraftGenerateRequest, DraftGenerateResponse
from backend.providers.ai.base import AIProviderError


def _build_outlook_client_for_user(services: ServiceBundle):
    """Return an OutlookClient loaded with the first active Outlook account
    for the current user, or None if no Outlook account is connected."""
    from backend.core.config import get_settings
    from backend.core.crypto import decrypt_text
    from backend.persistence.repositories.email_account_repository import EmailAccountRepository
    from backend.providers.outlook.client import OutlookClient

    s = get_settings()
    repo = EmailAccountRepository(services.session)
    for model in repo.list_models_for_user(services.current_user.id):
        if model.provider == "outlook" and model.credentials_encrypted:
            credentials_json = decrypt_text(
                model.credentials_encrypted, s.auth_token_encryption_key
            )
            return OutlookClient(
                client_id=s.outlook_client_id or "",
                client_secret=s.outlook_client_secret,
                tenant_id=s.outlook_tenant_id or "common",
                credentials_json=credentials_json,
            )
    return None


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


@router.delete("/threads/{thread_id}/draft", status_code=204)
def delete_draft(
    thread_id: str,
    services: ServiceBundle = Depends(get_service_bundle),
) -> None:
    """Discard the stored draft for a thread without sending it."""
    thread = services.queue_service.get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found.")
    services.review_service.thread_repository.clear_draft(thread_id)
    services.session.commit()


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

    runtime_settings = services.runtime_settings_service.get()

    # ------------------------------------------------------------------ #
    # Route to the correct provider based on the thread ID prefix.        #
    # Outlook threads use "outlook:<conversationId>"; everything else      #
    # is treated as Gmail.                                                 #
    # ------------------------------------------------------------------ #
    if thread_id.startswith("outlook:"):
        # Strip the prefix to get the raw Graph API conversationId.
        conversation_id = thread_id[len("outlook:"):]
        outlook_client = _build_outlook_client_for_user(services)
        if outlook_client is None:
            raise HTTPException(
                status_code=400,
                detail="No Outlook account connected. Please connect one in Settings.",
            )
        try:
            sent_id = outlook_client.send_reply(
                conversation_id=conversation_id,
                to=payload.to,
                subject=payload.subject,
                body=payload.body,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Outlook send failed: {exc}") from exc

        sender_email = outlook_client.get_profile_email() or payload.to

    else:
        # Gmail path (original behaviour).
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
        user_email=sender_email,
    )
    services.session.commit()

    return {"status": "sent", "message_id": sent_id}
