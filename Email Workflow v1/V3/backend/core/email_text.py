"""Utilities for cleaning noisy email text before analysis or display."""

from __future__ import annotations

import re
from html.parser import HTMLParser


# Tags whose entire subtree (including text content) should be ignored.
_SKIP_TAGS = frozenset({"script", "style", "head"})
# Tags that should produce a line break in the extracted text.
_BLOCK_TAGS = frozenset({"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6"})


class _HtmlTextExtractor(HTMLParser):
    """Minimal HTML → plain-text extractor using the stdlib parser."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def handle_entityref(self, name: str) -> None:
        import html as _html
        if self._skip_depth == 0:
            self._parts.append(_html.unescape(f"&{name};"))

    def handle_charref(self, name: str) -> None:
        import html as _html
        if self._skip_depth == 0:
            self._parts.append(_html.unescape(f"&#{name};"))

    def get_text(self) -> str:
        raw = "".join(self._parts)
        raw = re.sub(r"[^\S\n]+", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def extract_text_from_html(html: str) -> str:
    """Strip HTML tags and return readable plain text.

    Uses Python's built-in html.parser — no extra dependency.
    Skips <script>, <style>, and <head> subtrees entirely.
    """
    extractor = _HtmlTextExtractor()
    try:
        extractor.feed(html)
    except Exception:
        # Malformed HTML — fall back to a simple tag-strip regex.
        return re.sub(r"<[^>]+>", " ", html).strip()
    return extractor.get_text()


def is_html_body(text: str) -> bool:
    """Return True when the body is an HTML document rather than plain text."""
    trimmed = text.lstrip().lower()
    return (
        trimmed.startswith("<!doctype")
        or trimmed.startswith("<html")
        or ("<table" in trimmed and "</table>" in trimmed)
    )


INLINE_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\r\n?"), "\n"),
    (re.compile("\u00a0"), " "),
    (re.compile(r"[\u200b-\u200d\u2060\ufeff]"), ""),
    (re.compile("\u00c2"), ""),
    (re.compile("\ufffd"), ""),
)

FOOTER_MARKERS = (
    "the content of this message",
    "this message and any attachments",
    "this e-mail and any attachments",
    "if you received this message by mistake",
    "if you are not the intended recipient",
    "please reply to this message and delete the email",
    "ce message et toute piece jointe",
    "ce courriel et toute piece jointe",
    "si vous avez recu ce message par erreur",
)

QUOTED_HISTORY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^on .+wrote:$", re.IGNORECASE),
    re.compile(r"^le .+a ecrit.*:$", re.IGNORECASE),
    re.compile(r"^from:\s", re.IGNORECASE),
    re.compile(r"^de:\s", re.IGNORECASE),
    re.compile(r"^sent:\s", re.IGNORECASE),
    re.compile(r"^envoye:\s", re.IGNORECASE),
    re.compile(r"^to:\s", re.IGNORECASE),
    re.compile(r"^a:\s", re.IGNORECASE),
    re.compile(r"^subject:\s", re.IGNORECASE),
    re.compile(r"^objet:\s", re.IGNORECASE),
    re.compile(r"^-+\s*original message\s*-+$", re.IGNORECASE),
)

# Matches the Gmail "---------- Forwarded message ---------" separator.
# When this line is present the content that follows IS the email — it must
# never be treated as quoted history and stripped.
FORWARDED_SEPARATOR_RE = re.compile(
    r"^-{3,}\s*forwarded message\s*-{3,}$",
    re.IGNORECASE,
)

SIGNATURE_SIGNOFF_RE = re.compile(
    r"^(?:best|best regards|kind regards|regards|warm regards|thanks|thank you|cheers|sincerely|cordially)[,!.\s]*$",
    re.IGNORECASE,
)
EMAIL_RE = re.compile(r"\b[^@\s]+@[^@\s]+\.[^@\s]+\b")
PHONE_RE = re.compile(r"(?:\+?\d[\d\s().-]{6,}\d)")
WEBSITE_RE = re.compile(r"(?:https?://|www\.)", re.IGNORECASE)
NAME_LIKE_RE = re.compile(
    r"^[A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){1,3}$"
)
SIGNATURE_KEYWORDS = (
    "manager",
    "director",
    "coordinator",
    "specialist",
    "analyst",
    "recruiter",
    "sales",
    "marketing",
    "operations",
    "inter-op",
    "inter op",
    "inter-mission",
    "linkedin",
)
TITLE_PHRASES = (
    "inside sales manager",
    "sales manager",
    "account manager",
    "operations manager",
    "project manager",
    "business development",
)


def normalize_email_text(value: str | None) -> str:
    """Normalize whitespace and common mojibake artifacts."""

    normalized = str(value or "")
    for pattern, replacement in INLINE_REPLACEMENTS:
        normalized = pattern.sub(replacement, normalized)
    normalized = re.sub(r"[^\S\n]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def clean_email_snippet(value: str | None) -> str:
    return clean_email_body(value)


def clean_email_body(value: str | None, is_forwarded: bool = False) -> str:
    """Drop reply history, legal footers, and common signature blocks.

    When ``is_forwarded`` is True the quoted-history stripping step is skipped
    because the forwarded headers (From:, Subject:, etc.) ARE the content the
    user wants to read — not noise to discard.
    """
    normalized = normalize_email_text(value)
    if not normalized:
        return ""

    normalized = _truncate_inline_footer(normalized)
    lines = normalized.split("\n")
    trimmed = lines if is_forwarded else _strip_quoted_history(lines)
    trimmed = _strip_footer(trimmed)
    trimmed = _strip_signature(trimmed)
    cleaned = "\n".join(trimmed)
    cleaned = _truncate_inline_signature(cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _strip_quoted_history(lines: list[str]) -> list[str]:
    kept: list[str] = []
    for index, raw_line in enumerate(lines):
        line = raw_line.rstrip()
        lowered = line.strip().lower()
        has_visible_content = any(item.strip() for item in kept)
        # A forwarded-message separator means everything from here on IS the
        # main content — keep the separator and all remaining lines as-is.
        if FORWARDED_SEPARATOR_RE.match(lowered):
            kept.extend(raw_line.rstrip() for raw_line in lines[index:])
            break
        if has_visible_content and any(
            pattern.match(lowered) for pattern in QUOTED_HISTORY_PATTERNS
        ):
            break
        kept.append(line)
    return kept


def _strip_footer(lines: list[str]) -> list[str]:
    kept: list[str] = []
    for raw_line in lines:
        line = raw_line.rstrip()
        lowered = line.strip().lower()
        has_visible_content = any(item.strip() for item in kept)
        if has_visible_content and any(marker in lowered for marker in FOOTER_MARKERS):
            break
        kept.append(line)
    return kept


def _strip_signature(lines: list[str]) -> list[str]:
    if len(lines) < 2:
        return lines

    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not SIGNATURE_SIGNOFF_RE.match(line):
            continue

        trailing_lines = [item.strip() for item in lines[index + 1 :] if item.strip()]
        if not trailing_lines:
            continue

        signature_like_count = sum(
            1 for item in trailing_lines[:6] if _looks_like_signature_line(item)
        )
        if signature_like_count >= 2 or (signature_like_count >= 1 and len(trailing_lines) >= 2):
            trimmed = [item.rstrip() for item in lines[:index]]
            while trimmed and not trimmed[-1].strip():
                trimmed.pop()
            return trimmed

    return lines


def _looks_like_signature_line(line: str) -> bool:
    lowered = line.lower()
    if EMAIL_RE.search(line) or PHONE_RE.search(line) or WEBSITE_RE.search(line):
        return True
    if _looks_like_name_line(line):
        return True
    if any(keyword in lowered for keyword in SIGNATURE_KEYWORDS) and len(line.split()) <= 8:
        return True
    if any(phrase in lowered for phrase in TITLE_PHRASES):
        return True
    return False


def _truncate_inline_footer(value: str) -> str:
    lowered = value.lower()
    positions = [
        lowered.find(marker)
        for marker in FOOTER_MARKERS
        if lowered.find(marker) > 0
    ]
    if not positions:
        return value
    cut_index = min(positions)
    return value[:cut_index].rstrip(" -,\n")


def _truncate_inline_signature(value: str) -> str:
    compact = value.strip()
    if not compact:
        return ""

    for match in re.finditer(r"[.!?]", compact):
        tail = compact[match.end() :].strip()
        if tail and _looks_like_inline_signature_block(tail):
            return compact[: match.end()].strip()
    return compact


def _looks_like_inline_signature_block(value: str) -> bool:
    lowered = value.lower()
    words = value.replace("|", " ").split()
    if len(words) > 24:
        return False

    strong_signals = 0
    weak_signals = 0
    if EMAIL_RE.search(value) or PHONE_RE.search(value):
        strong_signals += 1
    if any(marker in lowered for marker in FOOTER_MARKERS):
        strong_signals += 2
    if WEBSITE_RE.search(value):
        weak_signals += 1
    if any(keyword in lowered for keyword in SIGNATURE_KEYWORDS):
        weak_signals += 1
    if any(phrase in lowered for phrase in TITLE_PHRASES):
        weak_signals += 1
    if _looks_like_name_prefix(value):
        weak_signals += 1
    return strong_signals >= 2 or (strong_signals >= 1 and weak_signals >= 1) or weak_signals >= 3


def _looks_like_name_prefix(value: str) -> bool:
    tokens = value.split()
    if len(tokens) < 2:
        return False
    prefix = " ".join(tokens[: min(4, len(tokens))])
    for index in range(4, 1, -1):
        candidate = " ".join(tokens[:index])
        if NAME_LIKE_RE.match(candidate):
            return True
    return NAME_LIKE_RE.match(prefix) is not None


def _looks_like_name_line(value: str) -> bool:
    compact = value.strip()
    return bool(compact) and bool(NAME_LIKE_RE.match(compact))
