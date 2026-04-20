"""Thin Gmail API client for V3."""

from __future__ import annotations

import base64
import secrets
from datetime import datetime, timedelta
from typing import Any

from backend.core.config import AppSettings
from backend.domain.gmail import GmailConnectionStatus
from backend.domain.thread import InboundEmailMessage


SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class GmailReadonlyClient:
    """Handles Gmail OAuth and basic recent-thread fetches."""

    PAGE_SIZE = 500
    QUERY_BY_SOURCE = {
        "anywhere": "in:anywhere",
        "sent": "in:sent",
        "received": "-in:sent",
    }

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def list_recent_messages(
        self,
        max_results: int | None = None,
        source: str | None = None,
    ) -> list[InboundEmailMessage]:
        service = self._build_service()
        query = self.build_query(source or self.settings.gmail_thread_source)
        message_refs: list[dict[str, Any]] = []
        next_page_token: str | None = None
        limit = max_results or self.settings.gmail_max_results

        while True:
            response = (
                service.users()
                .messages()
                .list(
                    userId="me",
                    maxResults=min(limit, self.PAGE_SIZE),
                    q=query,
                    pageToken=next_page_token,
                )
                .execute()
            )
            message_refs.extend(response.get("messages", []))
            next_page_token = response.get("nextPageToken")
            if not next_page_token or len(message_refs) >= limit:
                break

        messages: list[InboundEmailMessage] = []
        seen_thread_ids: set[str] = set()
        for message_ref in message_refs[:limit]:
            thread_id = message_ref.get("threadId")
            if thread_id:
                if thread_id in seen_thread_ids:
                    continue
                raw_thread = (
                    service.users()
                    .threads()
                    .get(userId="me", id=thread_id, format="full")
                    .execute()
                )
                for raw_message in raw_thread.get("messages", []):
                    messages.append(self._normalize_message(raw_message))
                seen_thread_ids.add(thread_id)
                continue

            raw_message = (
                service.users()
                .messages()
                .get(userId="me", id=message_ref["id"], format="full")
                .execute()
            )
            messages.append(self._normalize_message(raw_message))

        return messages

    def _build_service(self) -> Any:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = self._load_credentials(refresh_if_needed=True, persist=True)
        if not creds or not creds.valid:
            raise RuntimeError(
                "Gmail account is not connected yet. Open the Gmail connect flow first."
            )
        return build("gmail", "v1", credentials=creds)

    def get_connection_status(self, connect_url: str | None = None) -> GmailConnectionStatus:
        credentials_path = self.settings.resolved_gmail_credentials_path
        token_path = self._resolve_existing_token_path() or self.settings.resolved_gmail_token_path
        status = GmailConnectionStatus(
            credentials_configured=credentials_path.exists(),
            connected=False,
            credentials_path=str(credentials_path),
            token_path=str(token_path),
            connect_url=connect_url,
        )

        if not credentials_path.exists():
            status.error_message = "Gmail OAuth credentials file is missing."
            return status

        try:
            creds = self._load_credentials(refresh_if_needed=True, persist=True)
            if not creds or not creds.valid:
                status.error_message = "Gmail account is not connected yet."
                return status

            status.connected = True
            status.email_address = self.get_profile_email()
            return status
        except Exception as exc:
            status.error_message = str(exc)
            return status

    def generate_code_verifier(self) -> str:
        return secrets.token_urlsafe(64)

    def build_authorization_url(
        self,
        redirect_uri: str,
        state: str,
        code_verifier: str,
    ) -> str:
        flow = self._build_flow(
            redirect_uri=redirect_uri,
            state=state,
            code_verifier=code_verifier,
        )
        authorization_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        return authorization_url

    def exchange_code_for_token(
        self,
        redirect_uri: str,
        state: str,
        code: str,
        code_verifier: str,
    ) -> None:
        flow = self._build_flow(
            redirect_uri=redirect_uri,
            state=state,
            code_verifier=code_verifier,
        )
        flow.fetch_token(code=code)
        token_path = self.settings.resolved_gmail_token_path
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(flow.credentials.to_json(), encoding="utf-8")

    def get_profile_email(self) -> str | None:
        service = self._build_service()
        profile = service.users().getProfile(userId="me").execute()
        email_address = str(profile.get("emailAddress") or "").strip()
        return email_address or None

    def _load_credentials(self, refresh_if_needed: bool, persist: bool):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        credentials_path = self.settings.resolved_gmail_credentials_path
        if not credentials_path.exists():
            raise FileNotFoundError(
                "Gmail OAuth credentials file is missing. "
                f"Expected: {credentials_path}"
            )

        token_path = self._resolve_existing_token_path()
        if token_path is None:
            token_path = self.settings.resolved_gmail_token_path

        if not token_path.exists():
            return None

        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        if refresh_if_needed and creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            if persist:
                token_path.write_text(creds.to_json(), encoding="utf-8")
        return creds

    def _resolve_existing_token_path(self):
        for candidate in self.settings.resolved_gmail_token_candidate_paths:
            if candidate.exists():
                return candidate
        return None

    def _build_flow(
        self,
        redirect_uri: str,
        state: str,
        code_verifier: str,
    ):
        from google_auth_oauthlib.flow import InstalledAppFlow

        credentials_path = self.settings.resolved_gmail_credentials_path
        if not credentials_path.exists():
            raise FileNotFoundError(
                "Gmail OAuth credentials file is missing. "
                f"Expected: {credentials_path}"
            )

        flow = InstalledAppFlow.from_client_secrets_file(
            str(credentials_path),
            SCOPES,
            redirect_uri=redirect_uri,
            state=state,
        )
        flow.code_verifier = code_verifier
        return flow

    @classmethod
    def build_query(cls, source: str, now: datetime | None = None) -> str:
        normalized = (source or "anywhere").strip().lower()
        base_query = cls.QUERY_BY_SOURCE.get(normalized, cls.QUERY_BY_SOURCE["anywhere"])
        window_start = cls.rolling_window_start(now)
        return f"{base_query} after:{window_start.strftime('%Y/%m/%d')}"

    @staticmethod
    def rolling_window_start(now: datetime | None = None) -> datetime:
        local_now = (now or datetime.now().astimezone()).astimezone()
        start = local_now - timedelta(days=7)
        return start.replace(hour=0, minute=0, second=0, microsecond=0)

    def _normalize_message(self, message: dict[str, Any]) -> InboundEmailMessage:
        payload = message.get("payload", {})
        headers = {h["name"]: h["value"] for h in payload.get("headers", [])}
        return InboundEmailMessage(
            external_message_id=message.get("id", ""),
            external_thread_id=message.get("threadId", ""),
            subject=headers.get("Subject", ""),
            from_address=headers.get("From", ""),
            to_address=headers.get("To", ""),
            date_header=headers.get("Date", ""),
            snippet=message.get("snippet", ""),
            body_text=self._extract_text(payload),
            label_ids=message.get("labelIds", []),
        )

    def _extract_text(self, payload: dict[str, Any]) -> str:
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
