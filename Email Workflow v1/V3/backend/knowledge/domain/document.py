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
    status: KbIngestionStatus
    error_message: str | None = None
    chunk_count: int = 0
    created_at: datetime
    updated_at: datetime
