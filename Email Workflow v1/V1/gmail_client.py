"""Thin Gmail API client for read-only message access."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any


SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class GmailReadonlyClient:
    """Handles Gmail authentication and basic message retrieval."""

    def __init__(self, credentials_path: Path, token_path: Path) -> None:
        self.credentials_path = credentials_path
        self.token_path = token_path

    def _build_service(self) -> Any:
        """Authenticate with Google and return a Gmail API service.

        Imports happen inside the method so simple import tests can run even
        before dependencies are installed locally.
        """

        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        if not self.credentials_path.exists():
            raise FileNotFoundError(
                "Gmail OAuth client file was not found. "
                f"Expected: {self.credentials_path}"
            )

        creds = None
        if self.token_path.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        elif not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(self.credentials_path), SCOPES
            )
            creds = flow.run_local_server(port=0)
            self.token_path.parent.mkdir(parents=True, exist_ok=True)
            self.token_path.write_text(creds.to_json(), encoding="utf-8")

        return build("gmail", "v1", credentials=creds)

    def list_recent_messages(self, max_results: int = 10) -> list[dict[str, Any]]:
        """Return raw Gmail messages with enough data for downstream agents."""

        service = self._build_service()
        response = (
            service.users()
            .messages()
            .list(userId="me", maxResults=max_results, q="in:anywhere")
            .execute()
        )
        message_refs = response.get("messages", [])

        messages: list[dict[str, Any]] = []
        for message_ref in message_refs:
            raw_message = (
                service.users()
                .messages()
                .get(userId="me", id=message_ref["id"], format="full")
                .execute()
            )
            messages.append(self._normalize_message(raw_message))

        return messages

    def _normalize_message(self, message: dict[str, Any]) -> dict[str, Any]:
        """Convert a Gmail API response into a smaller, friendlier shape."""

        payload = message.get("payload", {})
        headers = {h["name"]: h["value"] for h in payload.get("headers", [])}

        return {
            "id": message.get("id", ""),
            "thread_id": message.get("threadId", ""),
            "subject": headers.get("Subject", ""),
            "from_address": headers.get("From", ""),
            "to_address": headers.get("To", ""),
            "date": headers.get("Date", ""),
            "snippet": message.get("snippet", ""),
            "body_text": self._extract_text(payload),
            "label_ids": message.get("labelIds", []),
        }

    def _extract_text(self, payload: dict[str, Any]) -> str:
        """Pull a readable text body from Gmail payload parts."""

        body = payload.get("body", {})
        data = body.get("data")
        if data:
            return self._decode_base64(data)

        for part in payload.get("parts", []) or []:
            mime_type = part.get("mimeType", "")
            if mime_type == "text/plain" and part.get("body", {}).get("data"):
                return self._decode_base64(part["body"]["data"])

        return ""

    @staticmethod
    def _decode_base64(value: str) -> str:
        padding = "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(value + padding)
        return decoded.decode("utf-8", errors="ignore")
