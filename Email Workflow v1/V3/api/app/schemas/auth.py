"""Auth API schemas."""

from __future__ import annotations

from pydantic import BaseModel

from backend.domain.user import AuthenticatedUser


class AuthenticatedUserResponse(BaseModel):
    id: int
    email: str
    display_name: str
    role: str

    @classmethod
    def from_domain(cls, user: AuthenticatedUser) -> "AuthenticatedUserResponse":
        return cls(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            role=user.role.value,
        )
