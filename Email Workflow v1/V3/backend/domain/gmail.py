"""Gmail connection domain models."""

from __future__ import annotations

from pydantic import BaseModel


class GmailConnectionStatus(BaseModel):
    """Connection state for the current Gmail integration."""

    credentials_configured: bool = False
    connected: bool = False
    email_address: str | None = None
    credentials_path: str = ""
    token_path: str = ""
    connect_url: str | None = None
    error_message: str | None = None
