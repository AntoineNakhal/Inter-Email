"""Formatting helpers for readable agent inputs."""

from __future__ import annotations

from schemas import AgentEmail, TriageItem


def agent_emails_to_payload(
    emails: list[AgentEmail],
) -> list[dict[str, str | int]]:
    """Return plain dictionaries so agent payloads stay clean and predictable."""

    return [email.model_dump() for email in emails]


def triage_items_to_payload(items: list[TriageItem]) -> list[dict[str, str | bool]]:
    """Return plain dictionaries for summary payloads."""

    return [item.model_dump() for item in items]
