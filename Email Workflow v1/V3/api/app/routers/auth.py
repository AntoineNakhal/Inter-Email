"""Authentication endpoints — email/password auth."""

from __future__ import annotations

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, Field

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


# ------------------------------------------------------------------ #
# Request schemas (local to this router — small enough to inline)      #
# ------------------------------------------------------------------ #

class RegisterRequest(BaseModel):
    email: str
    password: str = Field(..., min_length=8)
    display_name: str = Field(..., min_length=1, max_length=255)


class LoginRequest(BaseModel):
    email: str
    password: str


# ------------------------------------------------------------------ #
# Endpoints                                                            #
# ------------------------------------------------------------------ #

@router.post("/auth/register", response_model=AuthenticatedUserResponse, status_code=201)
def register(
    body: RegisterRequest,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthenticatedUserResponse:
    """Create a new user account and open a session."""
    try:
        result = auth_service.register(
            email=body.email,
            password=body.password,
            display_name=body.display_name,
        )
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    settings = get_settings()
    set_auth_cookies(
        response,
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        settings=settings,
    )
    return AuthenticatedUserResponse.from_domain(result.user)


@router.post("/auth/login", response_model=AuthenticatedUserResponse)
def login(
    body: LoginRequest,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthenticatedUserResponse:
    """Authenticate with email + password and open a session."""
    try:
        result = auth_service.login(email=body.email, password=body.password)
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    settings = get_settings()
    set_auth_cookies(
        response,
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        settings=settings,
    )
    return AuthenticatedUserResponse.from_domain(result.user)


@router.get("/auth/me", response_model=AuthenticatedUserResponse)
def get_authenticated_user(
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUserResponse:
    return AuthenticatedUserResponse.from_domain(user)


@router.post("/auth/refresh", response_model=AuthenticatedUserResponse)
def refresh_auth_session(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthenticatedUserResponse:
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh session missing.")
    try:
        result = auth_service.refresh_access_token(refresh_token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    set_auth_cookies(
        response,
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        settings=get_settings(),
    )
    return AuthenticatedUserResponse.from_domain(result.user)


@router.post("/auth/logout")
def logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
    auth_service: AuthService = Depends(get_auth_service),
) -> dict[str, str]:
    auth_service.logout(refresh_token)
    clear_auth_cookies(response, get_settings())
    return {"status": "signed_out"}
