"""Microsoft OAuth client for Outlook / Microsoft 365.

Uses MSAL (Microsoft Authentication Library) with the authorization-code +
PKCE flow. Requires an Azure app registration with:
  - Redirect URI pointing to /api/v1/email-accounts/outlook/callback
  - Mail.Read + Mail.Send + User.Read delegated permissions (Microsoft Graph)
  - "Accounts in any organizational directory and personal Microsoft accounts"
    (multi-tenant + personal) so both @outlook.com and work 365 accounts work.

Credentials JSON stored in email_accounts.credentials_encrypted:
{
  "access_token": "...",
  "refresh_token": "...",
  "token_type": "Bearer",
  "expires_at": "<ISO-8601 UTC>",
  "scope": "..."
}
"""

from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Microsoft Graph base URL
_GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# Required scopes — offline_access gets us a refresh token
SCOPES = [
    "User.Read",
    "Mail.Read",
    "Mail.Send",
]


class OutlookClient:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str | None,
        tenant_id: str = "common",
        credentials_json: str | None = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant_id = tenant_id  # "common" = personal + work
        self.credentials_json = credentials_json

    # ------------------------------------------------------------------ #
    # OAuth helpers                                                        #
    # ------------------------------------------------------------------ #

    def build_authorization_url(self, redirect_uri: str, state: str) -> str:
        import msal

        app = self._build_msal_app(redirect_uri=redirect_uri)
        result = app.initiate_auth_code_flow(
            scopes=SCOPES,
            redirect_uri=redirect_uri,
            state=state,
        )
        # Store the flow dict as a JSON-serialisable object; the caller must
        # persist it (e.g. in the OAuth state store) to validate the callback.
        return result["auth_uri"], result  # type: ignore[return-value]

    def exchange_code_for_token(
        self,
        auth_code_flow: dict,
        auth_response: dict,
        redirect_uri: str,
    ) -> str:
        """Exchange the callback params for tokens. Returns credentials JSON."""
        import msal

        app = self._build_msal_app(redirect_uri=redirect_uri)
        result = app.acquire_token_by_auth_code_flow(auth_code_flow, auth_response)
        if "error" in result:
            raise RuntimeError(
                f"Outlook token exchange failed: {result.get('error_description', result['error'])}"
            )
        credentials = {
            "access_token": result["access_token"],
            "refresh_token": result.get("refresh_token", ""),
            "token_type": result.get("token_type", "Bearer"),
            "scope": " ".join(result.get("scope", SCOPES)),
            "expires_at": self._expiry_iso(result.get("expires_in", 3600)),
        }
        self.credentials_json = json.dumps(credentials)
        return self.credentials_json

    def get_profile(self) -> tuple[str, str | None]:
        """Return (email_address, display_name) from Microsoft Graph /me."""
        import urllib.request

        access_token = self._get_valid_access_token()
        req = urllib.request.Request(
            f"{_GRAPH_BASE}/me?$select=mail,userPrincipalName,displayName",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
        email = (data.get("mail") or data.get("userPrincipalName") or "").strip().lower()
        name = (data.get("displayName") or "").strip() or None
        return email, name

    # ------------------------------------------------------------------ #
    # Message fetching                                                     #
    # ------------------------------------------------------------------ #

    def list_recent_messages(
        self,
        *,
        lookback_days: int = 7,
        max_results: int = 50,
    ) -> list:
        """Fetch recent messages via Microsoft Graph API.

        Returns InboundEmailMessage objects compatible with the existing
        thread grouping and analysis pipeline.
        """
        import urllib.parse
        import urllib.request
        from datetime import timedelta
        from email.utils import format_datetime

        from backend.domain.thread import InboundEmailMessage

        since_dt = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        # Graph API filter uses ISO 8601 UTC
        since_str = since_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        params = {
            "$filter": f"receivedDateTime ge {since_str}",
            "$top": str(min(max_results, 100)),
            "$select": (
                "id,conversationId,subject,from,toRecipients,"
                "receivedDateTime,bodyPreview,body,internetMessageHeaders"
            ),
            "$orderby": "receivedDateTime desc",
        }
        url = f"{_GRAPH_BASE}/me/messages?{urllib.parse.urlencode(params)}"
        access_token = self._get_valid_access_token()
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())

        results: list[InboundEmailMessage] = []
        for raw in data.get("value", []):
            inbound = _outlook_msg_to_inbound(raw)
            if inbound is not None:
                results.append(inbound)
        return results

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _build_msal_app(self, redirect_uri: str | None = None):
        import msal

        authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        return msal.ConfidentialClientApplication(
            client_id=self.client_id,
            client_credential=self.client_secret,
            authority=authority,
        )

    def _get_valid_access_token(self) -> str:
        """Return a valid access token, refreshing if it has expired."""
        if not self.credentials_json:
            raise RuntimeError("Outlook account not connected.")
        creds = json.loads(self.credentials_json)
        expires_at_raw = creds.get("expires_at")
        if expires_at_raw:
            expiry = datetime.fromisoformat(expires_at_raw)
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            # Refresh 5 minutes before actual expiry to avoid races.
            from datetime import timedelta
            if datetime.now(timezone.utc) >= expiry - timedelta(minutes=5):
                creds = self._refresh_access_token(creds)
        return creds["access_token"]

    def _get_access_token(self) -> str:
        """Compatibility shim — prefer _get_valid_access_token()."""
        return self._get_valid_access_token()

    def _refresh_access_token(self, creds: dict) -> dict:
        """Use the stored refresh_token to obtain a new access token."""
        import msal

        refresh_token = creds.get("refresh_token", "")
        if not refresh_token:
            raise RuntimeError(
                "Outlook access token expired and no refresh_token is available. "
                "Please reconnect the account."
            )
        app = self._build_msal_app()
        result = app.acquire_token_by_refresh_token(
            refresh_token=refresh_token,
            scopes=SCOPES,
        )
        if "error" in result:
            raise RuntimeError(
                f"Outlook token refresh failed: "
                f"{result.get('error_description', result['error'])}"
            )
        new_creds = {
            "access_token": result["access_token"],
            # Microsoft may or may not return a new refresh_token; keep the old one if absent.
            "refresh_token": result.get("refresh_token") or refresh_token,
            "token_type": result.get("token_type", "Bearer"),
            "scope": " ".join(result.get("scope", SCOPES)),
            "expires_at": self._expiry_iso(result.get("expires_in", 3600)),
        }
        self.credentials_json = json.dumps(new_creds)
        logger.info("Outlook access token refreshed successfully.")
        return new_creds

    @staticmethod
    def _expiry_iso(expires_in_seconds: int) -> str:
        from datetime import timedelta

        expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds)
        return expiry.isoformat()


