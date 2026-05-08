"""Common extractor interface."""

from __future__ import annotations

from abc import ABC, abstractmethod


class ExtractionError(RuntimeError):
    """Raised when text extraction fails (corrupt file, unsupported subtype, ...)."""


class BaseExtractor(ABC):
    """Stable interface every file-type extractor implements.

    Extractors take raw bytes and return a single concatenated text blob.
    They MUST NOT do chunking, embedding, or any AI work — that lives one
    layer up in the ingestion service.
    """

    file_type: str  # canonical identifier ("pdf", "pptx", ...)

    @abstractmethod
    def extract(self, content: bytes, *, filename: str = "") -> str:
        """Return cleaned text from the given file bytes."""
        raise NotImplementedError
