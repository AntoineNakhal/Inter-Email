"""Repository for `kb_chunks` — bulk insert + similarity search."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.knowledge.domain.chunk import KbChunk, KbChunkMatch
from backend.knowledge.models.chunk import KbChunkModel
from backend.knowledge.models.document import KbDocumentModel


class KbChunkRepository:
    """Repository for embedded text chunks.

    Two hot operations:
      * bulk_insert during ingestion (one document = many chunks)
      * search_similar during retrieval (cosine, top-K, threshold)
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def bulk_insert(
        self,
        *,
        document_id: int,
        chunks: list[tuple[int, str, int, list[float]]],
    ) -> int:
        """Insert many chunks at once.

        chunks: list of (chunk_index, content, token_count, embedding).
        Returns the number of rows written.
        """
        if not chunks:
            return 0
        models = [
            KbChunkModel(
                document_id=document_id,
                chunk_index=index,
                content=content,
                token_count=token_count,
                embedding=embedding,
            )
            for index, content, token_count, embedding in chunks
        ]
        self.session.add_all(models)
        self.session.flush()
        return len(models)

    def get(self, chunk_id: int) -> KbChunkModel | None:
        """Return the raw model — service layer needs the doc_id off it
        to validate the chunk belongs to the right document."""
        return self.session.get(KbChunkModel, chunk_id)

    def update_content(
        self,
        chunk_id: int,
        *,
        content: str,
        token_count: int,
        embedding: list[float],
    ) -> KbChunk:
        """Rewrite a chunk's text + matching embedding in one go.

        Invariant: content and embedding always change together. There is
        no path that updates content without also re-embedding — that
        would silently break retrieval since the vector would no longer
        represent the text.
        """
        model = self.session.get(KbChunkModel, chunk_id)
        if model is None:
            raise ValueError(f"KB chunk `{chunk_id}` was not found.")
        model.content = content
        model.token_count = token_count
        model.embedding = embedding
        self.session.flush()
        return KbChunk(
            id=model.id,
            document_id=model.document_id,
            chunk_index=model.chunk_index,
            content=model.content,
            token_count=model.token_count,
        )

    def delete(self, chunk_id: int) -> bool:
        model = self.session.get(KbChunkModel, chunk_id)
        if model is None:
            return False
        self.session.delete(model)
        self.session.flush()
        return True

    def list_for_document(self, document_id: int) -> list[KbChunk]:
        """Return every chunk for a document, ordered by chunk_index.

        Used by the review modal so the user can audit what the extractor +
        chunker actually produced before approving the doc. Excludes the
        embedding vector — the UI doesn't need 1536 floats per chunk.
        """
        rows = self.session.scalars(
            select(KbChunkModel)
            .where(KbChunkModel.document_id == document_id)
            .order_by(KbChunkModel.chunk_index.asc())
        ).all()
        return [
            KbChunk(
                id=row.id,
                document_id=row.document_id,
                chunk_index=row.chunk_index,
                content=row.content,
                token_count=row.token_count,
            )
            for row in rows
        ]

    def delete_for_document(self, document_id: int) -> int:
        """Wipe chunks for a document (used before re-ingestion).

        Returns the rowcount. The cascade on `kb_documents` already covers
        document deletion, so this is for re-ingestion-in-place only.
        """
        result = self.session.execute(
            delete(KbChunkModel).where(KbChunkModel.document_id == document_id)
        )
        self.session.flush()
        return result.rowcount or 0

    def search_similar(
        self,
        *,
        query_embedding: list[float],
        top_k: int,
        similarity_threshold: float,
        document_status_filter: str | None = "ready",
    ) -> list[KbChunkMatch]:
        """Top-K cosine similarity search against the corpus.

        Notes:
          * pgvector's `<=>` operator returns COSINE DISTANCE in [0, 2].
            similarity = 1 - distance, so similarity ∈ [-1, 1] in theory,
            and ∈ [0, 1] for non-negative embedding spaces (which OpenAI's are).
          * We filter on document.status='ready' so chunks belonging to a
            document still being ingested or one that failed don't leak in.
        """
        if top_k <= 0:
            return []

        distance = KbChunkModel.embedding.cosine_distance(query_embedding)
        stmt = (
            select(
                KbChunkModel,
                KbDocumentModel,
                distance.label("distance"),
            )
            .join(KbDocumentModel, KbChunkModel.document_id == KbDocumentModel.id)
            .order_by(distance)
            .limit(top_k)
        )
        if document_status_filter:
            stmt = stmt.where(KbDocumentModel.status == document_status_filter)

        results = self.session.execute(stmt).all()

        matches: list[KbChunkMatch] = []
        for chunk_model, doc_model, raw_distance in results:
            similarity = 1.0 - float(raw_distance)
            if similarity < similarity_threshold:
                # Results are ordered by distance ASC, so the first chunk
                # below threshold means everything after is too. Bail early.
                break
            matches.append(
                KbChunkMatch(
                    chunk=KbChunk(
                        id=chunk_model.id,
                        document_id=chunk_model.document_id,
                        chunk_index=chunk_model.chunk_index,
                        content=chunk_model.content,
                        token_count=chunk_model.token_count,
                    ),
                    similarity=similarity,
                    document_title=doc_model.title or doc_model.filename,
                    document_product_name=doc_model.product_name,
                )
            )
        return matches
