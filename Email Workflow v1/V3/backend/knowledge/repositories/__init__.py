"""Persistence repositories for the Knowledge Base.

Repositories own the SQLAlchemy → domain conversion. Services NEVER touch
ORM models directly — they get back Pydantic objects and operate on those.
"""

from backend.knowledge.repositories.chunk_repository import KbChunkRepository
from backend.knowledge.repositories.document_repository import KbDocumentRepository

__all__ = ["KbChunkRepository", "KbDocumentRepository"]
