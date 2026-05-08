"""Plain-text and Markdown extractor.

Markdown is intentionally NOT stripped — heading markers (##), bullet
points (-, *), and inline code formatting carry semantic weight that
embedding models pick up. We only normalize newlines.
"""

from __future__ import annotations

from backend.knowledge.extractors.base import BaseExtractor, ExtractionError


class PlainTextExtractor(BaseExtractor):
    """Used for both `.txt` and `.md` — same code path."""

    file_type = "text"  # logical type; registry maps both extensions here

    def extract(self, content: bytes, *, filename: str = "") -> str:
        try:
            # utf-8 first; fall back to latin-1 so a stray Windows export
            # doesn't crash the upload. We never want to reject a doc
            # silently, so any decode failure becomes an ExtractionError.
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = content.decode("latin-1")
            except Exception as exc:
                raise ExtractionError(
                    f"Failed to decode text file '{filename}': {exc}"
                ) from exc
        # Normalize line endings; collapsing whitespace would destroy
        # markdown structure, so leave the rest alone.
        return text.replace("\r\n", "\n").replace("\r", "\n").strip()
