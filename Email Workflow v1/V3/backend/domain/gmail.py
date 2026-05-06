"""Gmail connection domain models."""

from __future__ import annotations

from pydantic import BaseModel


class GmailConnectionStatus(BaseModel):
    """Connection state for the current Gmail integration."""

    credentials_configured: bool = False
    connected: bool = False
    email_address: str | None = None
    # Human-readable display name pulled from the Gmail sendAs profile
    # (e.g. "Antoine Nakhal"). Used to sign drafts correctly without
    # letting the AI infer the name from the email address prefix.
    display_name: str | None = None
    credentials_path: str = ""
    token_path: str = ""
    connect_url: str | None = None
    error_message: str | None = None
