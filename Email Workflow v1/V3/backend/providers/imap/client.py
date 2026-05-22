"""IMAP client for iCloud Mail and generic IMAP providers.

Uses Python's built-in imaplib — no extra dependency.

Well-known iCloud defaults:
  host = imap.mail.me.com
  port = 993
  ssl  = True

iCloud requires an "App-Specific Password" (not your Apple ID password).
Generate one at: https://appleid.apple.com → Sign-In and Security → App-Specific Passwords.

Credentials JSON stored in email_accounts.credentials_encrypted:
{
  "host": "imap.mail.me.com",
  "port": 993,
  "username": "user@icloud.com",
  "password": "<app-specific-password>",
  "use_ssl": true
}
"""

from __future__ import annotations

import imaplib
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.domain.thread import InboundEmailMessage

logger = logging.getLogger(__name__)

# iCloud defaults — used when the caller doesn't supply host/port
ICLOUD_HOST = "imap.mail.me.com"
ICLOUD_PORT = 993

# Common IMAP defaults for generic providers
GENERIC_HOST = ""
GENERIC_PORT = 993


class ImapClient:
    def __init__(self, credentials_json: str) -> None:
        self._creds = json.loads(credentials_json)

    # ------------------------------------------------------------------ #
    # Factory helpers                                                      #
    # ------------------------------------------------------------------ #

    @classmethod
    def for_icloud(cls, username: str, app_password: str) -> "ImapClient":
        creds = {
            "host": ICLOUD_HOST,
            "port": ICLOUD_PORT,
            "username": username.strip().lower(),
            "password": app_password,
            "use_ssl": True,
        }
        return cls(json.dumps(creds))

    @classmethod
    def for_generic(
        cls,
        host: str,
        port: int,
        username: str,
        password: str,
        use_ssl: bool = True,
    ) -> "ImapClient":
        creds = {
            "host": host.strip(),
            "port": int(port),
            "username": username.strip(),
            "password": password,
            "use_ssl": use_ssl,
        }
        return cls(json.dumps(creds))

    # ------------------------------------------------------------------ #
    # Connection test                                                      #
    # ------------------------------------------------------------------ #

    def verify_connection(self) -> tuple[bool, str | None]:
        """Try to open an IMAP connection and authenticate.

        Returns:
            (True, None)        on success
            (False, error_msg)  on failure
        """
        try:
            conn = self._connect()
            conn.logout()
            return True, None
        except imaplib.IMAP4.error as exc:
            return False, f"IMAP authentication failed: {exc}"
        except OSError as exc:
            return False, f"Cannot reach mail server: {exc}"
        except Exception as exc:
            return False, str(exc)

    def get_email_address(self) -> str:
        """Return the username (which is the email address for IMAP)."""
        return str(self._creds.get("username") or "").strip().lower()

    def credentials_json(self) -> str:
        return json.dumps(self._creds)

    # ------------------------------------------------------------------ #
    # Message fetching                                                     #
    # ------------------------------------------------------------------ #

    def list_recent_messages(
        self,
        *,
        lookback_days: int = 7,
        max_results: int = 50,
    ) -> list["InboundEmailMessage"]:
        """Fetch recent messages from INBOX.

        Returns InboundEmailMessage objects compatible with the existing
        thread grouping and analysis pipeline.
        """
        import email as _email
        import email.policy
        from datetime import date, timedelta

        from backend.domain.thread import InboundEmailMessage

        conn = self._connect()
        results: list[InboundEmailMessage] = []
        try:
            conn.select("INBOX", readonly=True)
            since_date = (date.today() - timedelta(days=lookback_days)).strftime("%d-%b-%Y")
            _, uids_raw = conn.uid("SEARCH", None, f"SINCE {since_date}")  # type: ignore[misc]
            uids = uids_raw[0].split() if uids_raw and uids_raw[0] else []
            # Most-recent first, capped at max_results
            uids = uids[-max_results:][::-1]

            for uid in uids:
                try:
                    _, data = conn.uid("FETCH", uid, "(RFC822)")  # type: ignore[misc]
                    if not data or not data[0]:
                        continue
                    raw = data[0][1]
                    msg = _email.message_from_bytes(raw, policy=_email.policy.default)
                    inbound = _imap_msg_to_inbound(uid.decode(), msg)
                    if inbound is not None:
                        results.append(inbound)
                except Exception:
                    logger.warning("IMAP: failed to fetch message UID %s", uid, exc_info=True)
        finally:
            try:
                conn.logout()
            except Exception:
                pass
        return results

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _connect(self):
        host = self._creds["host"]
        port = int(self._creds["port"])
        username = self._creds["username"]
        password = self._creds["password"]
        use_ssl = bool(self._creds.get("use_ssl", True))

        if use_ssl:
            conn = imaplib.IMAP4_SSL(host, port)
        else:
            conn = imaplib.IMAP4(host, port)

        conn.login(username, password)
        return conn


