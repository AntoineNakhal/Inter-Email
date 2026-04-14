"""Local guardrail agent for sensitive / classified threads."""

from __future__ import annotations

from schemas import EmailThread, SensitiveThreadBatch, SensitiveThreadRecord


class ClassifiedThreadAgentRunner:
    """Deterministic local handler that keeps sensitive threads out of AI."""

    HIGH_URGENCY_MARKERS = {"Protected B", "TLP Amber", "TLP Red", "CUI"}

    def run(self, threads: list[EmailThread]) -> SensitiveThreadBatch:
        records = [self._build_record(thread) for thread in threads]
        return SensitiveThreadBatch(records=records)

    def _build_record(self, thread: EmailThread) -> SensitiveThreadRecord:
        markers = list(thread.sensitivity_markers)
        marker_text = ", ".join(markers) if markers else "Sensitive marker"
        urgency = (
            "high"
            if any(marker in self.HIGH_URGENCY_MARKERS for marker in markers)
            else "medium"
        )
        summary = (
            f"Sensitive government-handling markers detected: {marker_text}. "
            "This thread was blocked from AI processing."
        )
        current_status = (
            "Manual handling is required because the thread contains content that "
            "may need controlled storage and review outside the AI workflow."
        )
        next_action = (
            "Review this thread manually, confirm the markings, and handle it only "
            "under the approved data-handling path."
        )
        return SensitiveThreadRecord(
            thread_id=thread.thread_id,
            markers=markers,
            summary=summary,
            current_status=current_status,
            next_action=next_action,
            urgency=urgency,
            needs_action_today=True,
        )
