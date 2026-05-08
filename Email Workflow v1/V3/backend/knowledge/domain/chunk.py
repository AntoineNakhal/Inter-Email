"""Pydantic domain models for KB chunks + retrieval results."""

from __future__ import annotations

from pydantic import BaseModel, Field


class KbChunk(BaseModel):
    """A single embedded text chunk."""

    id: int
    document_id: int
    chunk_index: int
    content: str
    token_count: int = 0


class KbChunkMatch(BaseModel):
    """A retrieval hit — chunk + its metric.

    `similarity` is cosine similarity in [0, 1]: 1.0 = identical direction,
    0.0 = orthogonal. We surface it (not raw distance) so callers can apply
    a threshold without translating between metrics.
    """

    chunk: KbChunk
    similarity: float
    document_title: str = ""
    document_product_name: str | None = None
