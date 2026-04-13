"""Formatting helpers for readable agent inputs."""

from __future__ import annotations

from schemas import AgentThread, ThreadTriageItem


def agent_threads_to_payload(
    threads: list[AgentThread],
) -> list[dict[str, str | int | list[str] | list[dict[str, str]]]]:
    """Return plain dictionaries so agent payloads stay clean and predictable."""

    return [thread.model_dump() for thread in threads]


def triage_items_to_payload(
    items: list[ThreadTriageItem],
) -> list[dict[str, str | bool]]:
    """Return plain dictionaries for summary payloads."""

    return [item.model_dump() for item in items]
