"""User override domain model.

Stores manual corrections a user makes to AI-generated thread analysis fields.
On re-analysis the AI receives these as soft hints — it may disagree but must
surface the conflict so the user can see both values.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from backend.domain.thread import RelevanceBucket, TriageCategory, UrgencyLevel


class ThreadOverride(BaseModel):
    """Fields the user has manually set for a thread.

    Every field is Optional — None means "not overridden, use AI value".
    """

    category: TriageCategory | None = None
    urgency: UrgencyLevel | None = None
    needs_action_today: bool | None = None
    waiting_on_us: bool | None = None
    needs_next_action: bool | None = None
    should_draft_reply: bool | None = None
    relevance_bucket: RelevanceBucket | None = None
    notes: str = ""

    # Provenance
    overridden_by: str | None = None   # user email
    overridden_at: datetime | None = None
    updated_at: datetime | None = None

    def active_fields(self) -> dict[str, object]:
        """Return only the fields the user has explicitly set (not None)."""
        data: dict[str, object] = {}
        for field in ("category", "urgency", "needs_action_today", "waiting_on_us",
                      "needs_next_action", "should_draft_reply", "relevance_bucket"):
            value = getattr(self, field)
            if value is not None:
                data[field] = value.value if hasattr(value, "value") else value
        return data

    def is_empty(self) -> bool:
        return len(self.active_fields()) == 0


# ── Forward-reference resolution ──────────────────────────────────────────────
# thread.py uses the string annotation "ThreadOverride | None" on EmailThread
# to avoid a circular import (override.py already imports enums from thread.py).
# Pydantic v2 can't resolve that string on its own, so we rebuild EmailThread
# here — the one place where both sides are fully defined — and then rebuild
# every analysis request model that transitively contains EmailThread.
from backend.domain.thread import EmailThread as _EmailThread  # noqa: E402
from backend.domain.analysis import (  # noqa: E402
    DraftReplyRequest as _DraftReplyRequest,
    QueueSummaryRequest as _QueueSummaryRequest,
    ThreadAnalysisRequest as _ThreadAnalysisRequest,
    ThreadVerificationRequest as _ThreadVerificationRequest,
)
from backend.domain.sync import SyncRunSummary as _SyncRunSummary  # noqa: E402

_EmailThread.model_rebuild(_types_namespace={"ThreadOverride": ThreadOverride})
_QueueSummaryRequest.model_rebuild()
_ThreadAnalysisRequest.model_rebuild()
_DraftReplyRequest.model_rebuild()
_ThreadVerificationRequest.model_rebuild()
_SyncRunSummary.model_rebuild()
