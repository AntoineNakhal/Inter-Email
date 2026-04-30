"""Repository for the contacts/persona system."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from email.utils import getaddresses, parseaddr

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from backend.domain.contact import Contact, ContactStats
from backend.persistence.models.contact import ContactModel, ContactThreadModel


# ─── domain classification ────────────────────────────────────────────────────

INTERNAL_DOMAINS: frozenset[str] = frozenset({"inter-op.ca"})

SERVICE_DOMAINS: frozenset[str] = frozenset({
    "gmail.com", "google.com", "googlemail.com",
    "microsoft.com", "outlook.com", "hotmail.com", "live.com",
    "openai.com", "anthropic.com",
    "github.com", "slack.com", "notion.so", "figma.com",
    "stripe.com", "zoom.us", "dropbox.com", "hubspot.com",
    "salesforce.com", "mailchimp.com", "sendgrid.com", "twilio.com",
    "atlassian.net", "jira.com", "trello.com", "asana.com",
    "monday.com", "linear.app", "vercel.com", "heroku.com",
})

GOVERNMENT_PATTERNS: tuple[str, ...] = (
    ".gov", ".gc.ca", ".gouv.fr", ".gov.uk",
    ".govt.nz", ".gov.au", ".government.",
)


def _extract_email(raw: str) -> str:
    _, addr = parseaddr(raw)
    return addr.strip().lower()


def _domain_of(email: str) -> str:
    parts = email.split("@")
    return parts[1].lower() if len(parts) == 2 else ""


def _org_from_domain(domain: str) -> str:
    if not domain:
        return ""
    parts = domain.split(".")
    if len(parts) >= 2:
        name = parts[-2]
        return name.capitalize()
    return domain


def detect_contact_type(email: str) -> str:
    domain = _domain_of(email)
    if not domain:
        return "external"
    if domain in INTERNAL_DOMAINS:
        return "internal"
    if domain in SERVICE_DOMAINS:
        return "service"
    if any(domain.endswith(pat) or pat in domain for pat in GOVERNMENT_PATTERNS):
        return "government"
    return "external"


def _should_upgrade_to_partner(current_type: str, ai_category: str | None) -> bool:
    """Upgrade external → partner when AI confirms a business relationship."""
    if current_type in ("internal", "service", "government"):
        return False
    if not ai_category:
        return False
    return "customer" in ai_category.lower() or "partner" in ai_category.lower()


# ─── repository ───────────────────────────────────────────────────────────────

class ContactRepository:
    """Upsert-centric repository — contacts are created/updated from thread data."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self._schema_checked = False

    def _ensure_schema(self) -> None:
        if self._schema_checked:
            return
        # Auto-create tables if they don't exist yet.
        from sqlalchemy import inspect
        bind = self.session.get_bind()
        if bind is None:
            return
        inspector = inspect(bind)
        if not inspector.has_table("contacts"):
            ContactModel.__table__.create(bind)
        if not inspector.has_table("contact_threads"):
            ContactThreadModel.__table__.create(bind)
        self._schema_checked = True

    # ── upsert from a thread ─────────────────────────────────────────────────

    def upsert_from_thread(
        self,
        external_thread_id: str,
        sender_raw: str,
        recipient_raws: list[str],
        thread_date: datetime | None,
        ai_category: str | None = None,
    ) -> None:
        """Create or update contact personas from a thread's participants."""
        self._ensure_schema()
        now = thread_date or datetime.now(timezone.utc)

        participants: list[tuple[str, str]] = []  # (email, role)
        sender_email = _extract_email(sender_raw)
        if sender_email:
            participants.append((sender_email, "sender"))

        for raw in recipient_raws:
            for _, addr in getaddresses([raw]):
                addr = addr.strip().lower()
                if addr and addr != sender_email:
                    participants.append((addr, "recipient"))

        for email, role in participants:
            if not email or "@" not in email:
                continue
            self._upsert_contact(
                email=email,
                display_name=sender_raw if role == "sender" else email,
                external_thread_id=external_thread_id,
                role=role,
                thread_date=now,
                ai_category=ai_category,
            )

    def _upsert_contact(
        self,
        email: str,
        display_name: str,
        external_thread_id: str,
        role: str,
        thread_date: datetime,
        ai_category: str | None,
    ) -> None:
        model = self.session.scalar(
            select(ContactModel).where(ContactModel.email == email)
        )

        detected_type = detect_contact_type(email)
        domain = _domain_of(email)

        aware_date = thread_date.replace(tzinfo=timezone.utc) if thread_date.tzinfo is None else thread_date

        if model is None:
            model = ContactModel(
                email=email,
                display_name=self._clean_display_name(display_name),
                contact_type=detected_type,
                type_locked=False,
                organization=_org_from_domain(domain),
                first_seen_at=aware_date,
                last_seen_at=aware_date,
                thread_count=0,
            )
            self.session.add(model)
            self.session.flush()
        else:
            # Only update type if not locked by user.
            if not model.type_locked:
                upgraded = _should_upgrade_to_partner(detected_type, ai_category)
                model.contact_type = "partner" if upgraded else detected_type
            # Keep display name if we have a better one.
            if not model.display_name and display_name:
                model.display_name = self._clean_display_name(display_name)
            if not model.organization:
                model.organization = _org_from_domain(domain)
            def _as_utc(dt: datetime) -> datetime:
                if dt.tzinfo is None:
                    return dt.replace(tzinfo=timezone.utc)
                return dt

            td = _as_utc(thread_date)
            if model.last_seen_at is None or td > _as_utc(model.last_seen_at):
                model.last_seen_at = td
            if model.first_seen_at is None or td < _as_utc(model.first_seen_at):
                model.first_seen_at = td

        # Link thread if not already linked.
        existing_link = self.session.scalar(
            select(ContactThreadModel).where(
                ContactThreadModel.contact_id == model.id,
                ContactThreadModel.external_thread_id == external_thread_id,
            )
        )
        if existing_link is None:
            link = ContactThreadModel(
                contact_id=model.id,
                external_thread_id=external_thread_id,
                role=role,
            )
            self.session.add(link)
            model.thread_count += 1

        self.session.flush()

    # ── queries ──────────────────────────────────────────────────────────────

    def list_contacts(self) -> list[Contact]:
        self._ensure_schema()
        models = self.session.scalars(
            select(ContactModel).order_by(ContactModel.thread_count.desc())
        ).all()
        return [self._to_domain(m) for m in models]

    def get_contact(self, email: str) -> Contact | None:
        self._ensure_schema()
        model = self.session.scalar(
            select(ContactModel).where(ContactModel.email == email)
        )
        return self._to_domain(model) if model else None

    def set_contact_type(self, email: str, contact_type: str) -> Contact | None:
        """Manually override a contact's type — locks it against auto-detection."""
        self._ensure_schema()
        model = self.session.scalar(
            select(ContactModel).where(ContactModel.email == email)
        )
        if model is None:
            return None
        model.contact_type = contact_type
        model.type_locked = True
        self.session.flush()
        return self._to_domain(model)

    def get_stats(self, range_key: str = "all") -> ContactStats:
        self._ensure_schema()
        cutoff = self._range_cutoff(range_key)

        total_query = select(func.count(ContactModel.id))
        if cutoff is not None:
            total_query = total_query.where(ContactModel.last_seen_at >= cutoff)
        total = self.session.scalar(total_query) or 0

        by_type_query = (
            select(ContactModel.contact_type, func.count(ContactModel.id))
            .group_by(ContactModel.contact_type)
        )
        if cutoff is not None:
            by_type_query = by_type_query.where(ContactModel.last_seen_at >= cutoff)
        by_type_rows = self.session.execute(by_type_query).all()
        by_type = {row[0]: row[1] for row in by_type_rows}

        new_per_month_query = (
            select(
                func.strftime("%Y-%m", ContactModel.first_seen_at).label("month"),
                func.count(ContactModel.id).label("cnt"),
            )
            .where(ContactModel.first_seen_at.is_not(None))
            .group_by("month")
            .order_by("month")
        )
        if cutoff is not None:
            new_per_month_query = new_per_month_query.where(
                ContactModel.first_seen_at >= cutoff
            )
        new_per_month_rows = self.session.execute(new_per_month_query).all()
        new_per_month = [{"month": r[0], "count": r[1]} for r in new_per_month_rows]

        top_query = (
            select(
                ContactModel.email,
                ContactModel.display_name,
                ContactModel.contact_type,
                ContactModel.organization,
                ContactModel.thread_count,
            )
            .order_by(ContactModel.thread_count.desc())
            .limit(10)
        )
        if cutoff is not None:
            top_query = top_query.where(ContactModel.last_seen_at >= cutoff)
        top_rows = self.session.execute(top_query).all()
        top_contacts = [
            {
                "email": r[0],
                "display_name": r[1],
                "contact_type": r[2],
                "organization": r[3],
                "thread_count": r[4],
            }
            for r in top_rows
        ]

        return ContactStats(
            total=total,
            by_type=by_type,
            new_per_month=new_per_month,
            top_contacts=top_contacts,
        )

    def _range_cutoff(self, range_key: str) -> datetime | None:
        normalized = (range_key or "all").strip().lower()
        if normalized in {"all", "all_time"}:
            return None

        now = datetime.now(timezone.utc)
        if normalized == "today":
            return now.replace(hour=0, minute=0, second=0, microsecond=0)
        if normalized == "week":
            return now - timedelta(days=7)
        if normalized == "month":
            return now - timedelta(days=30)
        if normalized == "three_months":
            return now - timedelta(days=90)
        if normalized == "six_months":
            return now - timedelta(days=180)
        if normalized == "year":
            return now - timedelta(days=365)
        if normalized == "three_years":
            return now - timedelta(days=365 * 3)
        if normalized == "five_years":
            return now - timedelta(days=365 * 5)
        return None

    # ── helpers ──────────────────────────────────────────────────────────────

    def _clean_display_name(self, raw: str) -> str:
        name, addr = parseaddr(raw)
        return (name or addr.split("@")[0]).strip()

    def _to_domain(self, model: ContactModel) -> Contact:
        thread_ids = [link.external_thread_id for link in (model.thread_links or [])]
        return Contact(
            email=model.email,
            display_name=model.display_name,
            contact_type=model.contact_type,
            type_locked=model.type_locked,
            organization=model.organization,
            thread_count=model.thread_count,
            first_seen_at=model.first_seen_at,
            last_seen_at=model.last_seen_at,
            thread_ids=thread_ids,
        )
