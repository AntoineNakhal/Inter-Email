"""Pydantic domain models for KB documents.

These are what the application/router layers pass around. The SQLAlchemy
models in `backend.knowledge.models.*` are kept private to the persistence
layer — repositories convert between the two.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

# Re-export the enum from the model layer to keep callers from having to
# reach into persistence to type their function signatures.
from backend.knowledge.models.document import KbIngestionStatus

__all__ = ["KbDocument", "KbDocumentMetadata", "KbIngestionStatus"]


class KbDocumentMetadata(BaseModel):
    """AI-extracted descriptors. All fields optional — Haiku may decline a
    field when the document doesn't support it (e.g. a generic spec sheet
    has no clear product name)."""

    title: str = ""
    product_name: str | None = None
    category: str | None = None
    description: str | None = None
    # User-provided. Free-form comma-separated terms that get baked into
    # the chunks' embedding inputs so the doc is retrievable by alternate
    # / customer-side names. Defaults to "" so legacy domain calls keep
    # working unchanged.
    search_aliases: str = ""


class KbDocument(BaseModel):
    """One uploaded knowledge-base document."""

    id: int
    filename: str
    file_type: str
    size_bytes: int
    title: str = ""
    product_name: str | None = None
    category: str | None = None
    description: str | None = None
    search_aliases: str = ""
    source_url: str | None = None
    status: KbIngestionStatus
    # Current ingestion stage. Only set while status=processing; None otherwise.
    progress_step: str | None = None
    error_message: str | None = None
    chunk_count: int = 0
    created_at: datetime
    updated_at: datetime