# ---------------------------------------------------------------------------
# Module-level parsing helper
# ---------------------------------------------------------------------------

_SERVICE_SENDER_PREFIXES = (
    "noreply@", "no-reply@", "donotreply@", "do-not-reply@",
    "notifications@", "notification@", "alert@", "alerts@",
    "mailer@", "bounce@", "support@", "help@", "info@",
    "newsletter@", "news@", "updates@", "update@",
    "marketing@", "promo@", "promotions@",
    "invoice@", "billing@", "receipt@", "payment@", "statements@",
    "orders@", "confirm@", "confirmation@",
)


def _is_service_email(headers: dict[str, str], from_address: str) -> bool:
    """Detect bulk / automated / marketing email using RFC standard headers."""
    if headers.get("List-Unsubscribe") or headers.get("List-Unsubscribe-Post"):
        return True
    precedence = (headers.get("Precedence") or "").strip().lower()
    if precedence in ("bulk", "list", "junk"):
        return True
    auto_submitted = (headers.get("Auto-Submitted") or "").strip().lower()
    if auto_submitted and auto_submitted != "no":
        return True
    from_lower = from_address.lower()
    return any(prefix in from_lower for prefix in _SERVICE_SENDER_PREFIXES)


def _outlook_msg_to_inbound(raw: dict) -> "object | None":
    """Convert a Microsoft Graph message dict into an InboundEmailMessage."""
    from email.utils import format_datetime
    from datetime import timezone as _tz

    from backend.domain.thread import InboundEmailMessage

    subject = (raw.get("subject") or "(no subject)").strip()

    from_info = (raw.get("from") or {}).get("emailAddress", {})
    from_email = from_info.get("address", "").strip()
    from_name = (from_info.get("name") or "").strip()
    from_addr = f"{from_name} <{from_email}>" if from_name and from_email else from_email

    to_parts = [
        r["emailAddress"]["address"]
        for r in (raw.get("toRecipients") or [])
        if r.get("emailAddress", {}).get("address")
    ]
    to_addr = ", ".join(to_parts)

    # Convert ISO 8601 → RFC 2822 so _parse_date() in the mapper can handle it.
    received_raw = raw.get("receivedDateTime", "")
    date_header = ""
    if received_raw:
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(received_raw.replace("Z", "+00:00"))
            date_header = format_datetime(dt)
        except Exception:
            date_header = received_raw

    snippet = (raw.get("bodyPreview") or "")[:200]
    body_info = raw.get("body") or {}
    body_content = body_info.get("content", "")
    body_type = (body_info.get("contentType") or "text").lower()

    if body_type == "html":
        body_html = body_content
        # Extract plain text from HTML so the AI pipeline has full body content.
        # _group_combined_text in mapper.py only reads body_text, not body_html.
        try:
            from backend.core.email_text import extract_text_from_html
            body_text = extract_text_from_html(body_content)
        except Exception:
            body_text = snippet  # fallback to preview if extraction fails
    else:
        body_html = ""
        body_text = body_content

    message_id = raw.get("id", "")
    thread_id = raw.get("conversationId") or message_id

    # Parse internet headers for service-email detection.
    inet_headers: dict[str, str] = {
        h["name"]: h["value"]
        for h in (raw.get("internetMessageHeaders") or [])
        if h.get("name") and h.get("value")
    }
    service = _is_service_email(inet_headers, from_email)

    return InboundEmailMessage(
        external_message_id=f"outlook:{message_id}",
        external_thread_id=f"outlook:{thread_id}",
        subject=subject,
        from_address=from_addr,
        to_address=to_addr,
        date_header=date_header,
        snippet=snippet,
        body_text=body_text[:50_000],
        body_html=body_html[:200_000],
        label_ids=[],
        is_service_email=service,
    )
