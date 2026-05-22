"""Draft persistence helpers."""

from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.thread import DraftDocument, KbDraftSource
from backend.persistence.models.draft import DraftModel
from backend.persistence.models.thread import EmailThreadModel


logger = logging.getLogger(__name__)


class DraftRepository:
    """Repository for generated draft responses."""

    def __init__(self, session: Session, user_id: int) -> None:
        self.session = session
        self.user_id = user_id

    def save(self, external_thread_id: str, draft: DraftDocument) -> DraftDocument:
        thread = self.session.scalar(
            select(EmailThreadModel).where(
                EmailThreadModel.user_id == self.user_id,
                EmailThreadModel.external_thread_id == external_thread_id
            )
        )
        if thread is None:
            raise ValueError(f"Thread `{external_thread_id}` was not found.")

        model = DraftModel(
            thread=thread,
            subject=draft.subject,
            body=draft.body,
            provider_name=draft.provider_name,
            model_name=draft.model_name,
            used_fallback=draft.used_fallback,
            kb_sources_json=_serialize_sources(draft.kb_sources),
        )
        self.session.add(model)
        self.session.flush()
        return _model_to_domain(model)

    def latest_for_thread(self, external_thread_id: str) -> DraftDocument | None:
        query = (
            select(DraftModel)
            .join(EmailThreadModel, DraftModel.thread_id == EmailThreadModel.id)
            .where(
                EmailThreadModel.user_id == self.user_id,
                EmailThreadModel.external_thread_id == external_thread_id,
            )
            .order_by(DraftModel.created_at.desc())
        )
        model = self.session.scalar(query)
        if model is None:
            return None
        return _model_to_domain(model)


# ── (de)serialization helpers ──────────────────────────────────────────
def _serialize_sources(sources: list[KbDraftSource]) -> str:
    """Encode the source list as a JSON string for the Text column.

    Empty list → empty string so we don't waste bytes on `[]`.
    """
    if not sources:
        return ""
    return json.dumps([source.model_dump() for source in sources])


def _deserialize_sources(raw: str | None) -> list[KbDraftSource]:
    """Decode the JSON string back into KbDraftSource objects.

    Tolerant: if the column is empty, NULL, or somehow corrupted, we
    return [] rather than failing — sources are an audit trail enrichment,
    not load-bearing draft data.
    """
    if not raw or not raw.strip():
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Could not decode kb_sources_json — treating as empty.")
        return []
    if not isinstance(payload, list):
        return []
    sources: list[KbDraftSource] = []
    for item in payload:
        try:
            sources.append(KbDraftSource.model_validate(item))
        except Exception:
            # Skip individual malformed entries; keep the rest.
            continue
    return sources


def _model_to_domain(model: DraftModel) -> DraftDocument:
    return DraftDocument(
        subject=model.subject,
        body=model.body,
        provider_name=model.provider_name,
        model_name=model.model_name,
        used_fallback=model.used_fallback,
        created_at=model.created_at,
        kb_sources=_deserialize_sources(model.kb_sources_json),
    )
