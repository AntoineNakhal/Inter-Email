"""Email account connection endpoints.

Lets an authenticated user connect, list, and disconnect email accounts
across any supported provider (Gmail, Outlook, iCloud, IMAP).
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from api.app.dependencies.auth import get_current_user, get_email_account_service
from backend.application.email_account_service import EmailAccountService
from backend.core.config import get_settings
from backend.domain.user import AuthenticatedUser
from backend.persistence.repositories.email_account_repository import EmailAccountRecord


router = APIRouter(prefix="/email-accounts", tags=["email-accounts"])


# ------------------------------------------------------------------ #
# Response schema                                                      #
# ------------------------------------------------------------------ #

class EmailAccountResponse(BaseModel):
    id: int
    provider: str
    email_address: str
    display_name: str | None
    is_active: bool

    @classmethod
    def from_record(cls, r: EmailAccountRecord) -> "EmailAccountResponse":
        return cls(
            id=r.id,
            provider=r.provider,
            email_address=r.email_address,
            display_name=r.display_name,
            is_active=r.is_active,
        )


# ------------------------------------------------------------------ #
# List / disconnect                                                    #
# ------------------------------------------------------------------ #

@router.get("", response_model=list[EmailAccountResponse])
def list_email_accounts(
    user: AuthenticatedUser = Depends(get_current_user),
    service: EmailAccountService = Depends(get_email_account_service),
) -> list[EmailAccountResponse]:
    accounts = service.list_accounts(user.id)
    return [EmailAccountResponse.from_record(a) for a in accounts]


@router.delete("/{account_id}", status_code=204)
def disconnect_email_account(
    account_id: int,
    user: AuthenticatedUser = Depends(get_current_user),
    service: EmailAccountService = Depends(get_email_account_service),
) -> None:
    found = service.disconnect_account(account_id=account_id, user_id=user.id)
    if not found:
        raise HTTPException(status_code=404, detail="Account not found.")


# ------------------------------------------------------------------ #
# Gmail OAuth flow                                                     #
# ------------------------------------------------------------------ #

@router.get("/gmail/connect", name="start_gmail_connect")
def start_gmail_connect(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    service: EmailAccountService = Depends(get_email_account_service),
) -> RedirectResponse:
    redirect_uri = str(request.url_for("finish_gmail_connect"))
    try:
        url = service.build_gmail_connect_url(user.id, redirect_uri)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url, status_code=302)


@router.get("/gmail/callback", name="finish_gmail_connect")
def finish_gmail_connect(
    request: Request,
    state: str,
    code: str,
    user: AuthenticatedUser = Depends(get_current_user),
    service: EmailAccountService = Depends(get_email_account_service),
) -> RedirectResponse:
    settings = get_settings()
    redirect_uri = str(request.url_for("finish_gmail_connect"))
    try:
        service.finalize_gmail_connection(
            user_id=user.id,
            state=state,
            code=code,
            redirect_uri=redirect_uri,
        )
        destination = f"{settings.frontend_app_url.rstrip('/')}/settings?connected=gmail"
    except Exception as exc:
        destination = (
            f"{settings.frontend_app_url.rstrip('/')}"
            f"/settings?error={quote(str(exc))}"
        )
    return RedirectResponse(destination, status_code=302)


# ------------------------------------------------------------------ #
# Outlook OAuth flow                                                   #
# ------------------------------------------------------------------ #

@router.get("/outlook/connect", name="start_outlook_connect")
def start_outlook_connect(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    service: EmailAccountService = Depends(get_email_account_service),
) -> RedirectResponse:
    settings = get_settings()
    if not settings.outlook_client_id:
        raise HTTPException(
            status_code=400,
            detail="Outlook OAuth is not configured. Set OUTLOOK_CLIENT_ID in .env.",
        )
    redirect_uri = str(request.url_for("finish_outlook_connect"))
    try:
        url, _ = service.build_outlook_connect_url(user.id, redirect_uri)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url, status_code=302)


@router.get("/outlook/callback", name="finish_outlook_connect")
def finish_outlook_connect(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    service: EmailAccountService = Depends(get_email_account_service),
) -> RedirectResponse:
    settings = get_settings()
    redirect_uri = str(request.url_for("finish_outlook_connect"))
    # MSAL returns all params in the query string
    auth_response = dict(request.query_params)
    state = auth_response.get("state", "")
    try:
        service.finalize_outlook_connection(
            user_id=user.id,
            state=state,
            auth_response=auth_response,
            redirect_uri=redirect_uri,
        )
        destination = f"{settings.frontend_app_url.rstrip('/')}/settings?connected=outlook"
    except Exception as exc:
        destination = (
            f"{settings.frontend_app_url.rstrip('/')}"
            f"/settings?error={quote(str(exc))}"
        )
    return RedirectResponse(destination, status_code=302)


# ------------------------------------------------------------------ #
# iCloud IMAP                                                          #
# ------------------------------------------------------------------ #

class ICloudConnectRequest(BaseModel):
    email_address: str = Field(..., description="Your @icloud.com / @me.com address")
    app_password: str = Field(..., description="App-specific password from appleid.apple.com")


@router.post("/icloud", response_model=EmailAccountResponse, status_code=201)
def connect_icloud(
    body: ICloudConnectRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    service: EmailAccountService = Depends(get_email_account_service),
) -> EmailAccountResponse:
    try:
        record = service.connect_icloud(
            user_id=user.id,
            email_address=body.email_address,
            app_password=body.app_password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return EmailAccountResponse.from_record(record)


# ------------------------------------------------------------------ #
# Generic IMAP                                                         #
# ------------------------------------------------------------------ #

class ImapConnectRequest(BaseModel):
    host: str = Field(..., description="IMAP server hostname, e.g. imap.gmail.com")
    port: int = Field(993, ge=1, le=65535)
    username: str
    password: str
    use_ssl: bool = True
    display_name: str | None = None


@router.post("/imap", response_model=EmailAccountResponse, status_code=201)
def connect_imap(
    body: ImapConnectRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    service: EmailAccountService = Depends(get_email_account_service),
) -> EmailAccountResponse:
    try:
        record = service.connect_imap(
            user_id=user.id,
            host=body.host,
            port=body.port,
            username=body.username,
            password=body.password,
            use_ssl=body.use_ssl,
            display_name=body.display_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return EmailAccountResponse.from_record(record)