# ---------------------------------------------------------------------------
# Module-level parsing helper (not a method so it can be unit-tested easily)
# ---------------------------------------------------------------------------

def _imap_msg_to_inbound(uid: str, msg: object) -> "InboundEmailMessage | None":
    """Convert a parsed email.message.Message object into an InboundEmailMessage."""
    from email.header import decode_header, make_header

    from backend.domain.thread import InboundEmailMessage

    def _decode(value: str | None) -> str:
        if not value:
            return ""
        try:
            return str(make_header(decode_header(value)))
        except Exception:
            return value or ""

    subject = _decode(msg.get("Subject", "(no subject)"))  # type: ignore[union-attr]
    from_addr = _decode(msg.get("From", ""))  # type: ignore[union-attr]
    to_addr = _decode(msg.get("To", ""))  # type: ignore[union-attr]
    date_str = msg.get("Date", "")  # type: ignore[union-attr]
    message_id = (msg.get("Message-ID") or "").strip().strip("<>")  # type: ignore[union-attr]
    in_reply_to = (msg.get("In-Reply-To") or "").strip().strip("<>")  # type: ignore[union-attr]
    references_raw = (msg.get("References") or "").strip()  # type: ignore[union-attr]

    # Derive a thread ID from the References chain.
    # The first Message-ID in References is the root of the conversation.
    if references_raw:
        first_ref = references_raw.split()[0].strip().strip("<>")
        thread_id = first_ref or message_id or uid
    elif in_reply_to:
        thread_id = in_reply_to
    else:
        thread_id = message_id or uid

    ext_message_id = message_id if message_id else f"imap:{uid}"

    # Extract body parts
    body_text = ""
    body_html = ""
    if msg.is_multipart():  # type: ignore[union-attr]
        for part in msg.walk():  # type: ignore[union-attr]
            ctype = part.get_content_type()
            if ctype == "text/plain" and not body_text:
                try:
                    body_text = part.get_content() or ""
                except Exception:
                    pass
            elif ctype == "text/html" and not body_html:
                try:
                    body_html = part.get_content() or ""
                except Exception:
                    pass
    else:
        ctype = msg.get_content_type()  # type: ignore[union-attr]
        try:
            content = msg.get_content() or ""  # type: ignore[union-attr]
        except Exception:
            content = ""
        if ctype == "text/html":
            body_html = content
        else:
            body_text = content

    snippet = (body_text or "")[:200].replace("\n", " ").strip()

    return InboundEmailMessage(
        external_message_id=ext_message_id,
        external_thread_id=thread_id,
        subject=subject,
        from_address=from_addr,
        to_address=to_addr,
        date_header=date_str,
        snippet=snippet,
        body_text=body_text[:50_000],
        body_html=body_html[:200_000],
        label_ids=[],
        is_service_email=False,
    )
