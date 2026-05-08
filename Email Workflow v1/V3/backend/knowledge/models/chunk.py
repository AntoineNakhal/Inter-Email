"""KB chunk model — one row per embedded text chunk.

The `embedding` column uses pgvector's `Vector(1536)` type, which matches
OpenAI `text-embedding-3-small`'s dimensionality. If you switch embedding
models you MUST:
  1. Drop the IVFFlat index and the `embedding` column.
  2. Re-create them with the new dimension.
  3. Re-ingest every document.

There's no migration shortcut — vector dim is a hard schema constraint.
"""

from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.knowledge.models.base import KbBase, KbTimestampMixin


# Dimension of OpenAI text-embedding-3-small. Hard-coded because the schema
# migration that creates this column also hard-codes 1536.
EMBEDDING_DIM = 1536


class KbChunkModel(KbBase, KbTimestampMixin):
    __tablename__ = "kb_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Cascade-delete on parent document removal so the corpus stays consistent
    # — orphan chunks would still match similarity queries and silently leak
    # context from deleted docs.
    document_id: Mapped[int] = mapped_column(
        ForeignKey("kb_documents.id", ondelete="CASCADE"),
        index=True,
    )

    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))

    document = relationship("KbDocumentModel")

    __table_args__ = (
        # IVFFlat index for approximate cosine similarity. Fast at retrieval
        # time at the cost of slightly fuzzy ranking — acceptable for RAG.
        # `lists=100` is a reasonable starting point for up to ~100k chunks;
        # tune up (sqrt(N)) once the corpus grows.
        Index(
            "ix_kb_chunks_embedding_cosine",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
