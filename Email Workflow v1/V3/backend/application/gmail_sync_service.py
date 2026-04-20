"""End-to-end Gmail sync and analysis workflow."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from time import perf_counter

from sqlalchemy.orm import Session

from backend.application.queue_service import QueueService
from backend.application.sync_progress_store import SyncProgressStore
from backend.application.thread_analysis_service import ThreadAnalysisService
from backend.domain.sync import SyncRunSummary, SyncStage, SyncStatus
from backend.persistence.repositories.sync_repository import SyncRepository
from backend.persistence.repositories.thread_repository import ThreadRepository
from backend.providers.gmail.client import GmailReadonlyClient
from backend.providers.gmail.mapper import group_messages_by_thread


logger = logging.getLogger(__name__)


class GmailSyncService:
    """Owns the main sync -> persist -> analyze -> summarize workflow."""

    def __init__(
        self,
        session: Session,
        gmail_client: GmailReadonlyClient,
        thread_repository: ThreadRepository,
        sync_repository: SyncRepository,
        analysis_service: ThreadAnalysisService,
        queue_service: QueueService,
        progress_store: SyncProgressStore,
    ) -> None:
        self.session = session
        self.gmail_client = gmail_client
        self.thread_repository = thread_repository
        self.sync_repository = sync_repository
        self.analysis_service = analysis_service
        self.queue_service = queue_service
        self.progress_store = progress_store

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

    def sync_recent_threads(
        self,
        run_id: int,
        source: str,
        max_results: int,
    ) -> SyncRunSummary:
        run = self.sync_repository.get_run_model(run_id)
        if run is None:
            raise ValueError(f"Sync run `{run_id}` was not found.")

        fetched_message_count = 0
        persisted_thread_count = 0
        analyzed_thread_count = 0
        ai_thread_count = 0
        try:
            sync_started_at = perf_counter()
            logger.info(
                "Sync run %s started source=%s max_results=%s",
                run_id,
                source,
                max_results,
            )
            self.progress_store.update(
                run_id,
                stage=SyncStage.FETCHING,
                progress_percent=12,
                status_message="Fetching recent Gmail threads.",
            )
            fetch_started_at = perf_counter()
            messages = self.gmail_client.list_recent_messages(
                max_results=max_results,
                source=source,
            )
            fetched_message_count = len(messages)
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
            persisted_thread_count = len(saved_threads)
            ai_thread_count = len(
                [thread for thread in saved_threads if thread.included_in_ai]
            )
            self.progress_store.update(
                run_id,
                stage=SyncStage.ANALYZING,
                progress_percent=52,
                status_message=f"Analyzing {len(saved_threads)} threads for next actions.",
                fetched_message_count=len(messages),
                thread_count=len(saved_threads),
                ai_thread_count=ai_thread_count,
            )
            analysis_started_at = perf_counter()
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
            )
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

    @staticmethod
    def _persistence_progress_percent(
        processed_messages: int,
        total_messages: int,
    ) -> int:
        if total_messages <= 0:
            return 40
        return 36 + int((processed_messages / total_messages) * 22)
