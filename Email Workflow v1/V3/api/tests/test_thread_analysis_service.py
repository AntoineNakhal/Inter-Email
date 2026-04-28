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


class _StubProviderRouter:
    class _Provider:
        name = "heuristic"

        def analyze_thread(self, _request):
            return ThreadAnalysis(
                category=TriageCategory.CUSTOMER_PARTNER,
                urgency=UrgencyLevel.MEDIUM,
                summary="Fresh summary",
                current_status="Waiting on us",
                next_action="Reply to the customer.",
                analyzed_at=datetime(2026, 4, 20, 12, 10, tzinfo=timezone.utc),
            )

        def verify_thread_analysis(self, _request):
            from backend.domain.analysis import ThreadVerificationResult

            return ThreadVerificationResult(
                accuracy_percent=91,
                verification_summary="Looks accurate.",
                provider_name="heuristic",
                model_name="deterministic-fallback",
                verified_at=datetime(2026, 4, 20, 12, 11, tzinfo=timezone.utc),
            )

    def provider_for_task(self, _task: str):
        return self._Provider()

    def fallback_provider(self):
        return self._Provider()


class _SavingRepository:
    def save_analysis(self, _external_thread_id: str, analysis: ThreadAnalysis):
        return EmailThread(
            external_thread_id="thread-1",
            subject="Status update",
            participants=["alice@example.com", "bob@example.com"],
            message_count=1,
            latest_message_date=datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc),
            messages=[],
            analysis=analysis,
        )


class _StubCRMService:
    class _CRMRecord:
        contact_name = "Alice"
        company = "Inter-Op"
        opportunity_type = "Follow-up"
        urgency = UrgencyLevel.MEDIUM

    def extract(self, *_args, **_kwargs):
        return self._CRMRecord()


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
            accuracy_percent=88,
            verification_summary="Verifier accepted the cached analysis.",
            verifier_provider_name="heuristic",
            verifier_model_name="deterministic-fallback",
            provider_name="heuristic",
            analyzed_at=datetime(2026, 4, 20, 12, 5, tzinfo=timezone.utc),
            verified_at=datetime(2026, 4, 20, 12, 5, tzinfo=timezone.utc),
        ),
    )

    result = service.analyze_threads([thread])

    assert len(result) == 1
    assert result[0].analysis is not None
    assert result[0].analysis.summary == "Cached summary"


def test_analyze_threads_calls_persist_callback_after_saving_analysis() -> None:
    service = ThreadAnalysisService(
        provider_router=_StubProviderRouter(),
        thread_repository=_SavingRepository(),
        crm_service=_StubCRMService(),
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
        included_in_ai=True,
        analysis_status=AnalysisStatus.PENDING,
    )
    persisted_threads: list[EmailThread] = []

    result = service.analyze_threads_with_progress(
        [thread],
        persist_callback=lambda saved_thread: persisted_threads.append(saved_thread),
    )

    assert len(result) == 1
    assert len(persisted_threads) == 1
    assert persisted_threads[0].analysis is not None
    assert persisted_threads[0].analysis.summary == "Fresh summary"
