"""Thread analysis orchestration."""

from __future__ import annotations

import concurrent.futures
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
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

# Service emails containing any of these signals need AI analysis because
# the user has a real decision to make (register, act on a security issue, etc.).
_SERVICE_ACTION_SIGNALS = (
    "register",
    "rsvp",
    "sign up",
    "sign-up",
    "join us",
    "save your spot",
    "webinar",
    "coaching",
    "event",
    "deadline",
    "expires",
    "last chance",
    "security alert",
    "suspicious",
    "verify",
    "unusual activity",
    "payment failed",
    "payment declined",
    "invoice overdue",
    "action required",
    "urgent",
)


def _service_email_needs_analysis(thread: "EmailThread") -> bool:
    """Return True when a service email contains a signal that requires a decision."""
    text = " ".join([
        thread.subject or "",
        thread.combined_thread_text[:500] or "",
    ]).lower()
    return any(signal in text for signal in _SERVICE_ACTION_SIGNALS)


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
        completed = 0

        # ── Phase 1: instant-path threads (no AI needed) ──────────────────────
        # Handle cached and classified threads synchronously so they don't
        # take up a worker slot and their progress is counted immediately.
        ai_threads: list[EmailThread] = []
        for thread in threads:
            if should_cancel and should_cancel():
                return analyzed_threads

            # Skip AI for service emails that are clearly passive (newsletters,
            # receipts, digests). But still analyze ones that require a decision
            # (event invites, security alerts, payment failures).
            if getattr(thread, "is_service_email", False) and not _service_email_needs_analysis(thread):
                analyzed_threads.append(thread)
                completed += 1
                if progress_callback:
                    progress_callback(completed, total_threads, thread)
                continue

            if self._should_reuse_existing_analysis(thread):
                analyzed_threads.append(thread)
                completed += 1
                logger.info("Reused cached analysis for thread id=%s", thread.external_thread_id)
                if progress_callback:
                    progress_callback(completed, total_threads, thread)
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
                    verification_summary="Guardrail verification accepted the manual-review hold.",
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
                saved_thread = self.thread_repository.save_analysis(thread.external_thread_id, analysis)
                if persist_callback:
                    persist_callback(saved_thread)
                analyzed_threads.append(saved_thread)
                completed += 1
                if progress_callback:
                    progress_callback(completed, total_threads, saved_thread)
                continue

            ai_threads.append(thread)

        if not ai_threads or (should_cancel and should_cancel()):
            return analyzed_threads

        # ── Phase 2: parallel AI analysis ─────────────────────────────────────
        # All AI calls (analyze + CRM + verify) are pure I/O — no DB access.
        # Fire every thread simultaneously and collect results via as_completed.
        # DB writes (save_analysis, persist_callback) stay on this main thread.
        logger.info(
            "Starting parallel AI analysis for %s threads", len(ai_threads)
        )
        started_at = perf_counter()

        with ThreadPoolExecutor(max_workers=len(ai_threads)) as pool:
            future_to_thread: dict[Future[tuple[EmailThread, ThreadAnalysis]], EmailThread] = {
                pool.submit(self._run_ai_pipeline, thread, user_email): thread
                for thread in ai_threads
            }

            for future in as_completed(future_to_thread):
                if should_cancel and should_cancel():
                    # Cancel pending futures — already-running ones finish naturally.
                    for pending in future_to_thread:
                        pending.cancel()
                    break

                original_thread = future_to_thread[future]
                try:
                    thread_with_analysis, analysis = future.result()
                    saved_thread = self.thread_repository.save_analysis(
                        thread_with_analysis.external_thread_id, analysis
                    )
                    if persist_callback:
                        persist_callback(saved_thread)
                    analyzed_threads.append(saved_thread)
                    logger.info(
                        "Parallel analysis done for thread id=%s included_in_ai=%s",
                        thread_with_analysis.external_thread_id,
                        thread_with_analysis.included_in_ai,
                    )
                except Exception:
                    logger.exception(
                        "AI pipeline failed for thread id=%s — keeping original",
                        original_thread.external_thread_id,
                    )
                    analyzed_threads.append(original_thread)

                completed += 1
                if progress_callback:
                    progress_callback(completed, total_threads, analyzed_threads[-1])

        logger.info(
            "Parallel AI analysis complete: %s threads in %.2fs",
            len(ai_threads),
            perf_counter() - started_at,
        )
        return analyzed_threads

    def _run_ai_pipeline(
        self,
        thread: EmailThread,
        user_email: str | None,
    ) -> tuple[EmailThread, ThreadAnalysis]:
        """Pure AI work — no DB access. Safe to call from a worker thread.

        Runs analyze → CRM extraction → verification for a single thread and
        returns the updated thread and analysis ready for the main thread to
        persist. Exceptions propagate to the caller via the Future.
        """
        prior_analysis = thread.analysis
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
        else:
            self._apply_verification(thread, analysis, user_email=user_email)

        return thread, analysis

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
        # Pass user overrides as soft hints to the AI prompt.
        user_overrides = (
            thread.override.active_fields()
            if thread.override and not thread.override.is_empty()
            else None
        )
        request = ThreadAnalysisRequest(
            thread=thread,
            user_email=user_email,
            user_overrides=user_overrides,
        )
        # Always use the primary AI provider — the decision to skip or analyze
        # was already made upstream. included_in_ai is no longer used to pick
        # the provider since all threads that reach here should get real AI.
        provider = self.provider_router.provider_for_task("thread_analysis")
        analysis = self._call_with_retry(provider.analyze_thread, request, thread)

        # Detect disagreements: compare AI output to user overrides.
        if user_overrides:
            disagreements: dict[str, str] = {}
            field_map = {
                "category": ("category", lambda v: v.value if hasattr(v, "value") else v),
                "urgency": ("urgency", lambda v: v.value if hasattr(v, "value") else v),
                "needs_action_today": ("needs_action_today", bool),
                "waiting_on_us": ("waiting_on_us", bool),
                "needs_next_action": ("needs_next_action", bool),
                "should_draft_reply": ("should_draft_reply", bool),
                "relevance_bucket": ("relevance_bucket", lambda v: v.value if hasattr(v, "value") else v),
            }
            for field, (attr, cast) in field_map.items():
                if field not in user_overrides:
                    continue
                ai_value = cast(getattr(analysis, attr))
                user_value = user_overrides[field]
                if str(ai_value) != str(user_value):
                    disagreements[field] = (
                        f"AI set {field}={ai_value!r} instead of your override {user_value!r}"
                    )
            analysis.ai_override_disagreements = disagreements

        return analysis

    def _call_with_retry(self, fn, request, thread: EmailThread):
        """Call fn(request) with exponential backoff on rate-limit errors.

        Retries up to 3 times before falling back to the heuristic provider.
        This handles the 429s that happen when 50 threads fire simultaneously.
        """
        import time

        last_exc: AIProviderError | None = None
        for attempt in range(3):
            try:
                return self._call_with_timeout(fn, request, thread)
            except AIProviderError as exc:
                last_exc = exc
                wait = 2 ** attempt  # 1s, 2s, 4s
                logger.warning(
                    "AI call failed for thread %s (attempt %s/3) — retrying in %ss: %s",
                    thread.external_thread_id, attempt + 1, wait, exc,
                )
                time.sleep(wait)

        logger.error(
            "AI call failed after 3 attempts for thread %s — using heuristic fallback.",
            thread.external_thread_id,
        )
        analysis = self.provider_router.fallback_provider().analyze_thread(request)
        analysis.used_fallback = True
        return analysis

    def _call_with_timeout(self, fn, request, thread: EmailThread):
        """Run fn(request), raising AIProviderError if it exceeds the timeout.

        Since _run_ai_pipeline already executes inside a ThreadPoolExecutor
        worker, we only need a simple Future.result(timeout=...) here — no
        extra thread spawning required.
        """
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(fn, request)
            try:
                return future.result(timeout=_AI_TIMEOUT_SECONDS)
            except concurrent.futures.TimeoutError:
                logger.warning(
                    "AI call timed out after %ss for thread %s — falling back.",
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
        provider = (
            self.provider_router.provider_for_task("thread_verification")
            if thread.included_in_ai
            else self.provider_router.fallback_provider()
        )

        # Skip verification entirely if it would run the heuristic provider.
        # Heuristic verification adds noise, not signal.
        if provider.name == "heuristic":
            analysis.verifier_provider_name = "none"
            analysis.verifier_model_name = "skipped"
            analysis.verifier_used_fallback = False
            analysis.verified_at = datetime.now(timezone.utc)
            return

        request = ThreadVerificationRequest(
            thread=thread,
            analysis=analysis,
            user_email=user_email,
        )
        try:
            verification = provider.verify_thread_analysis(request)
        except AIProviderError:
            # AI verification failed — skip rather than fall back to heuristic.
            analysis.verifier_provider_name = "none"
            analysis.verifier_model_name = "skipped"
            analysis.verifier_used_fallback = False
            analysis.verified_at = datetime.now(timezone.utc)
            return

        analysis.accuracy_percent = verification.accuracy_percent
        analysis.verification_summary = verification.verification_summary
        analysis.needs_human_review = verification.needs_human_review
        analysis.review_reason = verification.review_reason
        analysis.verifier_provider_name = verification.provider_name
        analysis.verifier_model_name = verification.model_name
        analysis.verifier_used_fallback = verification.used_fallback
        analysis.verified_at = verification.verified_at
