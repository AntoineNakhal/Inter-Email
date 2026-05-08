"""Token-aware text chunker (~400 tokens per chunk, 50-token overlap).

Why token-aware? Embedding budgets are measured in tokens, not characters.
A char/4 approximation produces wildly inconsistent chunk sizes for any
text that isn't pure English (code blocks, tables, JSON snippets). tiktoken
gives us byte-exact counts using the same BPE OpenAI uses.

Why overlap? Without it, an idea split mid-sentence gets two embeddings
that each capture only half the meaning. 50 tokens of overlap means the
last paragraph of chunk N is also the first paragraph of chunk N+1, so
either chunk is retrievable by the same query.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass


logger = logging.getLogger(__name__)


# Defaults from the project spec — tuned for OpenAI text-embedding-3-small,
# whose context window is 8191 tokens. 400 leaves plenty of headroom and
# fits a few chunks comfortably in a model context window for retrieval.
DEFAULT_CHUNK_TOKENS = 400
DEFAULT_OVERLAP_TOKENS = 50


@dataclass(frozen=True)
class TextChunk:
    """One produced chunk."""

    index: int
    content: str
    token_count: int


class TokenChunker:
    """Splits text into overlapping ~N-token windows."""

    def __init__(
        self,
        *,
        chunk_tokens: int = DEFAULT_CHUNK_TOKENS,
        overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
        encoding_name: str = "cl100k_base",
    ) -> None:
        if overlap_tokens >= chunk_tokens:
            raise ValueError("overlap_tokens must be smaller than chunk_tokens.")
        self.chunk_tokens = chunk_tokens
        self.overlap_tokens = overlap_tokens
        self.encoding_name = encoding_name
        self._encoding = None  # lazy — only paid for if chunker is actually used

    def _encoder(self):
        """Lazy load the tiktoken encoder.

        cl100k_base is what text-embedding-3-small uses. We pin the encoding
        rather than `encoding_for_model("text-embedding-3-small")` so the
        chunker doesn't break the day OpenAI removes a model alias.
        """
        if self._encoding is None:
            try:
                import tiktoken
            except ImportError as exc:
                raise RuntimeError(
                    "tiktoken is not installed — run `pip install tiktoken`."
                ) from exc
            self._encoding = tiktoken.get_encoding(self.encoding_name)
        return self._encoding

    def chunk(self, text: str) -> list[TextChunk]:
        """Split text into TextChunks. Returns [] for empty/whitespace-only input."""
        cleaned = (text or "").strip()
        if not cleaned:
            return []

        encoder = self._encoder()
        token_ids = encoder.encode(cleaned)
        total_tokens = len(token_ids)

        # Tiny doc: one chunk, skip the windowing math entirely.
        if total_tokens <= self.chunk_tokens:
            return [TextChunk(index=0, content=cleaned, token_count=total_tokens)]

        chunks: list[TextChunk] = []
        step = self.chunk_tokens - self.overlap_tokens
        start = 0
        chunk_index = 0
        while start < total_tokens:
            end = min(start + self.chunk_tokens, total_tokens)
            window = token_ids[start:end]
            content = encoder.decode(window)
            # Decoded windows can have leading/trailing whitespace that
            # contributes nothing to the embedding — strip it.
            content = content.strip()
            if content:
                chunks.append(
                    TextChunk(
                        index=chunk_index,
                        content=content,
                        token_count=len(window),
                    )
                )
                chunk_index += 1
            if end >= total_tokens:
                break
            start += step

        logger.debug(
            "Chunked text: %s tokens → %s chunks (size=%s, overlap=%s)",
            total_tokens,
            len(chunks),
            self.chunk_tokens,
            self.overlap_tokens,
        )
        return chunks
