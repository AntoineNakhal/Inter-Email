"""End-to-end Gmail sync and analysis workflow."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from time import perf_counter

from sqlalchemy.orm import Session

from backend.application.queue_service import QueueService
from backend.application.sync_progress_store import SyncProgressStore
from backend.application.sync_timing_learner import SyncTimingLearner
from backend.application.thread_analysis_service import ThreadAnalysisService
from backend.domain.runtime_settings import RuntimeSettings
from backend.domain.sync import SyncRunSummary, SyncStage, SyncStatus
from backend.domain.thread import (
    AnalysisStatus,
    EmailThread,
    RelevanceBucket,
    SecurityStatus,
)
from backend.persistence.repositories.eta_progress_repository import EtaProgressRepository
from backend.persistence.repositories.contact_repository import ContactRepository
from backend.persistence.repositories.sync_repository import SyncRepository
from backend.persistence.repositories.thread_repository import ThreadRepository
from backend.providers.gmail.client import GmailReadonlyClient, HistoryExpiredError
from backend.providers.gmail.mapper import group_messages_by_thread


logger = logging.getLogger(__name__)


class SyncCancelledError(Exception):
    """Raised when a running sync is cancelled by the user."""


class GmailSyncService:
    """Owns the main sync -> persist -> analyze -> summarize workflow."""

    def __init__(
        self,
        session: Session,
        runtime_settings: RuntimeSettings,
        gmail_client: GmailReadonlyClient,
        thread_repository: ThreadRepository,
        sync_repository: SyncRepository,
        analysis_service: ThreadAnalysisService,
        queue_service: QueueService,
        progress_store: SyncProgressStore,
        eta_progress_repository: EtaProgressRepository,
        timing_learner: SyncTimingLearner | None = None,
    ) -> None:
        self.session = session
        self.runtime_settings = runtime_settings
        self.gmail_client = gmail_client
        self.thread_repository = thread_repository
        self.sync_repository = sync_repository
        self.analysis_service = analysis_service
        self.queue_service = queue_service
        self.progress_store = progress_store
        self.eta_progress_repository = eta_progress_repository
        self.timing_learner = timing_learner
        self.contact_repository = (
            ContactRepository(session, thread_repository.user_id)
            if session is not None
            and thread_repository is not None
            and hasattr(thread_repository, "user_id")
            else None
        )

    def create_run(self, source: str) -> SyncRunSummary:
        mailbox = self.runtime_settings.gmail_mailbox_email.strip().lower()

        # Per-account single-active-run lock: reject a new run if one is
        # already in progress for this mailbox. The caller should surface this
        # to the user rather than queue a second overlapping sync.
        if mailbox:
            active = self.sync_repository.get_active_run_for_account(mailbox)
            if active is not None:
                raise RuntimeError(
                    f"A sync is already running for {mailbox} "
                    f"(run_id={active.id}). Cancel it first."
                )

        run = self.sync_repository.start_run(source, mailbox_account=mailbox)
        self.session.commit()
        summary = self.progress_store.start(run.id, source)
        self.eta_progress_repository.update_sync_phase(
            run_id=run.id,
            stage=summary.stage,
            status=summary.status,
            eta_seconds=summary.eta_seconds,
            progress_current=summary.stage_unit_current,
            progress_total=summary.stage_unit_total,
            status_message=summary.status_message,
        )
        self.session.commit()
        return summary

    def get_run_status(self, run_id: int) -> SyncRunSummary | None:
        # When Arq is active the worker updates the DB but has its own
        # in-memory progress_store. Always read from DB so the API sees
        # the worker's real progress instead of the stale queued state.
        from backend.core.config import get_settings
        if get_settings().redis_url:
            return self.sync_repository.get_run(run_id)
        progress = self.progress_store.get(run_id)
        if progress:
            return progress
        return self.sync_repository.get_run(run_id)

    def get_latest_run_status(self) -> SyncRunSummary | None:
        from backend.core.config import get_settings
        if get_settings().redis_url:
            return self.sync_repository.get_latest_run()
        progress = self.progress_store.latest()
        if progress:
            return progress
        return self.sync_repository.get_latest_run()

    def get_running_run(self) -> SyncRunSummary | None:
        from backend.core.config import get_settings
        if get_settings().redis_url:
            # Read active run directly from DB — the worker updates it, not this process.
            mailbox = self.runtime_settings.gmail_mailbox_email.strip().lower()
            if mailbox:
                active = self.sync_repository.get_active_run_for_account(mailbox)
                return self.sync_repository.get_run(active.id) if active else None
            # No mailbox configured — only block if a run is actively running.
            latest = self.sync_repository.get_latest_run()
            return latest if latest and latest.status == SyncStatus.RUNNING else None
        return self.progress_store.running()

    def cancel_run(self, run_id: int) -> SyncRunSummary | None:
        run = self.sync_repository.get_run_model(run_id)
        if run is None or run.status != SyncStatus.RUNNING.value:
            return None
        return self.progress_store.request_cancel(run_id)

    def sync_recent_threads(
        self,
        run_id: int,
        source: str,
        max_results: int,
        lookback_days: int = 7,
    ) -> SyncRunSummary:
        run = self.sync_repository.get_run_model(run_id)
        if run is None:
            raise ValueError(f"Sync run `{run_id}` was not found.")

        snapshot_threads = self.thread_repository.list_threads()
        self.progress_store.capture_snapshot(run_id, snapshot_threads)
        fetched_message_count = 0
        persisted_thread_count = 0
        analyzed_thread_count = 0
        ai_thread_count = 0
        # Per-stage wall-clock timestamps for timing the learner.
        _fetch_start: float = 0.0
        _persist_start: float = 0.0
        _analyze_start: float = 0.0
        _summarize_start: float = 0.0

        try:
            sync_started_at = perf_counter()
            logger.info(
                "Sync run %s started source=%s max_results=%s lookback_days=%s",
                run_id,
                source,
                max_results,
                lookback_days,
            )
            # ------------------------------------------------------------------
            # Fetch phase: incremental (history) or full (bootstrap / expiry)
            # ------------------------------------------------------------------
            stored_history_id = self.runtime_settings.gmail_history_id.strip()
            # Use incremental only when a cursor exists AND the user hasn't
            # requested a longer window than the default 7-day rolling window.
            # A longer lookback means they want a real full re-fetch (e.g. "last month").
            force_full = lookback_days > 7
            fetch_mode = "incremental" if (stored_history_id and not force_full) else "bootstrap"

            fetch_status_message = (
                "Fetching changes since last sync."
                if fetch_mode == "incremental"
                else f"Full fetch — last {lookback_days} days."
                if force_full
                else "Full fetch — bootstrapping incremental sync."
            )
            fetching_summary = self.progress_store.update(
                run_id,
                stage=SyncStage.FETCHING,
                status_message=fetch_status_message,
                stage_unit_current=0,
                stage_unit_total=0,
            )
            if fetching_summary:
                self._persist_stage_progress(run_id, fetching_summary)

            _fetch_start = perf_counter()
            fetch_started_at = _fetch_start
            deleted_thread_ids: set[str] = set()
            new_history_id: str = ""

            if fetch_mode == "incremental":
                try:
                    messages, new_history_id, deleted_thread_ids = (
                        self.gmail_client.list_messages_since_history(
                            start_history_id=stored_history_id,
                            source=source,
                            max_results=max_results,
                        )
                    )
                    logger.info(
                        "Sync run %s incremental fetch: %s messages, "
                        "%s deleted thread(s) in %.2fs",
                        run_id,
                        len(messages),
                        len(deleted_thread_ids),
                        perf_counter() - fetch_started_at,
                    )
                except HistoryExpiredError:
                    logger.warning(
                        "Sync run %s: historyId %r expired — falling back to full fetch.",
                        run_id,
                        stored_history_id,
                    )
                    fetch_mode = "bootstrap"

            if fetch_mode == "bootstrap":
                # For a manual longer-window fetch, skip the known-IDs filter so
                # every thread in the requested window is re-evaluated. Threads
                # with unchanged content will reuse their cached analysis; only
                # new or changed threads get re-analyzed.
                known_message_ids = (
                    set()
                    if force_full
                    else self.thread_repository.get_known_message_ids()
                )
                messages = self.gmail_client.list_recent_messages(
                    max_results=max_results,
                    source=source,
                    lookback_days=lookback_days,
                    known_message_ids=known_message_ids,
                )
                new_history_id = self.gmail_client.get_current_history_id()
                logger.info(
                    "Sync run %s bootstrap fetch: %s messages, historyId=%r in %.2fs",
                    run_id,
                    len(messages),
                    new_history_id,
                    perf_counter() - fetch_started_at,
                )

            fetched_message_count = len(messages)
            self._raise_if_cancel_requested(run_id)
            logger.info(
                "Sync run %s fetched %s Gmail messages in %.2fs",
                run_id,
                len(messages),
                perf_counter() - fetch_started_at,
            )
            _persist_start = perf_counter()
            persisting_summary = self.progress_store.update(
                run_id,
                stage=SyncStage.PERSISTING,
                status_message=f"Fetched {len(messages)} messages. Grouping threads.",
                fetched_message_count=len(messages),
                thread_count=0,
                stage_unit_current=0,
                stage_unit_total=len(messages),
            )
            if persisting_summary:
                self._persist_stage_progress(run_id, persisting_summary)
            grouping_started_at = perf_counter()
            grouped_threads = group_messages_by_thread(messages)
            grouped_threads = self._apply_runtime_ai_strategy(grouped_threads)
            self._raise_if_cancel_requested(run_id)
            logger.info(
                "Sync run %s grouped %s threads in %.2fs",
                run_id,
                len(grouped_threads),
                perf_counter() - grouping_started_at,
            )
            saved_threads = self._persist_threads_with_progress(
                run_id=run_id,
                grouped_threads=grouped_threads,
                fetched_message_count=len(messages),
            )

            # Clean up threads that were fully deleted from Gmail.
            # deleted_thread_ids are IDs where Gmail reported a messageDeleted
            # event. Those that didn't come back as saved_threads are gone.
            if deleted_thread_ids:
                saved_thread_id_set = {t.external_thread_id for t in saved_threads}
                truly_deleted = [
                    tid for tid in deleted_thread_ids
                    if tid not in saved_thread_id_set
                ]
                if truly_deleted:
                    self.thread_repository.delete_threads(truly_deleted)
                    logger.info(
                        "Sync run %s removed %s locally-deleted thread(s): %s",
                        run_id,
                        len(truly_deleted),
                        truly_deleted[:5],
                    )

            self.session.commit()
            self._raise_if_cancel_requested(run_id)

            # Persist the new history cursor so the next sync is incremental.
            # Done immediately after persisting threads, before analysis, so
            # a crash during analysis doesn't lose the cursor.
            if new_history_id:
                from backend.persistence.repositories.runtime_settings_repository import (
                    RuntimeSettingsRepository,
                )
                RuntimeSettingsRepository(
                    self.session,
                    self.thread_repository.user_id,
                ).update_gmail_history_id(
                    new_history_id
                )
                self.session.commit()
                logger.info(
                    "Sync run %s persisted new historyId=%r", run_id, new_history_id
                )

            # Threads skipped at fetch time (already-known message IDs) may
            # still need re-analysis if the active AI provider changed since
            # they were last analyzed (e.g. heuristic → Claude). Merge them
            # into the analysis batch, deduplicating by thread ID.
            active_provider = self.analysis_service.provider_router.provider_for_task("thread_analysis").name
            stale_threads = self.thread_repository.get_threads_with_stale_analysis(active_provider)
            saved_ids = {t.external_thread_id for t in saved_threads}
            stale_new = [t for t in stale_threads if t.external_thread_id not in saved_ids]
            if stale_new:
                logger.info(
                    "Sync run %s found %s thread(s) with stale analysis for provider %s",
                    run_id,
                    len(stale_new),
                    active_provider,
                )
                # Mark them pending so the reuse check in ThreadAnalysisService
                # treats them as needing fresh analysis.
                for thread in stale_new:
                    thread.analysis_status = AnalysisStatus.PENDING
                    thread.included_in_ai = True
                saved_threads = saved_threads + stale_new

            persisted_thread_count = len(saved_threads)
            ai_thread_count = len(
                [thread for thread in saved_threads if thread.included_in_ai]
            )
            _analyze_start = perf_counter()
            analyzing_summary = self.progress_store.update(
                run_id,
                stage=SyncStage.ANALYZING,
                status_message=(
                    f"Analyzing {len(saved_threads)} threads with your local AI agent."
                    if self.runtime_settings.local_ai_enabled
                    else f"Analyzing {len(saved_threads)} threads for next actions."
                ),
                fetched_message_count=len(messages),
                thread_count=len(saved_threads),
                ai_thread_count=ai_thread_count,
                stage_unit_current=0,
                stage_unit_total=len(saved_threads),
            )
            if analyzing_summary:
                self._persist_stage_progress(run_id, analyzing_summary)
            analysis_started_at = perf_counter()
            # Pull the connected mailbox owner so analysis prompts know
            # whose perspective to take. Falls back to None if no mailbox
            # is connected yet — providers handle that by skipping the
            # user-perspective preamble entirely.
            mailbox_email = (
                self.runtime_settings.gmail_mailbox_email.strip() or None
            )
            analyzed_threads = self.analysis_service.analyze_threads_with_progress(
                saved_threads,
                progress_callback=lambda current, total, thread: self._update_analysis_progress(
                    run_id=run_id,
                    current=current,
                    total=total,
                    fetched_message_count=len(messages),
                    thread_count=len(saved_threads),
                    ai_thread_count=ai_thread_count,
                    external_thread_id=thread.external_thread_id,
                ),
                persist_callback=lambda _thread: self.session.commit(),
                should_cancel=lambda: self.progress_store.is_cancel_requested(run_id),
                user_email=mailbox_email,
            )
            self._raise_if_cancel_requested(run_id)
            analyzed_thread_count = len(analyzed_threads)
            logger.info(
                "Sync run %s analyzed %s threads in %.2fs",
                run_id,
                len(analyzed_threads),
                perf_counter() - analysis_started_at,
            )
            _summarize_start = perf_counter()
            summarizing_summary = self.progress_store.update(
                run_id,
                stage=SyncStage.SUMMARIZING,
                status_message="Building your queue summary.",
                fetched_message_count=len(messages),
                thread_count=len(analyzed_threads),
                ai_thread_count=len(
                    [thread for thread in analyzed_threads if thread.included_in_ai]
                ),
                stage_unit_current=0,
                stage_unit_total=1,
            )
            if summarizing_summary:
                self._persist_stage_progress(run_id, summarizing_summary)
            summary_started_at = perf_counter()
            queue_summary = self.queue_service.summarize_threads(analyzed_threads)
            self._raise_if_cancel_requested(run_id)
            logger.info(
                "Sync run %s built queue summary in %.2fs",
                run_id,
                perf_counter() - summary_started_at,
            )
            result = self.sync_repository.complete_run(
                run=run,
                status=SyncStatus.COMPLETED,
                fetched_message_count=len(messages),
                thread_count=len(analyzed_threads),
                ai_thread_count=ai_thread_count,
                queue_summary=queue_summary,
            )
            result.threads = analyzed_threads
            result.status_message = "Inbox refresh complete."
            result.stage = SyncStage.COMPLETED
            result.progress_percent = 100
            result.completed_at = datetime.now(timezone.utc)
            self.eta_progress_repository.update_sync_phase(
                run_id=run_id,
                stage=SyncStage.COMPLETED,
                status=SyncStatus.COMPLETED,
                eta_seconds=0,
                progress_current=result.thread_count,
                progress_total=result.thread_count,
                status_message=result.status_message,
            )
            self.session.commit()
            _sync_done = perf_counter()
            logger.info(
                "Sync run %s completed in %.2fs",
                run_id,
                _sync_done - sync_started_at,
            )
            # Record real stage durations so the next run has learned averages.
            if self.timing_learner is not None and _fetch_start > 0:
                try:
                    self.timing_learner.record_run(
                        fetching_ms=(_persist_start - _fetch_start) * 1000,
                        persisting_ms=(_analyze_start - _persist_start) * 1000,
                        analyzing_ms=(_summarize_start - _analyze_start) * 1000,
                        summarizing_ms=(_sync_done - _summarize_start) * 1000,
                        thread_count=len(saved_threads),
                    )
                    self.timing_learner.save()
                except Exception:
                    logger.warning(
                        "Sync run %s: failed to record timing data — "
                        "next run will still work but ETA won't improve",
                        run_id,
                        exc_info=True,
                    )
            return self.progress_store.complete(result)
        except SyncCancelledError:
            self.session.rollback()
            cancelled_run_model = self.sync_repository.get_run_model(run_id)
            restored_threads = self.thread_repository.restore_threads_snapshot(
                snapshot_threads,
            )
            cancelled_run = self.sync_repository.complete_run(
                run=cancelled_run_model or run,
                status=SyncStatus.CANCELLED,
                fetched_message_count=fetched_message_count,
                thread_count=len(restored_threads),
                ai_thread_count=0,
                error_message=None,
            )
            cancelled_run.threads = restored_threads
            cancelled_run.status_message = (
                "Inbox refresh cancelled. Restored the previous local inbox."
            )
            cancelled_run.completed_at = datetime.now(timezone.utc)
            self.eta_progress_repository.update_sync_phase(
                run_id=run_id,
                stage=SyncStage.CANCELLED,
                status=SyncStatus.CANCELLED,
                eta_seconds=0,
                progress_current=0,
                progress_total=0,
                status_message=cancelled_run.status_message,
            )
            self.session.commit()
            logger.info("Sync run %s cancelled and previous snapshot restored", run_id)
            return self.progress_store.cancel(
                run_id,
                source=source,
                status_message=cancelled_run.status_message,
                fetched_message_count=fetched_message_count,
                thread_count=len(restored_threads),
                ai_thread_count=0,
            )
        except Exception as exc:
            self.session.rollback()
            try:
                failed_run_model = self.sync_repository.get_run_model(run_id)
                if failed_run_model is not None:
                    failed_run = self.sync_repository.complete_run(
                        run=failed_run_model,
                        status=SyncStatus.FAILED,
                        fetched_message_count=fetched_message_count,
                        thread_count=analyzed_thread_count or persisted_thread_count,
                        ai_thread_count=ai_thread_count,
                        error_message=str(exc),
                    )
                    self.eta_progress_repository.update_sync_phase(
                        run_id=run_id,
                        stage=SyncStage.FAILED,
                        status=SyncStatus.FAILED,
                        eta_seconds=0,
                        progress_current=0,
                        progress_total=0,
                        status_message="Inbox refresh failed.",
                    )
                    self.session.commit()
                else:
                    failed_run = None
            except Exception:
                self.session.rollback()
                failed_run = None
                logger.exception(
                    "Sync run %s could not record failure state after rollback",
                    run_id,
                )
            self.progress_store.fail(
                run_id,
                source=source,
                error_message=str(exc),
                fetched_message_count=(
                    failed_run.fetched_message_count
                    if failed_run is not None
                    else fetched_message_count
                ),
                thread_count=(
                    failed_run.thread_count
                    if failed_run is not None
                    else analyzed_thread_count or persisted_thread_count
                ),
                ai_thread_count=(
                    failed_run.ai_thread_count
                    if failed_run is not None
                    else ai_thread_count
                ),
            )
            logger.exception("Sync run %s failed", run_id)
            raise

    def _update_analysis_progress(
        self,
        *,
        run_id: int,
        current: int,
        total: int,
        fetched_message_count: int,
        thread_count: int,
        ai_thread_count: int,
        external_thread_id: str | None = None,
    ) -> None:
        if total <= 0:
            status_message = "Thread analysis complete."
        else:
            status_message = f"Analyzing threads ({current}/{total})."
        summary = self.progress_store.update(
            run_id,
            stage=SyncStage.ANALYZING,
            status_message=status_message,
            fetched_message_count=fetched_message_count,
            thread_count=thread_count,
            ai_thread_count=ai_thread_count,
            stage_unit_current=current,
            stage_unit_total=total,
        )
        # Persist to DB on every thread so the API process (which reads DB
        # when Arq is active) sees live per-thread progress, not just stage transitions.
        if summary:
            self._persist_stage_progress(run_id, summary)
            if external_thread_id:
                self.eta_progress_repository.update_thread_analysis(
                    run_id=run_id,
                    external_thread_id=external_thread_id,
                    eta_seconds=summary.eta_seconds,
                    progress_current=current,
                    progress_total=total,
                    status="running" if current < total else "completed",
                )

    def _persist_threads_with_progress(
        self,
        *,
        run_id: int,
        grouped_threads,
        fetched_message_count: int,
    ) -> list:
        persistence_started_at = perf_counter()
        total_threads = len(grouped_threads)
        total_messages = sum(len(thread.messages) for thread in grouped_threads)
        processed_messages = 0
        if total_threads == 0:
            self.progress_store.update(
                run_id,
                stage=SyncStage.PERSISTING,
                status_message="No threads to save from the latest fetch.",
                fetched_message_count=fetched_message_count,
                thread_count=0,
                ai_thread_count=0,
                stage_unit_current=0,
                stage_unit_total=0,
            )
            return []

        saved_threads = []
        self.progress_store.update(
            run_id,
            stage=SyncStage.PERSISTING,
            status_message=f"Saving thread 1 of {total_threads}.",
            fetched_message_count=fetched_message_count,
            thread_count=total_threads,
            ai_thread_count=0,
            stage_unit_current=0,
            stage_unit_total=total_messages,
        )
        for index, thread in enumerate(grouped_threads, start=1):
            self._raise_if_cancel_requested(run_id)
            thread_started_at = perf_counter()
            obsolete_source_threads = [
                source_thread_id
                for source_thread_id in thread.source_thread_ids
                if source_thread_id != thread.external_thread_id
            ]
            if obsolete_source_threads:
                self.thread_repository.delete_threads(obsolete_source_threads)

            self.progress_store.update(
                run_id,
                stage=SyncStage.PERSISTING,
                status_message=f"Saving thread {index} of {total_threads}.",
                fetched_message_count=fetched_message_count,
                thread_count=total_threads,
                ai_thread_count=0,
                stage_unit_current=processed_messages,
                stage_unit_total=total_messages,
            )

            def on_message_saved(current_message: int, thread_message_total: int) -> None:
                overall_processed = processed_messages + current_message
                self.progress_store.update(
                    run_id,
                    stage=SyncStage.PERSISTING,
                    status_message=(
                        f"Saving thread {index} of {total_threads} "
                        f"({current_message}/{thread_message_total} messages)."
                    ),
                    fetched_message_count=fetched_message_count,
                    thread_count=total_threads,
                    ai_thread_count=0,
                    stage_unit_current=overall_processed,
                    stage_unit_total=total_messages,
                )

            saved_thread = self.thread_repository.upsert_thread(
                thread,
                message_progress_callback=on_message_saved,
            )
            saved_threads.append(saved_thread)

            # Upsert contact personas from this thread's participants.
            if self.contact_repository is not None:
                for message in thread.messages:
                    recipients = message.recipients if hasattr(message, "recipients") else []
                    self.contact_repository.upsert_from_thread(
                        external_thread_id=thread.external_thread_id,
                        sender_raw=message.sender or "",
                        recipient_raws=recipients,
                        thread_date=message.sent_at,
                        ai_category=saved_thread.analysis.category.value if saved_thread.analysis else None,
                    )

            self.session.commit()
            self._raise_if_cancel_requested(run_id)
            processed_messages += len(thread.messages)
            self.progress_store.update(
                run_id,
                stage=SyncStage.PERSISTING,
                status_message=f"Saving threads ({index}/{total_threads}).",
                fetched_message_count=fetched_message_count,
                thread_count=total_threads,
                ai_thread_count=0,
                stage_unit_current=processed_messages,
                stage_unit_total=total_messages,
            )
            elapsed = perf_counter() - thread_started_at
            log_method = logger.warning if elapsed >= 2.5 else logger.info
            log_method(
                "Sync run %s persisted thread %s/%s id=%s messages=%s in %.2fs",
                run_id,
                index,
                total_threads,
                thread.external_thread_id,
                len(thread.messages),
                elapsed,
            )
        logger.info(
            "Sync run %s persisted %s threads / %s messages in %.2fs",
            run_id,
            total_threads,
            total_messages,
            perf_counter() - persistence_started_at,
        )
        return saved_threads

    def _apply_runtime_ai_strategy(self, grouped_threads: list) -> list:
        # When Claude or Local AI mode is active, every non-classified thread
        # should be analyzed by the selected provider — regardless of its
        # heuristic relevance score. Without this, low-relevance threads keep
        # their `included_in_ai = False` flag and always fall back to the
        # heuristic provider even when the user explicitly chose Claude.
        force_all = (
            self.runtime_settings.local_ai_analyzes_all_fetched_threads
            or self.runtime_settings.claude_enabled
            or self.runtime_settings.local_ai_enabled
        )
        if not force_all:
            return grouped_threads

        # Apply the safety cap: when local_ai_max_threads > 0, limit AI
        # analysis to the top N threads by relevance score. The rest get
        # the heuristic fallback so the app stays responsive on large mailboxes.
        max_threads = self.runtime_settings.local_ai_max_threads
        if max_threads > 0:
            eligible = [
                t for t in grouped_threads
                if t.security_status != SecurityStatus.CLASSIFIED
            ]
            eligible_sorted = sorted(
                eligible,
                key=lambda t: t.relevance_score or 0,
                reverse=True,
            )
            ai_thread_ids = {
                t.external_thread_id for t in eligible_sorted[:max_threads]
            }
        else:
            ai_thread_ids = None  # unlimited

        for thread in grouped_threads:
            if thread.security_status == SecurityStatus.CLASSIFIED:
                continue
            if ai_thread_ids is not None and thread.external_thread_id not in ai_thread_ids:
                # Over the cap — heuristic handles this one.
                thread.included_in_ai = False
                thread.ai_decision = "capped"
                thread.ai_decision_reason = (
                    f"Thread limit of {max_threads} reached — heuristic fallback used."
                )
                continue
            thread.included_in_ai = True
            thread.relevance_bucket = thread.relevance_bucket or RelevanceBucket.IMPORTANT
            if self.runtime_settings.local_ai_enabled:
                thread.ai_decision = "local_ai_all_threads"
                thread.ai_decision_reason = "Local AI mode is active — every thread is analyzed."
            elif self.runtime_settings.claude_enabled:
                thread.ai_decision = "claude_all_threads"
                thread.ai_decision_reason = "Claude mode is active — every thread is analyzed."
            else:
                thread.ai_decision = "manual_all_threads"
                thread.ai_decision_reason = "Every fetched email thread is configured to be analyzed."
            if thread.analysis_status == AnalysisStatus.SKIPPED:
                thread.analysis_status = AnalysisStatus.PENDING
        return grouped_threads

    def sync_supplemental_accounts(
        self,
        *,
        lookback_days: int = 7,
        max_results: int = 50,
    ) -> int:
        """Fetch and persist messages from all non-Gmail connected accounts.

        Called after the main Gmail sync completes. Does not create a new sync
        run record — threads are silently merged into the user's thread pool and
        analyzed by the same AI pipeline.

        Returns the total number of threads synced across all supplemental accounts.
        """
        from backend.core.config import get_settings
        from backend.core.crypto import decrypt_text
        from backend.persistence.repositories.email_account_repository import (
            EmailAccountRepository,
        )
        from backend.providers.gmail.mapper import group_messages_by_thread

        settings = get_settings()
        user_id = self.thread_repository.user_id
        accounts = EmailAccountRepository(self.session).list_models_for_user(user_id)

        total_synced = 0
        for account in accounts:
            if account.provider == "gmail":
                # Already handled by the main GmailSyncService run.
                continue
            if not account.credentials_encrypted:
                logger.warning(
                    "Supplemental sync: skipping %s (%s) — no credentials stored.",
                    account.email_address,
                    account.provider,
                )
                continue

            try:
                creds_json = decrypt_text(
                    account.credentials_encrypted,
                    settings.auth_token_encryption_key,
                )
                messages = self._fetch_from_provider(
                    provider=account.provider,
                    credentials_json=creds_json,
                    lookback_days=lookback_days,
                    max_results=max_results,
                )
                if not messages:
                    logger.info(
                        "Supplemental sync: no new messages from %s (%s)",
                        account.email_address,
                        account.provider,
                    )
                    continue

                # Tag messages sent by this account's owner with "SENT" so the
                # mapper can correctly set latest_from_me / waiting_on_us.
                # Gmail uses its own SENT label; non-Gmail providers need this.
                owner_email = account.email_address.lower()
                for msg in messages:
                    if owner_email in msg.from_address.lower() and "SENT" not in msg.label_ids:
                        msg.label_ids = list(msg.label_ids) + ["SENT"]

                grouped = group_messages_by_thread(messages)
                grouped = self._apply_runtime_ai_strategy(grouped)

                saved: list = []
                for thread in grouped:
                    saved_thread = self.thread_repository.upsert_thread(thread)
                    saved.append(saved_thread)
                self.session.commit()

                # Run AI analysis (no progress tracking — results appear silently).
                # Use the specific account's email so the AI knows who "you" are
                # in this mailbox (not just the Gmail address from runtime settings).
                analyzed = self.analysis_service.analyze_threads_with_progress(
                    saved,
                    progress_callback=lambda current, total, thread: None,
                    persist_callback=lambda _thread: self.session.commit(),
                    should_cancel=lambda: False,
                    user_email=account.email_address or None,
                )
                self.session.commit()
                total_synced += len(analyzed)
                logger.info(
                    "Supplemental sync: %s threads synced from %s (%s)",
                    len(analyzed),
                    account.email_address,
                    account.provider,
                )
            except Exception:
                logger.warning(
                    "Supplemental sync failed for %s (%s) — skipping.",
                    account.email_address,
                    account.provider,
                    exc_info=True,
                )

        return total_synced

    @staticmethod
    def _fetch_from_provider(
        *,
        provider: str,
        credentials_json: str,
        lookback_days: int,
        max_results: int,
    ) -> list:
        """Dispatch to the correct provider client and return InboundEmailMessage list."""
        if provider in ("imap", "icloud"):
            from backend.providers.imap.client import ImapClient

            client = ImapClient(credentials_json)
            return client.list_recent_messages(
                lookback_days=lookback_days,
                max_results=max_results,
            )
        if provider == "outlook":
            from backend.core.config import get_settings
            from backend.providers.outlook.client import OutlookClient

            s = get_settings()
            client = OutlookClient(
                client_id=s.outlook_client_id or "",
                client_secret=s.outlook_client_secret,
                tenant_id=s.outlook_tenant_id or "common",
                credentials_json=credentials_json,
            )
            return client.list_recent_messages(
                lookback_days=lookback_days,
                max_results=max_results,
            )
        logger.warning("Supplemental sync: unknown provider %r — skipping.", provider)
        return []

    def ensure_watch(self, topic: str) -> None:
        """Register or renew a Pub/Sub watch for the connected Gmail account.

        Called after every successful sync. Registers a new watch if none
        exists, or renews it when expiry is within 24 hours.

        Failures are logged as warnings and never propagate — losing push
        notifications degrades to polling but never breaks the sync itself.

        Args:
            topic: full Pub/Sub topic resource name (from AppSettings).
        """
        from datetime import datetime, timedelta, timezone

        from backend.persistence.repositories.runtime_settings_repository import (
            RuntimeSettingsRepository,
        )

        if not topic:
            return

        settings_repo = RuntimeSettingsRepository(
            self.session,
            self.thread_repository.user_id,
        )
        current = settings_repo.get()
        now = datetime.now(timezone.utc)
        expiry = current.gmail_watch_expiry

        # Renew if: no watch, expiry not set, or expiry within the next 24 hours.
        needs_renewal = expiry is None or expiry <= now + timedelta(hours=24)
        if not needs_renewal:
            return

        try:
            resource_id, new_expiry = self.gmail_client.register_watch(topic)
            settings_repo.update_gmail_watch(resource_id, new_expiry)
            self.session.commit()
            logger.info(
                "Gmail Pub/Sub watch registered resource_id=%r expires=%s",
                resource_id,
                new_expiry.isoformat(),
            )
        except Exception as exc:
            logger.warning(
                "Failed to register Gmail Pub/Sub watch (push notifications disabled "
                "until next successful sync): %s",
                exc,
            )

    def _persist_stage_progress(self, run_id: int, summary: SyncRunSummary) -> None:
        """Write a progress snapshot to the DB row at each stage transition.

        This is intentionally called only when the stage changes (not on every
        per-message tick) to keep DB write volume low while still making the
        last-known stage recoverable after a process restart.
        """
        try:
            self.sync_repository.update_progress(
                run_id,
                stage=summary.stage,
                progress_percent=summary.progress_percent,
                stage_unit_current=summary.stage_unit_current,
                stage_unit_total=summary.stage_unit_total,
                status_message=summary.status_message,
                eta_seconds=summary.eta_seconds,
            )
            self.eta_progress_repository.update_sync_phase(
                run_id=run_id,
                stage=summary.stage,
                status=summary.status,
                eta_seconds=summary.eta_seconds,
                progress_current=summary.stage_unit_current,
                progress_total=summary.stage_unit_total,
                status_message=summary.status_message,
            )
            self.session.commit()
        except Exception:
            # Progress persistence is best-effort — never let it abort the sync.
            logger.warning(
                "Failed to persist progress snapshot for run %s", run_id, exc_info=True
            )

    def _raise_if_cancel_requested(self, run_id: int) -> None:
        if self.progress_store.is_cancel_requested(run_id):
            raise SyncCancelledError()
