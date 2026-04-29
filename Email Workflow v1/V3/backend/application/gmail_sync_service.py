"""End-to-end Gmail sync and analysis workflow."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from time import perf_counter

from sqlalchemy.orm import Session

from backend.application.queue_service import QueueService
from backend.application.sync_progress_store import SyncProgressStore
from backend.application.thread_analysis_service import ThreadAnalysisService
from backend.domain.runtime_settings import RuntimeSettings
from backend.domain.sync import SyncRunSummary, SyncStage, SyncStatus
from backend.domain.thread import (
    AnalysisStatus,
    EmailThread,
    RelevanceBucket,
    SecurityStatus,
)
from backend.persistence.repositories.contact_repository import ContactRepository
from backend.persistence.repositories.sync_repository import SyncRepository
from backend.persistence.repositories.thread_repository import ThreadRepository
from backend.providers.gmail.client import GmailReadonlyClient
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
    ) -> None:
        self.session = session
        self.runtime_settings = runtime_settings
        self.gmail_client = gmail_client
        self.thread_repository = thread_repository
        self.sync_repository = sync_repository
        self.analysis_service = analysis_service
        self.queue_service = queue_service
        self.progress_store = progress_store
        self.contact_repository = ContactRepository(session)

    def create_run(self, source: str) -> SyncRunSummary:
        run = self.sync_repository.start_run(source)
        self.session.commit()
        return self.progress_store.start(run.id, source)

    def get_run_status(self, run_id: int) -> SyncRunSummary | None:
        progress = self.progress_store.get(run_id)
        if progress:
            return progress
        return self.sync_repository.get_run(run_id)

    def get_latest_run_status(self) -> SyncRunSummary | None:
        progress = self.progress_store.latest()
        if progress:
            return progress
        return self.sync_repository.get_latest_run()

    def get_running_run(self) -> SyncRunSummary | None:
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
        try:
            sync_started_at = perf_counter()
            logger.info(
                "Sync run %s started source=%s max_results=%s lookback_days=%s",
                run_id,
                source,
                max_results,
                lookback_days,
            )
            self.progress_store.update(
                run_id,
                stage=SyncStage.FETCHING,
                progress_percent=12,
                status_message="Fetching recent Gmail threads.",
            )
            fetch_started_at = perf_counter()
            known_message_ids = self.thread_repository.get_known_message_ids()
            messages = self.gmail_client.list_recent_messages(
                max_results=max_results,
                source=source,
                lookback_days=lookback_days,
                known_message_ids=known_message_ids,
            )
            fetched_message_count = len(messages)
            self._raise_if_cancel_requested(run_id)
            logger.info(
                "Sync run %s fetched %s Gmail messages in %.2fs",
                run_id,
                len(messages),
                perf_counter() - fetch_started_at,
            )
            self.progress_store.update(
                run_id,
                stage=SyncStage.PERSISTING,
                progress_percent=36,
                status_message=f"Fetched {len(messages)} messages. Grouping threads.",
                fetched_message_count=len(messages),
            )
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
            self.session.commit()
            self._raise_if_cancel_requested(run_id)

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
            self.progress_store.update(
                run_id,
                stage=SyncStage.ANALYZING,
                progress_percent=52,
                status_message=(
                    f"Analyzing {len(saved_threads)} threads with your local AI agent."
                    if self.runtime_settings.local_ai_enabled
                    else f"Analyzing {len(saved_threads)} threads for next actions."
                ),
                fetched_message_count=len(messages),
                thread_count=len(saved_threads),
                ai_thread_count=ai_thread_count,
            )
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
                progress_callback=lambda current, total, _: self._update_analysis_progress(
                    run_id=run_id,
                    current=current,
                    total=total,
                    fetched_message_count=len(messages),
                    thread_count=len(saved_threads),
                    ai_thread_count=ai_thread_count,
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
            self.progress_store.update(
                run_id,
                stage=SyncStage.SUMMARIZING,
                progress_percent=90,
                status_message="Building your queue summary.",
                fetched_message_count=len(messages),
                thread_count=len(analyzed_threads),
                ai_thread_count=len(
                    [thread for thread in analyzed_threads if thread.included_in_ai]
                ),
            )
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
            self.session.commit()
            logger.info(
                "Sync run %s completed in %.2fs",
                run_id,
                perf_counter() - sync_started_at,
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
    ) -> None:
        if total <= 0:
            progress_percent = 82
            status_message = "Thread analysis complete."
        else:
            progress_percent = 52 + int((current / total) * 30)
            status_message = f"Analyzing threads ({current}/{total})."
        self.progress_store.update(
            run_id,
            stage=SyncStage.ANALYZING,
            progress_percent=progress_percent,
            status_message=status_message,
            fetched_message_count=fetched_message_count,
            thread_count=thread_count,
            ai_thread_count=ai_thread_count,
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
                progress_percent=40,
                status_message="No threads to save from the latest fetch.",
                fetched_message_count=fetched_message_count,
                thread_count=0,
                ai_thread_count=0,
            )
            return []

        saved_threads = []
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
                progress_percent=self._persistence_progress_percent(
                    processed_messages,
                    total_messages,
                ),
                status_message=f"Saving thread {index} of {total_threads}.",
                fetched_message_count=fetched_message_count,
                thread_count=index - 1,
                ai_thread_count=0,
            )

            def on_message_saved(current_message: int, thread_message_total: int) -> None:
                overall_processed = processed_messages + current_message
                self.progress_store.update(
                    run_id,
                    stage=SyncStage.PERSISTING,
                    progress_percent=self._persistence_progress_percent(
                        overall_processed,
                        total_messages,
                    ),
                    status_message=(
                        f"Saving thread {index} of {total_threads} "
                        f"({current_message}/{thread_message_total} messages)."
                    ),
                    fetched_message_count=fetched_message_count,
                    thread_count=index - 1,
                    ai_thread_count=0,
                )

            saved_thread = self.thread_repository.upsert_thread(
                thread,
                message_progress_callback=on_message_saved,
            )
            saved_threads.append(saved_thread)

            # Upsert contact personas from this thread's participants.
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
                progress_percent=self._persistence_progress_percent(
                    processed_messages,
                    total_messages,
                ),
                status_message=f"Saving threads ({index}/{total_threads}).",
                fetched_message_count=fetched_message_count,
                thread_count=index,
                ai_thread_count=0,
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

        for thread in grouped_threads:
            if thread.security_status == SecurityStatus.CLASSIFIED:
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

    @staticmethod
    def _persistence_progress_percent(
        processed_messages: int,
        total_messages: int,
    ) -> int:
        if total_messages <= 0:
            return 40
        return 36 + int((processed_messages / total_messages) * 22)

    def _raise_if_cancel_requested(self, run_id: int) -> None:
        if self.progress_store.is_cancel_requested(run_id):
            raise SyncCancelledError()
