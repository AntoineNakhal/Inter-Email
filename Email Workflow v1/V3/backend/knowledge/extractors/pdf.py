"""PDF text extraction via pdfplumber.

pdfplumber is preferred over PyPDF2/pypdf because it preserves layout-derived
word ordering, which matters for technical specs that lay out tables in
columns. Tradeoff: ~2x slower per page.
"""

from __future__ import annotations

import io

from backend.knowledge.extractors.base import BaseExtractor, ExtractionError


class PdfExtractor(BaseExtractor):
    file_type = "pdf"

    def extract(self, content: bytes, *, filename: str = "") -> str:
        try:
            import pdfplumber
        except ImportError as exc:
            raise ExtractionError(
                "pdfplumber is not installed — run `pip install pdfplumber`."
            ) from exc

        try:
            pages: list[str] = []
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text() or ""
                    if page_text.strip():
                        pages.append(page_text)
        except Exception as exc:
            raise ExtractionError(
                f"Failed to extract text from PDF '{filename}': {exc}"
            ) from exc

        return "\n\n".join(pages).strip()
