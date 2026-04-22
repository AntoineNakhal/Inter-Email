"""Thread analysis orchestration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from time import perf_counter

from backend.application.crm_service import CRMService
from backend.domain.analysis import ThreadAnalysisRequest
from backend.domain.thread import (
    AnalysisStatus,
    EmailThread,
    SecurityStatus,
    ThreadAnalysis,
    TriageCategory,
    UrgencyLevel,
)
from backend.persistence.repositories.thread_repository import ThreadRepository
from backend.providers.ai.base import AIProviderError
from backend.providers.ai.router import AIProviderRouter


logger = logging.getLogger(__name__)


class ThreadAnalysisService:
    """Runs analysis against provider-agnostic task interfaces."""

    def __init__(
        self,
        provider_router: AIProviderRouter,
        thread_repository: ThreadRepository,
        crm_service: CRMService,
    ) -> None:
        self.provider_router = provider_router
        self.thread_repository = thread_repository
        self.crm_service = crm_service

    def analyze_threads(self, threads: list[EmailThread]) -> list[EmailThread]:
        return self.analyze_threads_with_progress(threads)

    def analyze_threads_with_progress(
        self,
        threads: list[EmailThread],
        progress_callback: Callable[[int, int, EmailThread], None] | None = None,
    ) -> list[EmailThread]:
        analyzed_threads: list[EmailThread] = []
        total_threads = len(threads)
        for index, thread in enumerate(threads, start=1):
            thread_started_at = perf_counter()
            if self._should_reuse_existing_analysis(thread):
                analyzed_threads.append(thread)
                logger.info(
                    "Reused cached analysis for thread %s/%s id=%s",
                    index,
                    total_threads,
                    thread.external_thread_id,
                )
                if progress_callback:
                    progress_callback(index, total_threads, thread)
                continue

            if thread.security_status == SecurityStatus.CLASSIFIED:
                analysis = ThreadAnalysis(
                    category=TriageCategory.CLASSIFIED_SENSITIVE,
                    urgency=UrgencyLevel.HIGH,
                    summary="Sensitive or classified thread held for manual review.",
                    current_status="Manual review required outside the AI workflow.",
                    next_action="Review the thread manually in the secure process.",
                    needs_action_today=True,
                    should_draft_reply=False,
                    provider_name="guardrail",
                    model_name="manual-review",
                    used_fallback=True,
                    analyzed_at=datetime.now(timezone.utc),
                )
                saved_thread = self.thread_repository.save_analysis(
                    thread.external_thread_id,
                    analysis,
                )
                analyzed_threads.append(saved_thread)
                logger.info(
                    "Analyzed thread %s/%s id=%s in %.2fs via manual guardrail",
                    index,
                    total_threads,
                    thread.external_thread_id,
                    perf_counter() - thread_started_at,
                )
                if progress_callback:
                    progress_callback(index, total_threads, saved_thread)
                continue

            analysis = self._analyze_thread(thread)
            thread.analysis = analysis
            crm_record = self.crm_service.extract(
                thread,
                prefer_primary=thread.included_in_ai,
            )
            analysis.crm_contact_name = crm_record.contact_name
            analysis.crm_company = crm_record.company
            analysis.crm_opportunity_type = crm_record.opportunity_type
            analysis.crm_urgency = crm_record.urgency
            saved_thread = self.thread_repository.save_analysis(
                thread.external_thread_id,
                analysis,
            )
            analyzed_threads.append(saved_thread)
            elapsed = perf_counter() - thread_started_at
            log_method = logger.warning if elapsed >= 4.0 else logger.info
            log_method(
                "Analyzed thread %s/%s id=%s included_in_ai=%s in %.2fs",
                index,
                total_threads,
                thread.external_thread_id,
                thread.included_in_ai,
                elapsed,
            )
            if progress_callback:
                progress_callback(index, total_threads, saved_thread)
        return analyzed_threads

    def _should_reuse_existing_analysis(self, thread: EmailThread) -> bool:
        if thread.analysis is None:
            return False
        if thread.analysis_status != AnalysisStatus.COMPLETE:
            return False
        if not thread.last_analyzed_at:
            return False
        expected_provider = (
            self.provider_router.provider_for_task("thread_analysis").name
            if thread.included_in_ai
            else self.provider_router.fallback_provider().name
        )
        if thread.analysis.provider_name != expected_provider:
            return False
        return True

    def _analyze_thread(self, thread: EmailThread) -> ThreadAnalysis:
        request = ThreadAnalysisRequest(thread=thread)
        provider = (
            self.provider_router.provider_for_task("thread_analysis")
            if thread.included_in_ai
            else self.provider_router.fallback_provider()
        )
        try:
            return provider.analyze_thread(request)
        except AIProviderError:
            fallback = self.provider_router.fallback_provider().analyze_thread(request)
            fallback.used_fallback = True
            return fallback
