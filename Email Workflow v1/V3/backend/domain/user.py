"""User and auth-related domain models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class UserRole(str, Enum):
    USER = "user"
    ADMIN = "admin"


class AuthenticatedUser(BaseModel):
    id: int
    email: str
    display_name: str = ""
    role: UserRole = UserRole.USER
    google_subject: str | None = None
    last_login_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN
