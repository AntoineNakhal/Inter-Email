"""Authentication endpoints."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from api.app.dependencies.auth import (
    REFRESH_COOKIE_NAME,
    clear_auth_cookies,
    get_auth_service,
    get_current_user,
    set_auth_cookies,
)
from api.app.schemas.auth import AuthenticatedUserResponse
from backend.application.auth_service import AuthService
from backend.core.config import get_settings
from backend.domain.user import AuthenticatedUser


router = APIRouter()


@router.get("/auth/me", response_model=AuthenticatedUserResponse)
def get_authenticated_user(
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUserResponse:
    return AuthenticatedUserResponse.from_domain(user)


@router.get("/auth/google/start", name="start_google_auth")
def start_google_auth(
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
) -> RedirectResponse:
    redirect_uri = str(request.url_for("finish_google_auth"))
    try:
        authorization_url = auth_service.build_login_url(redirect_uri)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(authorization_url, status_code=302)


@router.get("/auth/google/callback", name="finish_google_auth")
def finish_google_auth(
    request: Request,
    state: str,
    code: str,
    auth_service: AuthService = Depends(get_auth_service),
) -> RedirectResponse:
    settings = get_settings()
    redirect_uri = str(request.url_for("finish_google_auth"))
    try:
        session_result = auth_service.finalize_google_login(
            redirect_uri=redirect_uri,
            state=state,
            code=code,
        )
        destination = (
            f"{settings.frontend_app_url.rstrip('/')}/settings?auth=connected"
        )
        response = RedirectResponse(destination, status_code=302)
        set_auth_cookies(
            response,
            access_token=session_result.access_token,
            refresh_token=session_result.refresh_token,
            settings=settings,
        )
        return response
    except Exception as exc:
        destination = (
            f"{settings.frontend_app_url.rstrip('/')}"
            f"/settings?auth=error&message={quote(str(exc))}"
        )
        response = RedirectResponse(destination, status_code=302)
        clear_auth_cookies(response, settings)
        return response


@router.post("/auth/refresh", response_model=AuthenticatedUserResponse)
def refresh_auth_session(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthenticatedUserResponse:
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh session missing.")
    try:
        session_result = auth_service.refresh_access_token(refresh_token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    set_auth_cookies(
        response,
        access_token=session_result.access_token,
        refresh_token=session_result.refresh_token,
        settings=get_settings(),
    )
    return AuthenticatedUserResponse.from_domain(session_result.user)


@router.post("/auth/logout")
def logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
    auth_service: AuthService = Depends(get_auth_service),
) -> dict[str, str]:
    auth_service.logout(refresh_token)
    clear_auth_cookies(response, get_settings())
    return {"status": "signed_out"}
