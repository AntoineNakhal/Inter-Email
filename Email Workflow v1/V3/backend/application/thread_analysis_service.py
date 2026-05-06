"""Thread analysis orchestration."""

from __future__ import annotations

import concurrent.futures
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from time import perf_counter

from backend.application.crm_service import CRMService
from backend.domain.analysis import ThreadAnalysisRequest, ThreadVerificationRequest
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

# Maximum wall-clock seconds to wait for a single AI provider call.
# Prevents a hung API connection from blocking the entire sync indefinitely.
_AI_TIMEOUT_SECONDS = 60


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

    def analyze_threads(
        self,
        threads: list[EmailThread],
        user_email: str | None = None,
    ) -> list[EmailThread]:
        return self.analyze_threads_with_progress(threads, user_email=user_email)

    def analyze_threads_with_progress(
        self,
        threads: list[EmailThread],
        progress_callback: Callable[[int, int, EmailThread], None] | None = None,
        persist_callback: Callable[[EmailThread], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
        user_email: str | None = None,
    ) -> list[EmailThread]:
        analyzed_threads: list[EmailThread] = []
        total_threads = len(threads)
        for index, thread in enumerate(threads, start=1):
            if should_cancel and should_cancel():
                break
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
                    needs_next_action=True,
                    needs_action_today=True,
                    should_draft_reply=False,
                    accuracy_percent=100,
                    verification_summary=(
                        "Guardrail verification accepted the manual-review hold."
                    ),
                    needs_human_review=True,
                    review_reason="Sensitive or classified content must stay in manual review.",
                    provider_name="guardrail",
                    model_name="manual-review",
                    verifier_provider_name="guardrail",
                    verifier_model_name="manual-review",
                    used_fallback=True,
                    analyzed_at=datetime.now(timezone.utc),
                    verified_at=datetime.now(timezone.utc),
                )
                saved_thread = self.thread_repository.save_analysis(
                    thread.external_thread_id,
                    analysis,
                )
                if persist_callback:
                    persist_callback(saved_thread)
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

            prior_analysis = thread.analysis  # snapshot before overwrite
            analysis = self._analyze_thread(thread, user_email=user_email)
            thread.analysis = analysis
            crm_record = self.crm_service.extract(
                thread,
                prefer_primary=thread.included_in_ai,
                user_email=user_email,
            )
            analysis.crm_contact_name = crm_record.contact_name
            analysis.crm_company = crm_record.company
            analysis.crm_opportunity_type = crm_record.opportunity_type
            analysis.crm_urgency = crm_record.urgency
            if self._should_reuse_verification(thread, prior_analysis):
                self._carry_forward_verification(analysis, prior_analysis)
                logger.info(
                    "Skipped re-verification for thread id=%s — content unchanged",
                    thread.external_thread_id,
                )
            else:
                self._apply_verification(thread, analysis, user_email=user_email)
            saved_thread = self.thread_repository.save_analysis(
                thread.external_thread_id,
                analysis,
            )
            if persist_callback:
                persist_callback(saved_thread)
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
        if not thread.analysis.verifier_provider_name.strip():
            return False
        if thread.analysis.accuracy_percent <= 0:
            return False
        return True

    def _analyze_thread(
        self,
        thread: EmailThread,
        user_email: str | None = None,
    ) -> ThreadAnalysis:
        request = ThreadAnalysisRequest(thread=thread, user_email=user_email)
        provider = (
            self.provider_router.provider_for_task("thread_analysis")
            if thread.included_in_ai
            else self.provider_router.fallback_provider()
        )
        try:
            return self._call_with_timeout(provider.analyze_thread, request, thread)
        except AIProviderError:
            fallback = self.provider_router.fallback_provider().analyze_thread(request)
            fallback.used_fallback = True
            return fallback

    def _call_with_timeout(self, fn, request, thread: EmailThread):
        """Run *fn(request)* in a worker thread, raising AIProviderError on timeout.

        Using a ThreadPoolExecutor isolates the blocking HTTP call so Python's
        timeout machinery can interrupt the wait without killing the main thread.
        The underlying connection will be cleaned up when the worker finishes
        (or the process exits).
        """
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(fn, request)
            try:
                return future.result(timeout=_AI_TIMEOUT_SECONDS)
            except concurrent.futures.TimeoutError:
                logger.warning(
                    "AI analysis timed out after %ss for thread %s — falling back.",
                    _AI_TIMEOUT_SECONDS,
                    thread.external_thread_id,
                )
                raise AIProviderError(
                    f"Analysis timed out after {_AI_TIMEOUT_SECONDS}s for thread "
                    f"{thread.external_thread_id}"
                )

    def _should_reuse_verification(
        self,
        thread: EmailThread,
        prior_analysis: ThreadAnalysis | None,
    ) -> bool:
        """Return True when the prior verification is still valid.

        Conditions:
        - A previous verified analysis exists (accuracy > 0, verified_at set)
        - The thread content hasn't changed since that verification
          (stored signature matches the current computed signature)
        """
        if prior_analysis is None:
            return False
        if not prior_analysis.verified_at:
            return False
        if prior_analysis.accuracy_percent <= 0:
            return False
        if not prior_analysis.verifier_provider_name:
            return False
        # Thread unchanged since last sync → same content → same verification result.
        stored_sig = thread.signature
        if not stored_sig:
            return False
        return stored_sig == thread.compute_signature()

    @staticmethod
    def _carry_forward_verification(
        analysis: ThreadAnalysis,
        prior_analysis: ThreadAnalysis,
    ) -> None:
        """Copy verification fields from the prior analysis onto the fresh one."""
        analysis.accuracy_percent = prior_analysis.accuracy_percent
        analysis.verification_summary = prior_analysis.verification_summary
        analysis.needs_human_review = prior_analysis.needs_human_review
        analysis.review_reason = prior_analysis.review_reason
        analysis.verifier_provider_name = prior_analysis.verifier_provider_name
        analysis.verifier_model_name = prior_analysis.verifier_model_name
        analysis.verifier_used_fallback = prior_analysis.verifier_used_fallback
        analysis.verified_at = prior_analysis.verified_at

    def _apply_verification(
        self,
        thread: EmailThread,
        analysis: ThreadAnalysis,
        user_email: str | None = None,
    ) -> None:
        request = ThreadVerificationRequest(
            thread=thread,
            analysis=analysis,
            user_email=user_email,
        )
        provider = (
            self.provider_router.provider_for_task("thread_verification")
            if thread.included_in_ai
            else self.provider_router.fallback_provider()
        )
        try:
            verification = provider.verify_thread_analysis(request)
        except AIProviderError:
            verification = self.provider_router.fallback_provider().verify_thread_analysis(
                request
            )
            verification.used_fallback = True

        analysis.accuracy_percent = verification.accuracy_percent
        analysis.verification_summary = verification.verification_summary
        analysis.needs_human_review = verification.needs_human_review
        analysis.review_reason = verification.review_reason
        analysis.verifier_provider_name = verification.provider_name
        analysis.verifier_model_name = verification.model_name
        analysis.verifier_used_fallback = verification.used_fallback
        analysis.verified_at = verification.verified_at
