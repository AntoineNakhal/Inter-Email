"""Domain models for the contacts/persona system."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class Contact(BaseModel):
    email: str
    display_name: str = ""
    contact_type: str = "external"
    type_locked: bool = False
    organization: str = ""
    thread_count: int = 0
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    thread_ids: list[str] = []


class ContactStats(BaseModel):
    total: int = 0
    by_type: dict[str, int] = {}
    new_per_month: list[dict[str, object]] = []
    top_contacts: list[dict[str, object]] = []
