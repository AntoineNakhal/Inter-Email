"""OpenAI embeddings wrapper.

One job: turn N strings into N vectors. Batches up to OpenAI's limit per
request, applies a wall-clock timeout, and surfaces failures as
`EmbeddingError`. There is NO heuristic fallback — if embeddings can't be
computed, ingestion or retrieval must fail loudly so the user notices.
"""

from __future__ import annotations

import logging
import time
from typing import Sequence

from backend.core.config import AppSettings


logger = logging.getLogger(__name__)


# OpenAI's batch ceiling for embeddings is 2048 inputs per request, but in
# practice we keep it lower so a single request stays well under any token
# budget and finishes within the timeout.
_EMBEDDING_BATCH_SIZE = 100

# Hard wall-clock timeout per request. Embedding latency is usually <2s for
# a 100-input batch; 30s is generous and still bounded.
_EMBEDDING_TIMEOUT_SECONDS = 30


class EmbeddingError(RuntimeError):
    """Raised when an embedding API call fails."""


class EmbeddingService:
    """Thin wrapper around OpenAI's embeddings endpoint."""

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    @property
    def model(self) -> str:
        return self.settings.kb_embedding_model

    def embed_one(self, text: str) -> list[float]:
        """Embed a single string. Uses embed_many internally."""
        results = self.embed_many([text])
        if not results:
            raise EmbeddingError("Embedding API returned no vector for input.")
        return results[0]

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed many strings, batching transparently.

        Order of returned vectors matches the input order.
        """
        if not texts:
            return []
        if not self.settings.openai_api_key.strip():
            raise EmbeddingError(
                "OPENAI_API_KEY is missing — cannot compute embeddings."
            )

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise EmbeddingError(
                "openai package is not installed — run `pip install openai`."
            ) from exc

        client = OpenAI(
            api_key=self.settings.openai_api_key,
            timeout=_EMBEDDING_TIMEOUT_SECONDS,
        )
        all_vectors: list[list[float]] = []
        total = len(texts)
        started = time.perf_counter()
        for batch_start in range(0, total, _EMBEDDING_BATCH_SIZE):
            batch = list(texts[batch_start : batch_start + _EMBEDDING_BATCH_SIZE])
            try:
                response = client.embeddings.create(
                    model=self.model,
                    input=batch,
                )
            except Exception as exc:  # network, auth, rate-limit, etc.
                raise EmbeddingError(
                    f"OpenAI embeddings request failed (batch starting at "
                    f"index {batch_start}): {exc}"
                ) from exc

            # Defensive — assert the API gave us one vector per input.
            if len(response.data) != len(batch):
                raise EmbeddingError(
                    f"OpenAI embeddings returned {len(response.data)} vectors "
                    f"for {len(batch)} inputs."
                )
            all_vectors.extend(item.embedding for item in response.data)

        logger.info(
            "Embedded %s chunks via %s in %.2fs",
            total,
            self.model,
            time.perf_counter() - started,
        )
        return all_vectors
