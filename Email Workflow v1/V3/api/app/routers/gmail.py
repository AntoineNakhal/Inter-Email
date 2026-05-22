"""Gmail connection status endpoint.

The connect/callback flow has moved to /email-accounts/gmail/connect
and /email-accounts/gmail/callback. This router only exposes the
connection status read used by the Settings page.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from api.app.dependencies.auth import get_current_user, get_email_account_service
from api.app.dependencies.db import get_db_session
from api.app.schemas.gmail import GmailConnectionStatusResponse
from backend.application.email_account_service import EmailAccountService
from backend.core.config import get_settings
from backend.domain.gmail import GmailConnectionStatus
from backend.domain.user import AuthenticatedUser


router = APIRouter()


@router.get("/gmail/connection", response_model=GmailConnectionStatusResponse)
def get_gmail_connection_status(
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: EmailAccountService = Depends(get_email_account_service),
) -> GmailConnectionStatusResponse:
    """Return Gmail connection status for the current user.

    Checks the new email_accounts table first, then falls back to the
    legacy gmail_token_encrypted field so existing users aren't broken.
    """
    settings = get_settings()
    connect_url = str(request.url_for("start_gmail_connect"))

    # Check new email_accounts table
    accounts = service.list_accounts(current_user.id)
    gmail_accounts = [a for a in accounts if a.provider == "gmail"]

    if gmail_accounts:
        acc = gmail_accounts[0]
        status = GmailConnectionStatus(
            credentials_configured=settings.resolved_gmail_credentials_path.exists(),
            connected=True,
            email_address=acc.email_address,
            display_name=acc.display_name,
            connect_url=connect_url,
        )
    else:
        status = GmailConnectionStatus(
            credentials_configured=settings.resolved_gmail_credentials_path.exists(),
            connected=False,
            connect_url=connect_url,
        )

    return GmailConnectionStatusResponse.from_domain(status)
