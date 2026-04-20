"""Queue and summary service."""

from __future__ import annotations

from backend.domain.analysis import QueueSummaryRequest, QueueSummaryResult
from backend.domain.thread import EmailThread, UrgencyLevel
from backend.persistence.repositories.thread_repository import ThreadRepository
from backend.providers.ai.base import AIProviderError
from backend.providers.ai.router import AIProviderRouter


class QueueService:
    """Serves queue reads and high-level queue summaries."""

    def __init__(
        self,
        provider_router: AIProviderRouter,
        thread_repository: ThreadRepository,
    ) -> None:
        self.provider_router = provider_router
        self.thread_repository = thread_repository

    def list_threads(self) -> list[EmailThread]:
        threads = self.thread_repository.list_threads()
        return sorted(threads, key=self._sort_key)

    def get_thread(self, external_thread_id: str) -> EmailThread | None:
        return self.thread_repository.get_thread(external_thread_id)

    def summarize_threads(self, threads: list[EmailThread]) -> QueueSummaryResult:
        request = QueueSummaryRequest(threads=threads)
        provider = self.provider_router.provider_for_task("queue_summary")
        try:
            return provider.summarize_queue(request)
        except AIProviderError:
            return self.provider_router.fallback_provider().summarize_queue(request)

    def _sort_key(self, thread: EmailThread) -> tuple[int, int, int, int, int, float]:
        urgency_rank = {
            UrgencyLevel.HIGH: 0,
            UrgencyLevel.MEDIUM: 1,
            UrgencyLevel.LOW: 2,
            UrgencyLevel.UNKNOWN: 3,
        }
        analysis = thread.analysis
        latest_timestamp = (
            thread.latest_message_date.timestamp()
            if thread.latest_message_date
            else 0.0
        )
        return (
            0 if analysis and analysis.needs_action_today else 1,
            0 if thread.waiting_on_us else 1,
            0 if not thread.resolved_or_closed else 1,
            urgency_rank.get(analysis.urgency, 3) if analysis else 3,
            0 if not (thread.seen_state and thread.seen_state.seen) else 1,
            -latest_timestamp,
        )
