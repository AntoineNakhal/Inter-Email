"""Gmail connection endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from api.app.dependencies.auth import get_optional_current_user
from api.app.dependencies.db import get_db_session
from api.app.dependencies.services import build_service_bundle
from api.app.schemas.gmail import GmailConnectionStatusResponse
from backend.core.config import get_settings
from backend.domain.gmail import GmailConnectionStatus
from backend.domain.user import AuthenticatedUser


router = APIRouter()


@router.get("/gmail/connection", response_model=GmailConnectionStatusResponse)
def get_gmail_connection_status(
    request: Request,
    current_user: AuthenticatedUser | None = Depends(get_optional_current_user),
    session: Session = Depends(get_db_session),
) -> GmailConnectionStatusResponse:
    connect_url = str(request.url_for("start_google_auth"))
    if current_user is None:
        settings = get_settings()
        status = GmailConnectionStatus(
            credentials_configured=settings.resolved_gmail_credentials_path.exists(),
            connected=False,
            connect_url=connect_url,
        )
    else:
        services = build_service_bundle(session, current_user)
        status = services.gmail_connection_service.get_status(connect_url=connect_url)
    return GmailConnectionStatusResponse.from_domain(status)


@router.get("/gmail/connect/start", name="start_gmail_connect")
def start_gmail_connect(
    request: Request,
) -> RedirectResponse:
    return RedirectResponse(str(request.url_for("start_google_auth")), status_code=302)


@router.get("/gmail/connect/callback", name="finish_gmail_connect")
def finish_gmail_connect(
    request: Request,
    state: str,
    code: str,
) -> RedirectResponse:
    destination = (
        f"{request.url_for('finish_google_auth')}?state={state}&code={code}"
    )
    return RedirectResponse(destination, status_code=302)
