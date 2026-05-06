"""Pydantic schemas for the Gmail Pub/Sub push webhook."""

from __future__ import annotations

from pydantic import BaseModel


class PubSubMessage(BaseModel):
    """A single Pub/Sub message envelope as sent by Google."""

    # Base64url-encoded JSON: {"emailAddress": "...", "historyId": "..."}
    data: str
    messageId: str | None = None
    publishTime: str | None = None
    attributes: dict[str, str] | None = None


class PubSubPushPayload(BaseModel):
    """The top-level payload posted to a Pub/Sub push endpoint."""

    message: PubSubMessage
    subscription: str | None = None


class GmailPushData(BaseModel):
    """The decoded content of PubSubMessage.data.

    Google sends this as base64url(json({"emailAddress":..., "historyId":...})).
    historyId is the *latest* historyId in Gmail — NOT the startHistoryId.
    We use our persisted gmail_history_id as start and this just signals "fetch now".
    """

    emailAddress: str = ""
    historyId: str = ""
