"""Extractor registry — dispatch by file type.

The single point where the system enumerates supported file types. The API
router uses `SUPPORTED_FILE_TYPES` for upload validation and the ingestion
service uses `extract_text(...)` for dispatch.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from backend.knowledge.extractors.base import BaseExtractor, ExtractionError
from backend.knowledge.extractors.pdf import PdfExtractor
from backend.knowledge.extractors.pptx import PptxExtractor
from backend.knowledge.extractors.text import PlainTextExtractor
from backend.knowledge.extractors.xlsx import XlsxExtractor


# Maps the canonical file_type → extractor instance. We instantiate once
# (extractors are stateless) so the import-time cost is paid up front.
EXTRACTORS: dict[str, BaseExtractor] = {
    "pdf": PdfExtractor(),
    "pptx": PptxExtractor(),
    "xlsx": XlsxExtractor(),
    "txt": PlainTextExtractor(),
    "md": PlainTextExtractor(),
}

# Used by the upload router for client-friendly error messages.
SUPPORTED_FILE_TYPES: tuple[str, ...] = tuple(EXTRACTORS.keys())


def file_type_for_filename(filename: str) -> str | None:
    """Resolve a canonical file_type from the filename's extension.

    Returns None for unsupported extensions so the caller can produce a
    clean 400 error instead of crashing inside an extractor.
    """
    suffix = PurePosixPath(filename).suffix.lower().lstrip(".")
    return suffix if suffix in EXTRACTORS else None


def extract_text(content: bytes, *, file_type: str, filename: str = "") -> str:
    """Dispatch to the right extractor.

    Raises ExtractionError if the file_type is unsupported or extraction fails.
    """
    extractor = EXTRACTORS.get(file_type)
    if extractor is None:
        raise ExtractionError(f"Unsupported file_type: {file_type!r}")
    return extractor.extract(content, filename=filename)
