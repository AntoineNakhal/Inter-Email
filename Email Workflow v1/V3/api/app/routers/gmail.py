"""Gmail connection endpoints."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from api.app.dependencies.services import ServiceBundle, get_service_bundle
from api.app.schemas.gmail import GmailConnectionStatusResponse


router = APIRouter()


@router.get("/gmail/connection", response_model=GmailConnectionStatusResponse)
def get_gmail_connection_status(
    request: Request,
    services: ServiceBundle = Depends(get_service_bundle),
) -> GmailConnectionStatusResponse:
    connect_url = str(request.url_for("start_gmail_connect"))
    status = services.gmail_connection_service.get_status(connect_url=connect_url)
    return GmailConnectionStatusResponse.from_domain(status)


@router.get("/gmail/connect/start", name="start_gmail_connect")
def start_gmail_connect(
    request: Request,
    services: ServiceBundle = Depends(get_service_bundle),
) -> RedirectResponse:
    redirect_uri = str(request.url_for("finish_gmail_connect"))
    try:
        authorization_url = services.gmail_connection_service.build_connect_url(
            redirect_uri=redirect_uri,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(authorization_url, status_code=302)


@router.get("/gmail/connect/callback", name="finish_gmail_connect")
def finish_gmail_connect(
    request: Request,
    state: str,
    code: str,
    services: ServiceBundle = Depends(get_service_bundle),
) -> RedirectResponse:
    redirect_uri = str(request.url_for("finish_gmail_connect"))
    try:
        services.gmail_connection_service.finalize_connection(
            redirect_uri=redirect_uri,
            state=state,
            code=code,
        )
        destination = (
            f"{services.settings.frontend_app_url.rstrip('/')}"
            "/settings?gmail=connected"
        )
    except Exception as exc:
        destination = (
            f"{services.settings.frontend_app_url.rstrip('/')}"
            f"/settings?gmail=error&message={quote(str(exc))}"
        )
    return RedirectResponse(destination, status_code=302)
