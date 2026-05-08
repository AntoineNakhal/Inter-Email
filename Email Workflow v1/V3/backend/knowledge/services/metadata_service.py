"""Claude Haiku metadata extraction.

After ingestion completes, we make ONE Haiku call against the first ~2000
characters of the document to recover:
  * a clean human-readable title
  * the product the doc is about (best guess)
  * a category (e.g. "datasheet", "user manual", "spec sheet")
  * a one-paragraph description

These power the Knowledge Base list UI and feed the RAG retrieval block
so the AI knows WHICH product a chunk belongs to.

Failure mode: surface the error. We do NOT silently fall back to filename
heuristics — a doc without metadata is fine (`product_name` stays NULL),
but a corrupt metadata response should not be smuggled through.
"""

from __future__ import annotations

import json
import logging

from backend.core.config import AppSettings
from backend.knowledge.domain.document import KbDocumentMetadata


logger = logging.getLogger(__name__)


# Hard cap on the input to Haiku — beyond ~2000 chars we don't get better
# metadata, just spend more tokens.
_METADATA_INPUT_CHAR_LIMIT = 2000

# Output budget — small JSON object.
_METADATA_MAX_TOKENS = 512

_SYSTEM_PROMPT = (
    "You are a metadata extractor for a technical product knowledge base. "
    "Read the supplied document excerpt and return STRICT JSON with these keys: "
    "title (string), product_name (string or null), category (string or null), "
    "description (string or null, max 2 sentences). "
    "Rules: "
    "1) `title` must be a clean human-friendly title — never a filename or path. "
    "2) `product_name` is the specific product/SKU/model the doc is about. "
    "If the doc covers many products, return null. "
    "3) `category` is short (one to four words). Examples: \"datasheet\", "
    "\"installation guide\", \"user manual\", \"spec sheet\". "
    "4) `description` is one or two sentences plainly summarizing what the "
    "doc covers. "
    "Return ONLY the JSON object with these four keys, no preamble."
)


class MetadataExtractionError(RuntimeError):
    """Raised when Haiku metadata extraction fails."""


class MetadataExtractionService:
    """Calls Claude Haiku once per document to fill metadata fields."""

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def extract(self, *, filename: str, full_text: str) -> KbDocumentMetadata:
        if not self.settings.anthropic_api_key.strip():
            raise MetadataExtractionError(
                "ANTHROPIC_API_KEY is missing — cannot extract document metadata."
            )

        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise MetadataExtractionError(
                "anthropic package is not installed — run `pip install anthropic`."
            ) from exc

        excerpt = (full_text or "")[:_METADATA_INPUT_CHAR_LIMIT].strip()
        if not excerpt:
            raise MetadataExtractionError(
                "Document is empty — nothing to extract metadata from."
            )

        try:
            client = Anthropic(api_key=self.settings.anthropic_api_key)
            response = client.messages.create(
                model=self.settings.anthropic_model_thread_analysis,  # Haiku
                max_tokens=_METADATA_MAX_TOKENS,
                temperature=0.0,
                system=_SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Filename: {filename}\n\n"
                            f"Document excerpt:\n{excerpt}"
                        ),
                    },
                ],
            )
        except Exception as exc:
            raise MetadataExtractionError(
                f"Anthropic metadata request failed: {exc}"
            ) from exc

        text = self._extract_text(response)
        try:
            payload = self._parse_json(text)
        except ValueError as exc:
            raise MetadataExtractionError(
                f"Anthropic returned invalid JSON metadata: {exc}"
            ) from exc

        return KbDocumentMetadata(
            title=str(payload.get("title") or "").strip() or filename,
            product_name=_clean_str(payload.get("product_name")),
            category=_clean_str(payload.get("category")),
            description=_clean_str(payload.get("description")),
        )

    @staticmethod
    def _extract_text(response: object) -> str:
        """Pull text from an Anthropic Messages response (mirrors AnthropicProvider)."""
        try:
            blocks = getattr(response, "content", None) or []
            parts: list[str] = []
            for block in blocks:
                text = getattr(block, "text", None)
                if text is None and isinstance(block, dict):
                    text = block.get("text")
                if text:
                    parts.append(str(text))
            return "".join(parts).strip()
        except Exception:
            return str(response)

    @staticmethod
    def _parse_json(text: str) -> dict[str, object]:
        """Parse JSON tolerant of leading/trailing prose around the object."""
        if not text:
            raise ValueError("empty response")
        # Trim to the first { ... } window — Haiku occasionally adds prose
        # despite the system prompt, and we'd rather recover than fail.
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise ValueError("no JSON object detected in response")
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(str(exc)) from exc
        if not isinstance(parsed, dict):
            raise ValueError("top-level JSON value is not an object")
        return parsed


def _clean_str(value: object) -> str | None:
    """Return a stripped string or None for null/empty/non-string inputs."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    cleaned = value.strip()
    return cleaned or None
