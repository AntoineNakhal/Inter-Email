"""Repository for `kb_documents`."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.knowledge.domain.document import (
    KbDocument,
    KbDocumentMetadata,
    KbIngestionStatus,
)
from backend.knowledge.models.document import KbDocumentModel


class KbDocumentRepository:
    """CRUD + status transitions for KB document rows."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ── writes ────────────────────────────────────────────────────────────
    def create_pending(
        self,
        *,
        filename: str,
        file_type: str,
        size_bytes: int,
        title: str = "",
    ) -> KbDocument:
        """Insert a row in PENDING state; the worker flips it later."""
        model = KbDocumentModel(
            filename=filename,
            file_type=file_type,
            size_bytes=size_bytes,
            title=title or filename,
            status=KbIngestionStatus.PENDING,
        )
        self.session.add(model)
        self.session.flush()
        return self._to_domain(model)

    def mark_processing(self, document_id: int) -> None:
        model = self._get_model_or_fail(document_id)
        model.status = KbIngestionStatus.PROCESSING
        model.error_message = None
        self.session.flush()

    def mark_awaiting_review(
        self,
        document_id: int,
        *,
        chunk_count: int,
        metadata: KbDocumentMetadata | None = None,
    ) -> KbDocument:
        """Worker is done — park the doc in AWAITING_REVIEW.

        At this point chunks are stored but invisible to RAG (the retrieval
        repo filters on status='ready'). The user must call finalize() via
        the review modal to make the doc searchable.
        """
        model = self._get_model_or_fail(document_id)
        model.status = KbIngestionStatus.AWAITING_REVIEW
        model.chunk_count = chunk_count
        model.error_message = None
        if metadata is not None:
            # Only overwrite when Haiku gave us a non-empty value — preserve
            # the filename-derived title if metadata extraction returns "".
            if metadata.title:
                model.title = metadata.title
            if metadata.product_name is not None:
                model.product_name = metadata.product_name
            if metadata.category is not None:
                model.category = metadata.category
            if metadata.description is not None:
                model.description = metadata.description
        self.session.flush()
        return self._to_domain(model)

    def finalize(
        self,
        document_id: int,
        *,
        metadata: KbDocumentMetadata,
    ) -> KbDocument:
        """User-approved: write the user's edits and flip to READY.

        This is the only path that makes a document visible to RAG. We
        always overwrite the four metadata fields with the values the user
        confirmed in the modal — `null` from the modal becomes NULL in DB,
        empty string becomes "" (the user explicitly cleared the field).

        Idempotent: re-finalizing an already-READY doc just rewrites the
        metadata, which is fine.
        """
        model = self._get_model_or_fail(document_id)
        model.status = KbIngestionStatus.READY
        model.title = metadata.title or model.filename
        model.product_name = metadata.product_name
        model.category = metadata.category
        model.description = metadata.description
        self.session.flush()
        return self._to_domain(model)

    def mark_failed(self, document_id: int, error_message: str) -> KbDocument:
        model = self._get_model_or_fail(document_id)
        model.status = KbIngestionStatus.FAILED
        # Truncate so a runaway traceback can't blow out the row.
        model.error_message = (error_message or "")[:4000]
        self.session.flush()
        return self._to_domain(model)

    def adjust_chunk_count(self, document_id: int, delta: int) -> None:
        """Bump or shrink chunk_count by `delta`. Used after per-chunk
        edits delete one. Floors at 0 — we never allow negative counts."""
        model = self._get_model_or_fail(document_id)
        model.chunk_count = max(0, model.chunk_count + delta)
        self.session.flush()

    def delete(self, document_id: int) -> bool:
        model = self.session.get(KbDocumentModel, document_id)
        if model is None:
            return False
        # Chunks cascade-delete via FK ondelete=CASCADE.
        self.session.delete(model)
        self.session.flush()
        return True

    # ── reads ─────────────────────────────────────────────────────────────
    def get(self, document_id: int) -> KbDocument | None:
        model = self.session.get(KbDocumentModel, document_id)
        return self._to_domain(model) if model else None

    def list_all(self) -> list[KbDocument]:
        rows = self.session.scalars(
            select(KbDocumentModel).order_by(KbDocumentModel.created_at.desc())
        ).all()
        return [self._to_domain(row) for row in rows]

    # ── helpers ───────────────────────────────────────────────────────────
    def _get_model_or_fail(self, document_id: int) -> KbDocumentModel:
        model = self.session.get(KbDocumentModel, document_id)
        if model is None:
            raise ValueError(f"KB document `{document_id}` was not found.")
        return model

    @staticmethod
    def _to_domain(model: KbDocumentModel) -> KbDocument:
        return KbDocument(
            id=model.id,
            filename=model.filename,
            file_type=model.file_type,
            size_bytes=model.size_bytes,
            title=model.title,
            product_name=model.product_name,
            category=model.category,
            description=model.description,
            status=model.status,
            error_message=model.error_message,
            chunk_count=model.chunk_count,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
