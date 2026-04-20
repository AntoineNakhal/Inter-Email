"""Gmail connection API schemas."""

from __future__ import annotations

from pydantic import BaseModel

from backend.domain.gmail import GmailConnectionStatus


class GmailConnectionStatusResponse(BaseModel):
    credentials_configured: bool
    connected: bool
    email_address: str | None = None
    credentials_path: str
    token_path: str
    connect_url: str | None = None
    error_message: str | None = None

    @classmethod
    def from_domain(
        cls,
        status: GmailConnectionStatus,
    ) -> "GmailConnectionStatusResponse":
        return cls(**status.model_dump())
