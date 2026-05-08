"""KB document model — one row per uploaded source file."""

from __future__ import annotations

import enum

from sqlalchemy import Enum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.knowledge.models.base import KbBase, KbTimestampMixin


class KbIngestionStatus(str, enum.Enum):
    """Lifecycle of an uploaded document.

    Flow:
      pending  → row created, bytes staged, worker hasn't started
      processing → worker extracting / chunking / embedding / metadata
      awaiting_review → worker done; user must approve in the review modal
      ready    → user-approved; visible to RAG retrieval
      failed   → ingestion error; row kept so user can read the message

    NOTE: only `ready` documents participate in RAG searches. Chunks for
    a doc in `awaiting_review` are stored but invisible to retrieval — so
    nothing leaks into AI prompts before the user has signed off.
    """

    PENDING = "pending"
    PROCESSING = "processing"
    AWAITING_REVIEW = "awaiting_review"
    READY = "ready"
    FAILED = "failed"


class KbDocumentModel(KbBase, KbTimestampMixin):
    """One uploaded knowledge-base document.

    Schema notes:
      * `chunk_count` is denormalized so the list endpoint is one query, not
        one+N. Updated by the ingestion service after embedding.
      * AI-extracted metadata (`product_name`, `category`, `description`)
        starts NULL and is filled in by `MetadataExtractionService`. NULL
        means "metadata extraction hasn't run yet" — distinct from "ran but
        the model returned an empty value".
      * No user_id FK — KB is global to the deployment (one corpus shared
        across all users). If we ever want per-user KBs, this is where the
        scoping column goes.
    """

    __tablename__ = "kb_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Original filename + MIME-ish type. Use `file_type` to dispatch the
    # extractor; `filename` is kept verbatim for the UI.
    filename: Mapped[str] = mapped_column(String(500))
    file_type: Mapped[str] = mapped_column(String(32))  # pdf, pptx, xlsx, txt, md
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)

    # Human / AI metadata. `title` defaults to filename until Haiku rewrites it.
    title: Mapped[str] = mapped_column(String(500), default="")
    product_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Pipeline state.
    status: Mapped[KbIngestionStatus] = mapped_column(
        Enum(KbIngestionStatus, name="kb_ingestion_status"),
        default=KbIngestionStatus.PENDING,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
