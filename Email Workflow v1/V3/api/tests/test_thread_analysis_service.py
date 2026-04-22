from datetime import datetime, timezone

from backend.application.thread_analysis_service import ThreadAnalysisService
from backend.domain.thread import (
    AnalysisStatus,
    EmailThread,
    ThreadAnalysis,
    ThreadMessage,
    TriageCategory,
    UrgencyLevel,
)


class _ForbiddenProviderRouter:
    class _Provider:
        name = "heuristic"

    def provider_for_task(self, _task: str):
        return self._Provider()

    def fallback_provider(self):
        return self._Provider()


class _ForbiddenRepository:
    def save_analysis(self, *_args, **_kwargs):  # pragma: no cover - should never be called
        raise AssertionError("save_analysis should not be called for cached threads")


class _ForbiddenCRMService:
    def extract(self, *_args, **_kwargs):  # pragma: no cover - should never be called
        raise AssertionError("CRM extraction should not be called for cached threads")


def test_analyze_threads_reuses_cached_analysis_without_provider_call() -> None:
    service = ThreadAnalysisService(
        provider_router=_ForbiddenProviderRouter(),
        thread_repository=_ForbiddenRepository(),
        crm_service=_ForbiddenCRMService(),
    )
    thread = EmailThread(
        external_thread_id="thread-1",
        subject="Status update",
        participants=["alice@example.com", "bob@example.com"],
        message_count=1,
        latest_message_date=datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc),
        messages=[
            ThreadMessage(
                external_message_id="message-1",
                sender="alice@example.com",
                recipients=["bob@example.com"],
                subject="Status update",
                sent_at=datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc),
                snippet="latest update",
                cleaned_body="latest update body",
                label_ids=["INBOX"],
            )
        ],
        analysis_status=AnalysisStatus.COMPLETE,
        last_analyzed_at=datetime(2026, 4, 20, 12, 5, tzinfo=timezone.utc),
        analysis=ThreadAnalysis(
            category=TriageCategory.CUSTOMER_PARTNER,
            urgency=UrgencyLevel.MEDIUM,
            summary="Cached summary",
            current_status="Waiting on us",
            next_action="Reply to the customer.",
            provider_name="heuristic",
            analyzed_at=datetime(2026, 4, 20, 12, 5, tzinfo=timezone.utc),
        ),
    )

    result = service.analyze_threads([thread])

    assert len(result) == 1
    assert result[0].analysis is not None
    assert result[0].analysis.summary == "Cached summary"
