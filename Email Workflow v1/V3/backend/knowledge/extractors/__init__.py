"""Text extractors — pluggable, one per file type.

To add support for a new format:
  1. Create `backend/knowledge/extractors/<format>.py` implementing `BaseExtractor`.
  2. Register it in `registry.py`'s `EXTRACTORS` dict.
That's it — no other file knows about the new format.
"""

from backend.knowledge.extractors.base import BaseExtractor, ExtractionError
from backend.knowledge.extractors.registry import (
    SUPPORTED_FILE_TYPES,
    extract_text,
    file_type_for_filename,
)

__all__ = [
    "BaseExtractor",
    "ExtractionError",
    "SUPPORTED_FILE_TYPES",
    "extract_text",
    "file_type_for_filename",
]
