"""Thin Gmail API client for V3."""

from __future__ import annotations

import base64
import email as email_lib
import logging
import json
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from backend.core.config import AppSettings
from backend.core.email_text import clean_email_body, clean_email_snippet
from backend.domain.gmail import GmailConnectionStatus
from backend.domain.thread import InboundEmailMessage


logger = logging.getLogger(__name__)


class HistoryExpiredError(Exception):
    """The stored Gmail historyId is too old; fall back to a full fetch.

    Gmail retains history for approximately 7 days. If the last sync ran more
    than 7 days ago, or the historyId was never stored, this error is raised
    and the caller should perform a full rolling-window fetch to re-bootstrap
    the cursor.
    """


SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


class GmailReadonlyClient:
    """Handles Gmail OAuth and basic recent-thread fetches."""

    PAGE_SIZE = 500
    # -in:draft excluded globally — we never want draft messages.
    QUERY_BY_SOURCE = {
        "anywhere": "in:anywhere -in:draft",
        "sent": "in:sent -in:draft",
        "received": "-in:sent -in:draft",
    }

    def __init__(
        self,
        settings: AppSettings,
        *,
        credentials_json: str | None = None,
        persist_credentials: Callable[[str], None] | None = None,
    ) -> None:
        self.settings = settings
        self.credentials_json = credentials_json
        self.persist_credentials = persist_credentials

    def list_recent_messages(
        self,
        max_results: int | None = None,
        source: str | None = None,
        lookback_days: int = 7,
        known_message_ids: set[str] | None = None,
    ) -> list[InboundEmailMessage]:
        """Fetch Gmail messages, skipping threads with no new activity.

        ``known_message_ids`` should be the set of message IDs already stored
        in the local DB. Any thread whose every message ref is already known
        is skipped entirely — no ``threads.get`` call is made for it.
        Draft messages (DRAFT label) are filtered out at the message level.
        """
        service = self._build_service()
        query = self.build_query(
            source or self.settings.gmail_thread_source,
            lookback_days=lookback_days,
        )
        limit = max_results or self.settings.gmail_max_results
        known = known_message_ids or set()

        # Step 1: Collect message refs (cheap list call, no body fetched yet).
        message_refs: list[dict[str, Any]] = []
        next_page_token: str | None = None
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

        # Step 2: Group message refs by thread_id so we can detect new activity
        # before paying for a threads.get call.
        thread_message_ids: dict[str, list[str]] = {}
        for ref in message_refs[:limit]:
            thread_id = ref.get("threadId") or ref.get("id")
            message_id = ref.get("id")
            if thread_id and message_id:
                thread_message_ids.setdefault(thread_id, []).append(message_id)

        # Step 3: Fetch full thread details — skip threads with no new messages.
        messages: list[InboundEmailMessage] = []
        seen_message_ids: set[str] = set()
        for thread_id, ref_message_ids in thread_message_ids.items():
            if known and all(mid in known for mid in ref_message_ids):
                # Every message in this thread's refs is already in the DB.
                # The thread has not changed — no fetch needed.
                continue
            raw_thread = (
                service.users()
                .threads()
                .get(userId="me", id=thread_id, format="full")
                .execute()
            )
            for raw_message in raw_thread.get("messages", []):
                self._append_unique_message(messages, seen_message_ids, raw_message)

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
        token_path = (
            "database"
            if self.credentials_json
            else self._resolve_existing_token_path() or self.settings.resolved_gmail_token_path
        )
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
            status.display_name = self.get_profile_name()
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
            prompt="consent",
        )
        return authorization_url

    def exchange_code_for_token(
        self,
        redirect_uri: str,
        state: str,
        code: str,
        code_verifier: str,
    ) -> str:
        flow = self._build_flow(
            redirect_uri=redirect_uri,
            state=state,
            code_verifier=code_verifier,
        )
        flow.fetch_token(code=code)
        credentials_json = flow.credentials.to_json()
        self.credentials_json = credentials_json
        if self.persist_credentials is not None:
            self.persist_credentials(credentials_json)
        else:
            token_path = self.settings.resolved_gmail_token_path
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(credentials_json, encoding="utf-8")
        return credentials_json

    def get_signature(self) -> str:
        """Return the HTML signature of the default send-as address, or empty string."""
        try:
            service = self._build_service()
            result = service.users().settings().sendAs().list(userId="me").execute()
            send_as_list = result.get("sendAs", [])
            default = next((s for s in send_as_list if s.get("isDefault")), None)
            if default is None and send_as_list:
                default = send_as_list[0]
            return default.get("signature", "") if default else ""
        except Exception:
            return ""

    def send_reply(
        self,
        thread_id: str,
        to: str,
        subject: str,
        body: str,
        signature_html: str = "",
    ) -> str:
        """Send an email reply in the given Gmail thread. Returns the sent message ID."""
        service = self._build_service()
        sender_email = self.get_profile_email() or "me"

        # Build a plain-text + HTML multipart message.
        msg = MIMEMultipart("alternative")
        msg["To"] = to
        msg["From"] = sender_email
        msg["Subject"] = subject

        # Plain text — strip signature HTML for the text part.
        plain_body = body.strip()
        msg.attach(MIMEText(plain_body, "plain", "utf-8"))

        # HTML part — append signature if available.
        body_html = plain_body.replace("\n", "<br>")
        if signature_html:
            full_html = f"<div>{body_html}</div><br><div class='gmail_signature'>{signature_html}</div>"
        else:
            full_html = f"<div>{body_html}</div>"
        msg.attach(MIMEText(full_html, "html", "utf-8"))

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        sent = (
            service.users()
            .messages()
            .send(userId="me", body={"raw": raw, "threadId": thread_id})
            .execute()
        )
        return sent.get("id", "")

    def get_profile_email(self) -> str | None:
        service = self._build_service()
        profile = service.users().getProfile(userId="me").execute()
        email_address = str(profile.get("emailAddress") or "").strip()
        return email_address or None

    def get_current_history_id(self) -> str:
        """Return the current historyId for the connected account.

        This is the value to persist after a full-fetch bootstrap so the next
        sync can use the incremental history path. The users.getProfile endpoint
        is the cheapest way to get it — no message data is transferred.
        """
        service = self._build_service()
        profile = service.users().getProfile(userId="me").execute()
        return str(profile.get("historyId") or "")

    # ------------------------------------------------------------------
    # Label-based source filters for the history path.
    # mirrors the query strings in QUERY_BY_SOURCE for the polling path.
    # ------------------------------------------------------------------
    _HISTORY_EXCLUDE_LABELS: frozenset[str] = frozenset({"DRAFT", "TRASH", "SPAM"})
    _HISTORY_SOURCE_REQUIRE: dict[str, frozenset[str]] = {
        "sent": frozenset({"SENT"}),
        "received": frozenset({"INBOX"}),
    }

    def list_messages_since_history(
        self,
        start_history_id: str,
        source: str = "anywhere",
        max_results: int | None = None,
    ) -> tuple[list[InboundEmailMessage], str, set[str]]:
        """Return only messages changed since *start_history_id*.

        Uses the Gmail users.history.list API, which is far cheaper than a
        full rolling-window fetch for accounts that sync frequently.

        Returns:
            messages:          full InboundEmailMessage objects for added /
                               modified messages (source-filtered, no drafts).
            new_history_id:    the latest historyId to persist after this run.
            deleted_thread_ids: Gmail thread IDs where at least one message was
                               permanently deleted. Callers use this to clean up
                               local threads that no longer exist in Gmail.

        Raises:
            HistoryExpiredError: start_history_id is too old (> ~7 days) or
                                 otherwise invalid. The caller should fall back
                                 to list_recent_messages() and re-bootstrap.
        """
        service = self._build_service()
        limit = max_results or self.settings.gmail_max_results
        source_normalized = (source or "anywhere").strip().lower()

        added_thread_ids: set[str] = set()
        deleted_thread_ids: set[str] = set()
        new_history_id = start_history_id  # overwritten once we get a response
        total_history_records = 0
        next_page_token: str | None = None

        try:
            while True:
                request_kwargs: dict[str, Any] = {
                    "userId": "me",
                    "startHistoryId": start_history_id,
                    "historyTypes": ["messageAdded", "messageDeleted"],
                }
                if next_page_token:
                    request_kwargs["pageToken"] = next_page_token

                response = service.users().history().list(**request_kwargs).execute()

                # historyId is present even when the history array is empty.
                if response.get("historyId"):
                    new_history_id = str(response["historyId"])

                for record in response.get("history", []):
                    for added in record.get("messagesAdded", []):
                        msg = added.get("message", {})
                        label_ids: list[str] = msg.get("labelIds") or []
                        # Skip messages excluded globally (drafts, trash, spam).
                        if self._HISTORY_EXCLUDE_LABELS & set(label_ids):
                            continue
                        # Apply source filter via label presence.
                        required = self._HISTORY_SOURCE_REQUIRE.get(source_normalized)
                        if required and not (required & set(label_ids)):
                            continue
                        thread_id = msg.get("threadId")
                        if thread_id:
                            added_thread_ids.add(thread_id)

                    for deleted in record.get("messagesDeleted", []):
                        msg = deleted.get("message", {})
                        thread_id = msg.get("threadId")
                        if thread_id:
                            deleted_thread_ids.add(thread_id)

                total_history_records += len(response.get("history", []))
                next_page_token = response.get("nextPageToken")
                if not next_page_token or total_history_records >= limit:
                    break

        except HistoryExpiredError:
            raise
        except Exception as exc:
            err_lower = str(exc).lower()
            if (
                "404" in err_lower
                or "invalid history" in err_lower
                or "starthistoryid" in err_lower
                or "start_history" in err_lower
            ):
                raise HistoryExpiredError(
                    f"Gmail historyId {start_history_id!r} has expired or is invalid."
                ) from exc
            raise

        logger.info(
            "history.list returned %s records — added threads: %s, deleted threads: %s",
            total_history_records,
            len(added_thread_ids),
            len(deleted_thread_ids),
        )

        # For threads with deletions that also had additions (e.g., a SEND
        # triggered a deletion of a draft version), the addition wins — we
        # re-fetch the thread and get its current state. For deletion-only
        # threads we still re-fetch; if Gmail returns 404, the thread is gone.
        threads_to_fetch = added_thread_ids | deleted_thread_ids

        messages: list[InboundEmailMessage] = []
        seen_message_ids: set[str] = set()

        for thread_id in threads_to_fetch:
            try:
                raw_thread = (
                    service.users()
                    .threads()
                    .get(userId="me", id=thread_id, format="full")
                    .execute()
                )
                for raw_message in raw_thread.get("messages", []):
                    self._append_unique_message(messages, seen_message_ids, raw_message)
            except Exception as exc:
                if "404" in str(exc):
                    logger.debug(
                        "Thread %s not found in Gmail (fully deleted).", thread_id
                    )
                else:
                    logger.warning(
                        "Failed to fetch thread %s during incremental sync: %s",
                        thread_id,
                        exc,
                    )

        return messages, new_history_id, deleted_thread_ids

    def register_watch(self, topic: str) -> tuple[str, "datetime"]:
        """Register a Pub/Sub push watch on this Gmail account.

        Calls users.watch() and returns (resource_id, expiry_utc).
        The caller should persist both values and call this again before
        expiry_utc (Gmail guarantees at most 7 days per watch).

        Args:
            topic: full Pub/Sub topic name, e.g.
                   "projects/my-project/topics/gmail-notifications"

        Returns:
            resource_id: opaque watch ID used to call stop_watch() later.
            expiry_utc:  UTC datetime when the watch expires.
        """
        from datetime import datetime, timezone

        service = self._build_service()
        response = service.users().watch(
            userId="me",
            body={
                "topicName": topic,
                # Listen for all inbox and sent changes.
                "labelIds": ["INBOX", "SENT"],
            },
        ).execute()

        resource_id = str(response.get("id") or "")
        # Gmail returns expiration as a Unix timestamp in milliseconds.
        expiry_ms = int(response.get("expiration") or 0)
        expiry_utc = (
            datetime.fromtimestamp(expiry_ms / 1000, tz=timezone.utc)
            if expiry_ms
            else datetime.now(timezone.utc)
        )
        return resource_id, expiry_utc

    def stop_watch(self) -> None:
        """Stop all push notifications for this Gmail account.

        Calls users.stop(). Safe to call even if no watch is active.
        """
        try:
            service = self._build_service()
            service.users().stop(userId="me").execute()
        except Exception as exc:
            logger.warning("users.stop() failed (may be no active watch): %s", exc)

    def get_profile_name(self) -> str | None:
        """Return the display name of the default send-as address, or None."""
        try:
            service = self._build_service()
            result = service.users().settings().sendAs().list(userId="me").execute()
            send_as_list = result.get("sendAs", [])
            default = next((s for s in send_as_list if s.get("isDefault")), None)
            if default is None and send_as_list:
                default = send_as_list[0]
            name = str(default.get("displayName") or "").strip() if default else ""
            return name or None
        except Exception:
            return None

    def _load_credentials(self, refresh_if_needed: bool, persist: bool):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        credentials_path = self.settings.resolved_gmail_credentials_path
        if not credentials_path.exists():
            raise FileNotFoundError(
                "Gmail OAuth credentials file is missing. "
                f"Expected: {credentials_path}"
            )

        token_path = None
        if self.credentials_json:
            creds = Credentials.from_authorized_user_info(
                json.loads(self.credentials_json),
                SCOPES,
            )
        else:
            token_path = self._resolve_existing_token_path()
            if token_path is None:
                token_path = self.settings.resolved_gmail_token_path

            if not token_path.exists():
                return None

            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        if refresh_if_needed and creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            if persist:
                refreshed_json = creds.to_json()
                self.credentials_json = refreshed_json
                if self.persist_credentials is not None:
                    self.persist_credentials(refreshed_json)
                elif token_path is not None:
                    token_path.write_text(refreshed_json, encoding="utf-8")
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
    def build_query(
        cls,
        source: str,
        now: datetime | None = None,
        lookback_days: int = 7,
    ) -> str:
        normalized = (source or "anywhere").strip().lower()
        base_query = cls.QUERY_BY_SOURCE.get(normalized, cls.QUERY_BY_SOURCE["anywhere"])
        window_start = cls.rolling_window_start(now, lookback_days=lookback_days)
        return f"{base_query} after:{window_start.strftime('%Y/%m/%d')}"

    @staticmethod
    def rolling_window_start(
        now: datetime | None = None,
        lookback_days: int = 7,
    ) -> datetime:
        local_now = (now or datetime.now().astimezone()).astimezone()
        safe_lookback_days = max(1, lookback_days)
        start = local_now - timedelta(days=safe_lookback_days)
        return start.replace(hour=0, minute=0, second=0, microsecond=0)

    # Strings that, when present anywhere in the From address, indicate an
    # automated/transactional sender. Checked with `in` so they match both
    # prefixes (noreply@) and substrings (invoice+statements@, billing.co@).
    _SERVICE_SENDER_PREFIXES = (
        "noreply", "no-reply", "donotreply", "do-not-reply",
        "notifications@", "notification@", "updates@", "newsletter@",
        "mailer@", "bounces@", "bounce@", "alerts@", "auto@",
        "automated@", "system@",
        # Billing / transactional
        "invoice", "billing", "receipt", "payment", "statements",
        "orders@", "confirm@", "confirmation@",
    )

    def _is_service_email(self, headers: dict[str, str]) -> bool:
        """Return True when the message is from an automated/transactional sender.

        Uses RFC-standard bulk-email headers as the primary signal — these are
        legally required and present in virtually all marketing/service emails.
        Falls back to sender address heuristics for automated system emails
        that don't use bulk sending infrastructure.
        """
        # List-Unsubscribe is the most reliable signal — required by CAN-SPAM
        # and GDPR for all bulk/marketing email. Real person emails never have it.
        if headers.get("List-Unsubscribe") or headers.get("List-Unsubscribe-Post"):
            return True

        # Precedence: bulk/list — RFC 2076 bulk email marker.
        precedence = (headers.get("Precedence") or "").strip().lower()
        if precedence in ("bulk", "list", "junk"):
            return True

        # Auto-Submitted — used by automated systems (calendar, alerts, etc.).
        auto_submitted = (headers.get("Auto-Submitted") or "").strip().lower()
        if auto_submitted and auto_submitted != "no":
            return True

        # Sender address prefix heuristic — catches noreply@, notifications@, etc.
        from_address = (headers.get("From") or "").lower()
        return any(prefix in from_address for prefix in self._SERVICE_SENDER_PREFIXES)

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
            snippet=clean_email_snippet(message.get("snippet", "")),
            body_text=clean_email_body(self._extract_text(payload)),
            body_html=self._extract_html(payload),
            label_ids=message.get("labelIds", []),
            is_service_email=self._is_service_email(headers),
        )

    def _append_unique_message(
        self,
        messages: list[InboundEmailMessage],
        seen_message_ids: set[str],
        raw_message: dict[str, Any],
    ) -> None:
        normalized = self._normalize_message(raw_message)
        message_id = str(normalized.external_message_id or "").strip()
        if not message_id or message_id in seen_message_ids:
            return
        # Defense-in-depth: skip draft messages even if the query filter missed them.
        if "DRAFT" in (normalized.label_ids or []):
            return
        seen_message_ids.add(message_id)
        messages.append(normalized)

    def _extract_html(self, payload: dict[str, Any]) -> str:
        """Recursively extract the HTML body from a Gmail payload.

        Mirrors _extract_text but looks for text/html parts.
        Returns empty string when no HTML part exists (plain-text only emails).
        """
        body = payload.get("body", {})
        mime_type = payload.get("mimeType", "")
        # A top-level text/html payload (rare but valid).
        if mime_type == "text/html":
            data = body.get("data")
            if data:
                return self._decode_base64(data)

        for part in payload.get("parts", []) or []:
            part_mime = part.get("mimeType", "")
            if part_mime == "text/html":
                part_data = part.get("body", {}).get("data")
                if part_data:
                    return self._decode_base64(part_data)
            elif part_mime.startswith("multipart/"):
                nested = self._extract_html(part)
                if nested:
                    return nested
        return ""

    def _extract_text(self, payload: dict[str, Any]) -> str:
        """Recursively extract the plain-text body from a Gmail payload.

        Forwarded emails use nested multipart structures (e.g. multipart/mixed
        wrapping multipart/alternative wrapping text/plain). A single-level
        scan silently returns "" for those messages — this recursive version
        walks the full tree until it finds a text/plain part with data.
        """
        body = payload.get("body", {})
        data = body.get("data")
        if data:
            return self._decode_base64(data)

        for part in payload.get("parts", []) or []:
            mime_type = part.get("mimeType", "")
            if mime_type == "text/plain":
                part_data = part.get("body", {}).get("data")
                if part_data:
                    return self._decode_base64(part_data)
            elif mime_type.startswith("multipart/"):
                # Recurse into nested multipart containers (e.g. multipart/alternative
                # inside multipart/mixed, which is the standard Fwd: structure).
                nested = self._extract_text(part)
                if nested:
                    return nested
        return ""

    @staticmethod
    def _decode_base64(value: str) -> str:
        padding = "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(value + padding)
        return decoded.decode("utf-8", errors="ignore")
