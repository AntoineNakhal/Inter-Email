"""Thread repository and mapping helpers."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from time import sleep

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.exc import OperationalError

from backend.domain.thread import (
    AnalysisStatus,
    DraftDocument,
    EmailThread,
    ReviewDecision,
    SeenState,
    ThreadAnalysis,
    ThreadMessage,
)
from backend.persistence.models.draft import DraftModel
from backend.persistence.models.review import ReviewDecisionModel
from backend.persistence.models.thread import (
    EmailThreadModel,
    ThreadAnalysisModel,
    ThreadMessageModel,
    ThreadStateModel,
)


class ThreadRepository:
    """Repository for thread, analysis, and seen-state persistence."""

    def __init__(self, session: Session, user_id: int) -> None:
        self.session = session
        self.user_id = user_id

    def get_threads_with_stale_analysis(self, expected_provider: str) -> list[EmailThread]:
        """Return threads whose analysis was produced by a different provider.

        Used by the sync service to re-analyze threads that were skipped at
        fetch time (already-known message IDs) but whose analysis belongs to
        an old provider (e.g. heuristic) while the current mode uses Claude.
        """

        query = (
            select(EmailThreadModel)
            .join(ThreadAnalysisModel, isouter=False)
            .where(
                EmailThreadModel.user_id == self.user_id,
                ThreadAnalysisModel.provider_name != expected_provider,
            )
            .options(
                selectinload(EmailThreadModel.messages),
                selectinload(EmailThreadModel.analysis),
                selectinload(EmailThreadModel.review),
                selectinload(EmailThreadModel.state),
                selectinload(EmailThreadModel.drafts),
                selectinload(EmailThreadModel.override),
            )
        )
        models = self.session.scalars(query).all()
        return [self._to_domain(model) for model in models]

    def get_known_message_ids(self) -> set[str]:
        """Return the set of all message IDs currently stored in the DB.

        Used by the sync service to skip Gmail threads that have not received
        any new messages since the last sync — avoiding redundant threads.get
        API calls and re-analysis of unchanged content.
        """

        rows = self.session.scalars(
            select(ThreadMessageModel.external_message_id).where(
                ThreadMessageModel.user_id == self.user_id
            )
        ).all()
        return {str(mid) for mid in rows if mid}

    def list_threads(self) -> list[EmailThread]:

        query = (
            select(EmailThreadModel)
            .where(EmailThreadModel.user_id == self.user_id)
            .options(
                selectinload(EmailThreadModel.messages),
                selectinload(EmailThreadModel.analysis),
                selectinload(EmailThreadModel.review),
                selectinload(EmailThreadModel.state),
                selectinload(EmailThreadModel.drafts),
                selectinload(EmailThreadModel.override),
            )
            .order_by(EmailThreadModel.latest_message_date.desc())
        )
        models = self.session.scalars(query).all()
        return [self._to_domain(model) for model in models]

    def get_thread(self, external_thread_id: str) -> EmailThread | None:

        query = (
            select(EmailThreadModel)
            .where(
                EmailThreadModel.user_id == self.user_id,
                EmailThreadModel.external_thread_id == external_thread_id,
            )
            .options(
                selectinload(EmailThreadModel.messages),
                selectinload(EmailThreadModel.analysis),
                selectinload(EmailThreadModel.review),
                selectinload(EmailThreadModel.state),
                selectinload(EmailThreadModel.drafts),
                selectinload(EmailThreadModel.override),
            )
        )
        model = self.session.scalar(query)
        return self._to_domain(model) if model else None

    def upsert_thread(
        self,
        thread: EmailThread,
        message_progress_callback: Callable[[int, int], None] | None = None,
    ) -> EmailThread:

        model = self.session.scalar(
            select(EmailThreadModel).where(
                EmailThreadModel.user_id == self.user_id,
                EmailThreadModel.external_thread_id == thread.external_thread_id
            )
        )
        if model is None:
            model = EmailThreadModel(
                user_id=self.user_id,
                external_thread_id=thread.external_thread_id,
            )
            self.session.add(model)

        previous_signature = model.signature
        next_signature = thread.signature or thread.compute_signature()
        signature_unchanged = (
            bool(previous_signature)
            and previous_signature == next_signature
            and model.analysis is not None
        )

        # Mark as new when the thread receives a fresh message.
        if not signature_unchanged:
            model.is_new = True

        # Auto-reset "done" state when the thread has new content.
        # seen_version is set to the thread signature at the time the user
        # clicked Done. If the signature has since changed (new message
        # arrived), the action is no longer done — surface it again.
        if (
            model.state is not None
            and model.state.seen
            and model.state.seen_version != next_signature
        ):
            model.state.seen = False
            model.state.seen_version = ""
            model.state.seen_at = None

        model.subject = thread.subject
        model.participants_json = json.dumps(thread.participants, ensure_ascii=False)
        model.message_count = thread.message_count
        model.latest_message_date = thread.latest_message_date
        model.combined_thread_text = thread.combined_thread_text
        model.security_status = thread.security_status.value
        model.sensitivity_markers_json = json.dumps(
            thread.sensitivity_markers,
            ensure_ascii=False,
        )
        model.latest_message_from_me = thread.latest_message_from_me
        model.latest_message_from_external = thread.latest_message_from_external
        model.latest_message_has_question = thread.latest_message_has_question
        model.latest_message_has_action_request = thread.latest_message_has_action_request
        model.waiting_on_us = thread.waiting_on_us
        model.resolved_or_closed = thread.resolved_or_closed
        model.relevance_score = thread.relevance_score
        model.relevance_bucket = (
            thread.relevance_bucket.value if thread.relevance_bucket else None
        )
        model.included_in_ai = thread.included_in_ai
        model.ai_decision = thread.ai_decision
        model.ai_decision_reason = thread.ai_decision_reason
        model.analysis_status = (
            AnalysisStatus.COMPLETE.value
            if signature_unchanged
            else thread.analysis_status.value
        )
        model.signature = next_signature
        model.is_service_email = thread.is_service_email
        model.last_synced_at = datetime.now(timezone.utc)
        model.grouping_reason = thread.grouping_reason or "gmail_thread_id"
        model.merge_signals_json = json.dumps(thread.merge_signals, ensure_ascii=False)
        model.source_thread_ids_json = json.dumps(thread.source_thread_ids, ensure_ascii=False)

        incoming_message_ids = _dedupe_message_ids(
            [message.external_message_id for message in thread.messages]
        )
        existing_messages = self._load_existing_messages(incoming_message_ids)
        seen_message_ids: set[str] = set()
        displaced_threads: dict[int, EmailThreadModel] = {}
        total_messages = len(incoming_message_ids)
        saved_message_count = 0
        for message in thread.messages:
            message_id = str(message.external_message_id or "").strip()
            if not message_id or message_id in seen_message_ids:
                continue

            saved_message_count += 1
            seen_message_ids.add(message_id)
            message_model = existing_messages.pop(message_id, None)
            if message_model is None:
                message_model = ThreadMessageModel(
                    user_id=self.user_id,
                    external_message_id=message_id,
                )
                model.messages.append(message_model)
            elif message_model.thread is not model:
                previous_thread = message_model.thread
                if previous_thread is not None:
                    displaced_threads[id(previous_thread)] = previous_thread
                model.messages.append(message_model)

            message_model.sender = message.sender
            message_model.recipients_json = json.dumps(
                message.recipients,
                ensure_ascii=False,
            )
            message_model.subject = message.subject
            message_model.sent_at = message.sent_at
            message_model.snippet = message.snippet
            message_model.cleaned_body = message.cleaned_body
            message_model.label_ids_json = json.dumps(
                message.label_ids,
                ensure_ascii=False,
            )
            message_model.is_forwarded = message.is_forwarded
            if message.original_gmail_thread_id:
                message_model.original_gmail_thread_id = message.original_gmail_thread_id
            if message_progress_callback is not None:
                message_progress_callback(saved_message_count, total_messages)

        for stale_message in list(model.messages):
            if stale_message.external_message_id not in seen_message_ids:
                model.messages.remove(stale_message)

        for displaced_thread in displaced_threads.values():
            if displaced_thread is model:
                continue
            if not displaced_thread.messages:
                self.session.delete(displaced_thread)

        self.session.flush()
        return self._to_domain(model)

    def delete_threads(
        self,
        external_thread_ids: list[str],
    ) -> None:

        normalized_ids = [
            str(thread_id).strip()
            for thread_id in external_thread_ids
            if str(thread_id or "").strip()
        ]
        if not normalized_ids:
            return

        models = self.session.scalars(
            select(EmailThreadModel).where(
                EmailThreadModel.user_id == self.user_id,
                EmailThreadModel.external_thread_id.in_(normalized_ids)
            )
        ).all()
        for model in models:
            self.session.delete(model)
        self.session.flush()

    def clear_all(self) -> None:

        models = self.session.scalars(
            select(EmailThreadModel).where(EmailThreadModel.user_id == self.user_id)
        ).all()
        for model in models:
            self.session.delete(model)
        self.session.flush()

    def restore_threads_snapshot(self, threads: list[EmailThread]) -> list[EmailThread]:

        self.clear_all()
        restored_threads: list[EmailThread] = []
        for thread in threads:
            restored_thread = self.upsert_thread(thread)
            if thread.analysis is not None:
                restored_thread = self.save_analysis(
                    thread.external_thread_id,
                    thread.analysis,
                )
            self._restore_thread_extras(thread)
            restored_threads.append(
                self.get_thread(thread.external_thread_id) or restored_thread
            )
        self.session.flush()
        return restored_threads

    def save_analysis(
        self,
        external_thread_id: str,
        analysis: ThreadAnalysis,
    ) -> EmailThread:

        model = self._require_thread_model(external_thread_id)
        if model.analysis is None:
            model.analysis = ThreadAnalysisModel()

        model.analysis.category = analysis.category.value
        model.analysis.urgency = analysis.urgency.value
        model.analysis.summary = analysis.summary
        model.analysis.current_status = analysis.current_status
        model.analysis.next_action = analysis.next_action
        model.analysis.needs_next_action = analysis.needs_next_action
        model.analysis.needs_action_today = analysis.needs_action_today
        # Let Claude override the heuristic waiting_on_us when it has an opinion.
        if analysis.waiting_on_us is not None:
            model.waiting_on_us = analysis.waiting_on_us
        model.analysis.should_draft_reply = analysis.should_draft_reply
        model.analysis.draft_needs_date = analysis.draft_needs_date
        model.analysis.draft_date_reason = analysis.draft_date_reason
        model.analysis.draft_needs_attachment = analysis.draft_needs_attachment
        model.analysis.draft_attachment_reason = analysis.draft_attachment_reason
        model.analysis.crm_contact_name = analysis.crm_contact_name
        model.analysis.crm_company = analysis.crm_company
        model.analysis.crm_opportunity_type = analysis.crm_opportunity_type
        model.analysis.crm_urgency = (
            analysis.crm_urgency.value if analysis.crm_urgency else None
        )
        model.analysis.provider_name = analysis.provider_name
        model.analysis.model_name = analysis.model_name
        model.analysis.prompt_version = analysis.prompt_version
        model.analysis.used_fallback = analysis.used_fallback
        model.analysis.accuracy_percent = analysis.accuracy_percent
        model.analysis.verification_summary = analysis.verification_summary
        model.analysis.needs_human_review = analysis.needs_human_review
        model.analysis.review_reason = analysis.review_reason
        model.analysis.verifier_provider_name = analysis.verifier_provider_name
        model.analysis.verifier_model_name = analysis.verifier_model_name
        model.analysis.verifier_used_fallback = analysis.verifier_used_fallback
        model.analysis.analyzed_at = analysis.analyzed_at
        model.analysis.verified_at = analysis.verified_at
        model.analysis.ai_override_disagreements_json = json.dumps(
            analysis.ai_override_disagreements, ensure_ascii=False
        )
        model.analysis.thread = model
        model.analysis_status = AnalysisStatus.COMPLETE.value
        model.last_analyzed_at = analysis.analyzed_at
        self.session.flush()
        return self.get_thread(external_thread_id) or self._to_domain(model)

    def mark_seen(self, external_thread_id: str, seen: bool, version: str) -> EmailThread:

        last_error: OperationalError | None = None
        for attempt in range(3):
            model = self._require_thread_model(external_thread_id)
            if model.state is None:
                model.state = ThreadStateModel()
            model.state.seen = seen
            model.state.seen_version = version
            model.state.seen_at = datetime.now(timezone.utc) if seen else None
            # When marking done, clear the "act today" flag and unpin —
            # the action has been handled. The next sync will re-evaluate
            # if a new message arrives and the thread resurfaces.
            if seen and model.analysis is not None:
                model.analysis.needs_next_action = False
                model.analysis.needs_action_today = False
            if seen and model.state is not None:
                model.state.pinned = False
            try:
                self.session.flush()
                return self.get_thread(external_thread_id) or self._to_domain(model)
            except OperationalError as exc:
                if not _is_sqlite_locked_error(exc) or attempt == 2:
                    raise
                last_error = exc
                self.session.rollback()
                sleep(0.15 * (attempt + 1))

        if last_error is not None:
            raise last_error
        raise RuntimeError("mark_seen retry loop ended unexpectedly")

    def clear_draft(self, external_thread_id: str) -> None:
        """Delete the stored draft for a thread after it has been sent."""

        model = self._require_thread_model(external_thread_id)
        model.drafts.clear()
        self.session.flush()

    def append_outgoing_message(
        self,
        external_thread_id: str,
        external_message_id: str,
        sender: str,
        recipients: list[str],
        subject: str,
        body: str,
        sent_at: datetime | None = None,
    ) -> EmailThread:

        model = self._require_thread_model(external_thread_id)
        normalized_message_id = str(external_message_id or "").strip()
        if not normalized_message_id:
            raise ValueError("Outgoing message ID is required.")

        message_model = self.session.scalar(
            select(ThreadMessageModel).where(
                ThreadMessageModel.user_id == self.user_id,
                ThreadMessageModel.external_message_id == normalized_message_id
            )
        )
        if message_model is None:
            message_model = ThreadMessageModel(
                user_id=self.user_id,
                external_message_id=normalized_message_id,
            )
            model.messages.append(message_model)
        elif message_model.thread is not model:
            previous_thread = message_model.thread
            model.messages.append(message_model)
            if previous_thread is not None and not previous_thread.messages:
                self.session.delete(previous_thread)

        normalized_body = body.strip()
        effective_sent_at = sent_at or datetime.now(timezone.utc)
        message_model.sender = sender
        message_model.recipients_json = json.dumps(recipients, ensure_ascii=False)
        message_model.subject = subject
        message_model.sent_at = effective_sent_at
        message_model.snippet = normalized_body[:240]
        message_model.cleaned_body = normalized_body
        message_model.label_ids_json = json.dumps(["SENT"], ensure_ascii=False)

        model.subject = subject or model.subject
        current_participants = set(_load_json_list(model.participants_json))
        current_participants.add(sender)
        current_participants.update(recipients)
        model.participants_json = json.dumps(sorted(current_participants), ensure_ascii=False)
        model.message_count = len(model.messages)
        model.latest_message_date = effective_sent_at
        model.latest_message_from_me = True
        model.latest_message_from_external = False
        model.latest_message_has_question = "?" in f"{subject}\n{normalized_body}"
        model.latest_message_has_action_request = False
        model.waiting_on_us = False
        model.analysis_status = AnalysisStatus.PENDING.value
        model.last_synced_at = datetime.now(timezone.utc)
        model.last_analyzed_at = None
        model.is_new = False

        domain = self._to_domain(model)
        model.combined_thread_text = "\n\n".join(
            part.strip()
            for part in [domain.combined_thread_text, normalized_body]
            if part and part.strip()
        )
        refreshed_domain = self._to_domain(model)
        model.signature = refreshed_domain.compute_signature()

        self.session.flush()
        return self.get_thread(external_thread_id) or self._to_domain(model)

    def acknowledge(self, external_thread_id: str) -> EmailThread:
        """Mark a thread as seen (new notification cleared). Separate from done."""

        model = self._require_thread_model(external_thread_id)
        model.is_new = False
        self.session.flush()
        return self.get_thread(external_thread_id) or self._to_domain(model)

    def acknowledge_batch(self, external_thread_ids: list[str]) -> int:
        """Clear is_new for a specific set of threads."""

        if not external_thread_ids:
            return 0
        models = self.session.scalars(
            select(EmailThreadModel).where(
                EmailThreadModel.user_id == self.user_id,
                EmailThreadModel.external_thread_id.in_(external_thread_ids),
                EmailThreadModel.is_new == True,  # noqa: E712
            )
        ).all()
        for m in models:
            m.is_new = False
        self.session.flush()
        return len(models)

    def acknowledge_all(self) -> int:
        """Clear is_new on all threads. Returns number of threads acknowledged."""

        models = self.session.scalars(
            select(EmailThreadModel).where(  # noqa: E712
                EmailThreadModel.user_id == self.user_id,
                EmailThreadModel.is_new == True,
            )
        ).all()
        for m in models:
            m.is_new = False
        self.session.flush()
        return len(models)

    def mark_pinned(self, external_thread_id: str, pinned: bool) -> EmailThread:

        model = self._require_thread_model(external_thread_id)
        if model.state is None:
            model.state = ThreadStateModel()
        model.state.pinned = pinned
        self.session.flush()
        return self.get_thread(external_thread_id) or self._to_domain(model)

    def _require_thread_model(self, external_thread_id: str) -> EmailThreadModel:

        model = self.session.scalar(
            select(EmailThreadModel).where(
                EmailThreadModel.user_id == self.user_id,
                EmailThreadModel.external_thread_id == external_thread_id
            )
        )
        if model is None:
            raise ValueError(f"Thread `{external_thread_id}` was not found.")
        return model

    def _load_existing_messages(
        self,
        external_message_ids: list[str],
    ) -> dict[str, ThreadMessageModel]:

        if not external_message_ids:
            return {}
        models = self.session.scalars(
            select(ThreadMessageModel).where(
                ThreadMessageModel.user_id == self.user_id,
                ThreadMessageModel.external_message_id.in_(external_message_ids)
            )
        ).all()
        return {
            model.external_message_id: model
            for model in models
        }

    def _restore_thread_extras(self, thread: EmailThread) -> None:
        model = self._require_thread_model(thread.external_thread_id)

        if thread.seen_state is not None:
            if model.state is None:
                model.state = ThreadStateModel(thread=model)
                self.session.add(model.state)
            model.state.seen = thread.seen_state.seen
            model.state.seen_version = thread.seen_state.seen_version
            model.state.seen_at = thread.seen_state.seen_at
            model.state.pinned = thread.seen_state.pinned

        if thread.review is not None:
            if model.review is None:
                model.review = ReviewDecisionModel(thread=model)
                self.session.add(model.review)
            model.review.queue_belongs = thread.review.queue_belongs
            model.review.merge_correct = thread.review.merge_correct
            model.review.summary_useful = thread.review.summary_useful
            model.review.next_action_useful = thread.review.next_action_useful
            model.review.draft_useful = thread.review.draft_useful
            model.review.crm_useful = thread.review.crm_useful
            model.review.notes = thread.review.notes
            model.review.improvement_tags_json = json.dumps(
                thread.review.improvement_tags,
                ensure_ascii=False,
            )
            model.review.reviewed_at = thread.review.updated_at

        if thread.latest_draft is not None:
            model.drafts.clear()
            draft = DraftModel(
                thread=model,
                subject=thread.latest_draft.subject,
                body=thread.latest_draft.body,
                provider_name=thread.latest_draft.provider_name,
                model_name=thread.latest_draft.model_name,
                used_fallback=thread.latest_draft.used_fallback,
            )
            if thread.latest_draft.created_at is not None:
                draft.created_at = thread.latest_draft.created_at
            self.session.add(draft)

    def _to_domain(self, model: EmailThreadModel) -> EmailThread:
        latest_draft = model.drafts[0] if model.drafts else None
        return EmailThread(
            external_thread_id=model.external_thread_id,
            source_thread_ids=_load_json_list(model.source_thread_ids_json) or [model.external_thread_id],
            grouping_reason=model.grouping_reason or "gmail_thread_id",
            merge_signals=_load_json_list(model.merge_signals_json),
            subject=model.subject,
            participants=_load_json_list(model.participants_json),
            message_count=model.message_count,
            latest_message_date=model.latest_message_date,
            messages=[
                ThreadMessage(
                    external_message_id=message.external_message_id,
                    sender=message.sender,
                    recipients=_load_json_list(message.recipients_json),
                    subject=message.subject,
                    sent_at=message.sent_at,
                    snippet=message.snippet,
                    cleaned_body=message.cleaned_body,
                    label_ids=_load_json_list(message.label_ids_json),
                    is_forwarded=bool(message.is_forwarded),
                    original_gmail_thread_id=message.original_gmail_thread_id or "",
                )
                for message in model.messages
            ],
            combined_thread_text=model.combined_thread_text,
            security_status=model.security_status,
            sensitivity_markers=_load_json_list(model.sensitivity_markers_json),
            latest_message_from_me=model.latest_message_from_me,
            latest_message_from_external=model.latest_message_from_external,
            latest_message_has_question=model.latest_message_has_question,
            latest_message_has_action_request=model.latest_message_has_action_request,
            waiting_on_us=model.waiting_on_us,
            resolved_or_closed=model.resolved_or_closed,
            relevance_score=model.relevance_score,
            relevance_bucket=model.relevance_bucket,
            included_in_ai=model.included_in_ai,
            ai_decision=model.ai_decision,
            ai_decision_reason=model.ai_decision_reason,
            analysis_status=model.analysis_status,
            signature=model.signature,
            is_new=bool(model.is_new),
            is_service_email=bool(model.is_service_email),
            last_synced_at=model.last_synced_at,
            last_analyzed_at=model.last_analyzed_at,
            analysis=_to_analysis(model.analysis),
            seen_state=_to_seen_state(model.state),
            review=_to_review(model.review),
            latest_draft=_to_draft(latest_draft),
            override=_to_override(model.override),
        )

    def split_thread(self, external_thread_id: str, user_id: int) -> list[EmailThread]:
        """Split a merged thread back into its original Gmail threads.

        Groups messages by their original_gmail_thread_id and creates a
        separate email_threads row for each group. The merged thread is deleted.
        Returns the newly created threads.
        """
        model = self._require_thread_model(external_thread_id, user_id)
        source_ids = _load_json_list(model.source_thread_ids_json)

        if len(source_ids) <= 1:
            raise ValueError(
                f"Thread {external_thread_id!r} was not merged — nothing to split."
            )

        # Group messages by their original Gmail thread ID
        groups: dict[str, list] = {}
        for msg in model.messages:
            origin = msg.original_gmail_thread_id or model.external_thread_id
            groups.setdefault(origin, []).append(msg)

        if len(groups) <= 1:
            raise ValueError(
                f"Thread {external_thread_id!r} messages all share the same origin — "
                "cannot determine split boundary."
            )

        new_threads: list[EmailThread] = []
        for origin_thread_id, messages in groups.items():
            new_model = EmailThreadModel(
                user_id=user_id,
                external_thread_id=origin_thread_id,
                subject=messages[0].subject if messages else model.subject,
                participants_json=model.participants_json,
                message_count=len(messages),
                combined_thread_text=model.combined_thread_text,
                security_status=model.security_status,
                sensitivity_markers_json=model.sensitivity_markers_json,
                analysis_status="pending",
                signature="",
                grouping_reason="gmail_thread_id",
                merge_signals_json="[]",
                source_thread_ids_json=json.dumps([origin_thread_id]),
            )
            self.session.add(new_model)
            self.session.flush()  # get new_model.id

            for msg in messages:
                msg.thread_id = new_model.id
                msg.thread = new_model

            new_threads.append(self._to_domain(new_model))

        self.session.delete(model)
        self.session.flush()
        return new_threads


def _load_json_dict(payload: str | None) -> dict[str, str]:
    if not payload:
        return {}
    try:
        value = json.loads(payload)
    except json.JSONDecodeError:
        return {}
    return {str(k): str(v) for k, v in value.items()} if isinstance(value, dict) else {}


def _load_json_list(payload: str | None) -> list[str]:
    if not payload:
        return []
    try:
        value = json.loads(payload)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in value] if isinstance(value, list) else []


def _dedupe_message_ids(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _is_sqlite_locked_error(exc: OperationalError) -> bool:
    return "database is locked" in str(exc).lower()


def _to_analysis(model: ThreadAnalysisModel | None) -> ThreadAnalysis | None:
    if model is None:
        return None
    return ThreadAnalysis(
        category=model.category,
        urgency=model.urgency,
        summary=model.summary,
        current_status=model.current_status,
        next_action=model.next_action,
        needs_next_action=model.needs_next_action,
        needs_action_today=model.needs_action_today,
        should_draft_reply=model.should_draft_reply,
        draft_needs_date=model.draft_needs_date,
        draft_date_reason=model.draft_date_reason,
        draft_needs_attachment=model.draft_needs_attachment,
        draft_attachment_reason=model.draft_attachment_reason,
        crm_contact_name=model.crm_contact_name,
        crm_company=model.crm_company,
        crm_opportunity_type=model.crm_opportunity_type,
        crm_urgency=model.crm_urgency,
        provider_name=model.provider_name,
        model_name=model.model_name,
        prompt_version=model.prompt_version,
        used_fallback=model.used_fallback,
        accuracy_percent=model.accuracy_percent,
        verification_summary=model.verification_summary,
        needs_human_review=model.needs_human_review,
        review_reason=model.review_reason,
        verifier_provider_name=model.verifier_provider_name,
        verifier_model_name=model.verifier_model_name,
        verifier_used_fallback=model.verifier_used_fallback,
        analyzed_at=model.analyzed_at,
        verified_at=model.verified_at,
        ai_override_disagreements=_load_json_dict(model.ai_override_disagreements_json),
    )


def _to_review(model: ReviewDecisionModel | None) -> ReviewDecision | None:
    if model is None:
        return None
    return ReviewDecision(
        queue_belongs=model.queue_belongs,
        merge_correct=model.merge_correct,
        summary_useful=model.summary_useful,
        next_action_useful=model.next_action_useful,
        draft_useful=model.draft_useful,
        crm_useful=model.crm_useful,
        notes=model.notes,
        improvement_tags=_load_json_list(model.improvement_tags_json),
        updated_at=model.reviewed_at,
    )


def _to_seen_state(model: ThreadStateModel | None) -> SeenState | None:
    if model is None:
        return None
    return SeenState(
        seen=model.seen,
        seen_version=model.seen_version,
        seen_at=model.seen_at,
        pinned=model.pinned,
    )


def _to_draft(model: DraftModel | None) -> DraftDocument | None:
    if model is None:
        return None
    return DraftDocument(
        subject=model.subject,
        body=model.body,
        provider_name=model.provider_name,
        model_name=model.model_name,
        used_fallback=model.used_fallback,
        created_at=model.created_at,
    )


def _to_override(model: "ThreadOverrideModel | None") -> "ThreadOverride | None":
    if model is None:
        return None
    from backend.domain.override import ThreadOverride
    from backend.domain.thread import RelevanceBucket, TriageCategory, UrgencyLevel
    return ThreadOverride(
        category=TriageCategory(model.category) if model.category else None,
        urgency=UrgencyLevel(model.urgency) if model.urgency else None,
        needs_action_today=model.needs_action_today,
        waiting_on_us=model.waiting_on_us,
        needs_next_action=model.needs_next_action,
        should_draft_reply=model.should_draft_reply,
        relevance_bucket=RelevanceBucket(model.relevance_bucket) if model.relevance_bucket else None,
        notes=model.notes or "",
        overridden_at=model.created_at,
        updated_at=model.updated_at,
    )
