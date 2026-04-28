from backend.application.queue_service import QueueService
from backend.domain.analysis import QueueSummaryRequest, QueueSummaryResult
from backend.domain.runtime_settings import RuntimeSettings
from backend.domain.thread import EmailThread, SeenState


class _CapturingProvider:
    def __init__(self) -> None:
        self.last_request: QueueSummaryRequest | None = None

    def summarize_queue(self, request: QueueSummaryRequest) -> QueueSummaryResult:
        self.last_request = request
        return QueueSummaryResult(
            executive_summary=f"summarized {len(request.threads)} thread(s)",
            top_priorities=[thread.subject for thread in request.threads],
            next_actions=[],
        )


class _Router:
    def __init__(self, provider: _CapturingProvider) -> None:
        self.provider = provider

    def provider_for_task(self, _task: str) -> _CapturingProvider:
        return self.provider

    def fallback_provider(self) -> _CapturingProvider:
        return self.provider


class _ThreadRepository:
    def list_threads(self) -> list[EmailThread]:
        return []

    def get_thread(self, _external_thread_id: str) -> EmailThread | None:
        return None


def test_summarize_threads_excludes_seen_threads_from_priority_snapshot() -> None:
    provider = _CapturingProvider()
    service = QueueService(_Router(provider), _ThreadRepository(), RuntimeSettings())

    seen_thread = EmailThread(
        external_thread_id="thread-seen",
        subject="Already reviewed",
        seen_state=SeenState(seen=True, seen_version="v1"),
    )
    unseen_thread = EmailThread(
        external_thread_id="thread-unseen",
        subject="Needs follow up",
        seen_state=SeenState(seen=False, seen_version="v1"),
    )

    summary = service.summarize_threads([seen_thread, unseen_thread])

    assert provider.last_request is not None
    assert [thread.external_thread_id for thread in provider.last_request.threads] == [
        "thread-unseen"
    ]
    assert summary.executive_summary == "summarized 1 thread(s)"
