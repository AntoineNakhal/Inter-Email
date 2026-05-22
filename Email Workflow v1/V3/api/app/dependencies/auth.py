"""Auth dependencies and cookie helpers."""

from __future__ import annotations

from fastapi import Cookie, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from api.app.dependencies.db import get_db_session
from backend.application.auth_service import AuthService
from backend.application.email_account_service import EmailAccountService, OAuthStateStore
from backend.core.config import AppSettings, get_settings
from backend.domain.user import AuthenticatedUser
from backend.persistence.repositories.user_repository import UserRepository


ACCESS_COOKIE_NAME = "inter_email_access_token"
REFRESH_COOKIE_NAME = "inter_email_refresh_token"

# Module-level singletons — these are stateless (settings) or in-memory stores
# with TTL-based eviction; safe to keep as globals for a single-process deploy.
_OAUTH_STATE_STORE = OAuthStateStore()


def build_auth_service(session: Session) -> AuthService:
    return AuthService(
        settings=get_settings(),
        user_repository=UserRepository(session),
    )


def get_auth_service(
    session: Session = Depends(get_db_session),
) -> AuthService:
    return build_auth_service(session)


def get_email_account_service(
    session: Session = Depends(get_db_session),
) -> EmailAccountService:
    return EmailAccountService(
        settings=get_settings(),
        session=session,
        state_store=_OAUTH_STATE_STORE,
    )


def get_current_user(
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE_NAME),
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthenticatedUser:
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    try:
        return auth_service.get_user_from_access_token(access_token)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc


def get_optional_current_user(
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE_NAME),
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthenticatedUser | None:
    if not access_token:
        return None
    try:
        return auth_service.get_user_from_access_token(access_token)
    except Exception:
        return None


def set_auth_cookies(
    response: Response,
    *,
    access_token: str,
    refresh_token: str,
    settings: AppSettings,
) -> None:
    cookie_kwargs = _cookie_kwargs(settings)
    response.set_cookie(
        ACCESS_COOKIE_NAME,
        access_token,
        max_age=settings.auth_access_token_minutes * 60,
        httponly=True,
        samesite="lax",
        path="/",
        **cookie_kwargs,
    )
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        refresh_token,
        max_age=settings.auth_refresh_token_days * 24 * 60 * 60,
        httponly=True,
        samesite="lax",
        path="/",
        **cookie_kwargs,
    )


def clear_auth_cookies(response: Response, settings: AppSettings) -> None:
    cookie_kwargs = _cookie_kwargs(settings)
    response.delete_cookie(ACCESS_COOKIE_NAME, path="/", **cookie_kwargs)
    response.delete_cookie(REFRESH_COOKIE_NAME, path="/", **cookie_kwargs)


def _cookie_kwargs(settings: AppSettings) -> dict[str, object]:
    values: dict[str, object] = {"secure": settings.auth_cookie_secure}
    if settings.auth_cookie_domain.strip():
        values["domain"] = settings.auth_cookie_domain.strip()
    return values
