"""Pydantic schemas for the Knowledge Base API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from backend.knowledge.domain.document import KbDocument, KbIngestionStatus


class KbDocumentResponse(BaseModel):
    """Public-facing document shape returned by list / upload endpoints.

    Mirrors `KbDocument` 1:1 — kept as a separate class so we can evolve
    the wire format independently of the domain model (e.g. add UI-only
    helper fields like a friendly status label) without touching backend
    code that depends on the domain shape.
    """

    id: int
    filename: str
    file_type: str
    size_bytes: int
    title: str
    product_name: str | None
    category: str | None
    description: str | None
    search_aliases: str = ""
    status: KbIngestionStatus
    progress_step: str | None = None
    error_message: str | None
    chunk_count: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, document: KbDocument) -> "KbDocumentResponse":
        return cls(**document.model_dump())


class KbDocumentListResponse(BaseModel):
    """Wrapper so we can add cursor / total fields later without breaking clients."""

    documents: list[KbDocumentResponse] = Field(default_factory=list)


class KbUploadResponse(BaseModel):
    """Returned immediately from POST /knowledge/documents.

    The document starts in PENDING/PROCESSING — the worker fills it in.
    Frontend polls GET /knowledge/documents/{id} until status flips to
    AWAITING_REVIEW (then opens the review modal) or FAILED (shows error).
    """

    document: KbDocumentResponse
    queued: bool = True


class KbFinalizeRequest(BaseModel):
    """User-confirmed metadata sent from the review modal.

    All fields are user-editable. Empty strings are passed through as the
    user explicitly clearing a field; null `product_name` / `category` /
    `description` mean "not set". The repository normalizes this layer.

    `search_aliases` is special: it's a comma-separated list of
    alternate terms / synonyms / customer-side names. Changing it
    triggers a re-embedding pass on the document's chunks.
    """

    title: str = Field(..., min_length=1, max_length=500)
    product_name: str | None = None
    category: str | None = None
    description: str | None = None
    search_aliases: str = ""


class KbChunkSummary(BaseModel):
    """One chunk as shown in the review modal's chunk explorer.

    No embedding vector — UI doesn't need it, and 1536 floats per chunk
    bloats the payload by orders of magnitude for a 200-chunk document.
    """

    id: int
    chunk_index: int
    content: str
    token_count: int


class KbChunkListResponse(BaseModel):
    document_id: int
    chunks: list[KbChunkSummary] = Field(default_factory=list)


class KbYouTubeIngestRequest(BaseModel):
    """Body for POST /knowledge/youtube — just the URL.

    yt-dlp resolves the title and duration server-side; the user
    doesn't pre-fill those.
    """

    url: str = Field(..., min_length=1, max_length=2000)


class KbChunkUpdateRequest(BaseModel):
    """Body for PATCH /knowledge/documents/{doc_id}/chunks/{chunk_id}.

    Single field intentionally — keeping the API narrow makes it
    impossible to accidentally update the embedding without also updating
    the text (which is what we always want). The backend recomputes
    `embedding` and `token_count` from `content`.
    """

    content: str = Field(..., min_length=1)


# ── Diagnostic shapes (used by GET /knowledge/diagnose) ─────────────────
class KbDiagnoseMatch(BaseModel):
    chunk_id: int
    chunk_index: int
    document_id: int
    document_title: str
    similarity: float
    preview: str


class KbDiagnoseResponse(BaseModel):
    """Full end-to-end RAG self-check report.

    Each field maps to one layer of the chain. If any layer fails, every
    layer below it is reported with its zero-value (False / 0 / []) and
    `verdict` summarises what's wrong in plain language.
    """

    kb_enabled: bool
    kb_session_open: bool
    documents_by_status: dict[str, int]
    documents_ready: int
    chunks_total: int
    query: str
    embedding_succeeded: bool
    embedding_dim: int
    threshold: float
    top_k: int
    unfiltered_matches: list[KbDiagnoseMatch]
    matches_above_threshold: list[KbDiagnoseMatch]
    verdict: str
