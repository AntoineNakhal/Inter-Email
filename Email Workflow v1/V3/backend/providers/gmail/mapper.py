"""Maps Gmail message payloads into product thread objects."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from email.utils import getaddresses, parsedate_to_datetime

from backend.core.email_text import clean_email_body, clean_email_snippet
from backend.domain.thread import (
    EmailThread,
    InboundEmailMessage,
    RelevanceBucket,
    SecurityStatus,
    ThreadMessage,
)


QUESTION_HINTS = (
    "can you",
    "could you",
    "please advise",
    "let me know",
    "any update",
    "?",
)
ACTION_HINTS = (
    "please",
    "review",
    "confirm",
    "approve",
    "reply",
    "schedule",
    "next steps",
)
URGENT_HINTS = ("urgent", "asap", "today", "deadline", "immediately", "security")
RESOLVED_HINTS = (
    "resolved",
    "all set",
    "no action needed",
    "done",
    "closed",
    "completed",
)
SENSITIVE_HINTS = (
    "protected a",
    "protected b",
    "tlp amber",
    "tlp red",
    "controlled unclassified information",
    "cui",
)
NEWSLETTER_HINTS = (
    "unsubscribe",
    "newsletter",
    "weekly digest",
    "discount",
    "promotion",
)
THREAD_MERGE_WINDOW_DAYS = 14
HR_HINTS = (
    "interview",
    "candidate",
    "recruit",
    "recruiter",
    "resume",
    "curriculum vitae",
    "cv",
    "hiring",
    "human resources",
    "hr ",
    " hr",
)
GENERIC_LINK_SUBJECTS = {
    "link",
    "meeting link",
    "google meet",
    "join link",
}
INTERNAL_EMAIL_DOMAINS = {
    "inter-op.ca",
}
SUBJECT_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "your",
    "from",
    "this",
    "that",
    "follow",
    "following",
}
STANDALONE_NOTIFICATION_SUBJECT_MARKERS = (
    "weekly recap",
    "weekly digest",
    "newsletter",
    "daily report",
    "monthly report",
    "monitoring alert",
)
REPLY_PREFIX_RE = re.compile(
    r"^(?:re|fw|fwd)\s*:\s*",
    re.IGNORECASE,
)
CALENDAR_NOTIFICATION_PREFIX_RE = re.compile(
    r"^(?:updated|accepted|declined|tentative|invitation|cancelled|canceled)(?: [^:]{0,120})?:\s*",
    re.IGNORECASE,
)
LEADING_SUBJECT_TAG_RE = re.compile(r"^(?:\[[^\]]+\]\s*)+")
SUBJECT_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
UNKNOWN_SENDER_RE = re.compile(r"\bfrom an unknown sender\b", re.IGNORECASE)
GOOGLE_MEET_LINK_RE = re.compile(
    r"(?:https?://)?meet\.google\.com/([a-z]{3}-[a-z]{4}-[a-z]{3})",
    re.IGNORECASE,
)


def group_messages_by_thread(messages: list[InboundEmailMessage]) -> list[EmailThread]:
    """Group normalized Gmail messages into product thread records."""

    grouped: dict[str, list[InboundEmailMessage]] = defaultdict(list)
    for message in messages:
        grouped[message.external_thread_id or message.external_message_id].append(message)

    seed_groups = [
        _build_thread_group(thread_id, thread_messages)
        for thread_id, thread_messages in grouped.items()
    ]
    merged_groups = _merge_related_groups(seed_groups)
    threads = [_build_thread(group) for group in merged_groups]

    return sorted(
        threads,
        key=lambda item: item.latest_message_date or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )


def _build_thread_group(
    thread_id: str,
    thread_messages: list[InboundEmailMessage],
) -> dict[str, object]:
    sorted_messages = sorted(
        thread_messages,
        key=lambda item: _parse_date(item.date_header)
        or datetime.min.replace(tzinfo=timezone.utc),
    )
    latest = sorted_messages[-1]
    earliest = sorted_messages[0]
    subject = _clean_subject(latest.subject or earliest.subject or "(no subject)")
    normalized_subject = _normalize_subject(subject)
    participants = _build_participants(sorted_messages)
    combined_text = _group_combined_text(sorted_messages)

    return {
        "canonical_thread_id": thread_id,
        "source_thread_ids": [thread_id],
        "messages": sorted_messages,
        "participants": participants,
        "participant_keys": {
            _participant_key(item) for item in participants
        },
        "subject": subject,
        "normalized_subject": normalized_subject,
        "meeting_subject_key": _meeting_subject_key(subject),
        "subject_tokens": _subject_token_set(normalized_subject),
        "subject_identifier_tokens": _subject_identifier_tokens(normalized_subject),
        "combined_text": combined_text,
        "meeting_link_keys": _meeting_link_keys(combined_text),
        "external_participant_keys": _external_participant_keys(participants),
        "internal_participant_keys": _internal_participant_keys(participants),
        "hr_related": _is_hr_related(subject, normalized_subject, combined_text),
        "generic_link_subject": _is_generic_link_subject(normalized_subject),
        "latest_date": _parse_date(latest.date_header)
        or datetime.min.replace(tzinfo=timezone.utc),
        "earliest_date": _parse_date(earliest.date_header)
        or datetime.min.replace(tzinfo=timezone.utc),
        "looks_like_notification": _looks_like_notification_subject(normalized_subject),
        "merge_signals": ["gmail_thread_id"],
    }


def _merge_related_groups(groups: list[dict[str, object]]) -> list[dict[str, object]]:
    ordered_groups = sorted(groups, key=lambda item: item["latest_date"])
    merged_groups: list[dict[str, object]] = []
    for group in ordered_groups:
        merged = False
        for cluster in reversed(merged_groups):
            merge_signals = _merge_signals(cluster, group)
            if not merge_signals:
                continue
            _append_thread_group(cluster, group, merge_signals)
            merged = True
            break
        if not merged:
            merged_groups.append(group)
    return merged_groups


def _merge_signals(
    left: dict[str, object],
    right: dict[str, object],
) -> list[str]:
    date_gap = abs((left["latest_date"] - right["latest_date"]).days)
    if date_gap > THREAD_MERGE_WINDOW_DAYS:
        return []

    if left["looks_like_notification"] or right["looks_like_notification"]:
        return []

    participant_overlap = set(left["participant_keys"]) & set(right["participant_keys"])
    if not participant_overlap:
        return []

    signals: list[str] = ["participant_overlap"]
    shared_external_participants = set(left["external_participant_keys"]) & set(
        right["external_participant_keys"]
    )
    if shared_external_participants:
        signals.append("shared_external_participant")

    left_normalized = str(left["normalized_subject"])
    right_normalized = str(right["normalized_subject"])
    left_meeting_key = str(left["meeting_subject_key"])
    right_meeting_key = str(right["meeting_subject_key"])

    if left_normalized and left_normalized == right_normalized:
        signals.append("exact_subject_match")

    if (
        left_meeting_key
        and right_meeting_key
        and left_meeting_key == right_meeting_key
        and left_meeting_key != left_normalized
    ):
        signals.append("meeting_subject_match")

    shared_identifiers = set(left["subject_identifier_tokens"]) & set(
        right["subject_identifier_tokens"]
    )
    if shared_identifiers:
        signals.append("shared_subject_identifier")

    left_tokens = set(left["subject_tokens"])
    right_tokens = set(right["subject_tokens"])
    shared_tokens = left_tokens & right_tokens
    minimum_token_count = min(len(left_tokens), len(right_tokens))
    if len(shared_tokens) >= 4:
        signals.append("strong_subject_token_overlap")
    elif (
        minimum_token_count >= 3
        and len(shared_tokens) >= 3
        and (len(shared_tokens) / float(minimum_token_count)) >= 0.6
    ):
        signals.append("high_subject_token_overlap")

    if date_gap <= 3:
        signals.append("recent_time_window")

    shared_meeting_links = set(left["meeting_link_keys"]) & set(right["meeting_link_keys"])
    if shared_meeting_links and (
        left["hr_related"]
        or right["hr_related"]
        or left_meeting_key == right_meeting_key
    ):
        signals.append("shared_meeting_link")

    if left["hr_related"] and right["hr_related"] and shared_external_participants:
        signals.append("shared_hr_contact")

    if (
        (left["generic_link_subject"] or right["generic_link_subject"])
        and (left["hr_related"] or right["hr_related"])
        and shared_meeting_links
    ):
        signals.append("generic_hr_link_follow_up")
    elif (
        (left["generic_link_subject"] or right["generic_link_subject"])
        and left["hr_related"]
        and right["hr_related"]
        and shared_external_participants
        and date_gap <= 5
    ):
        signals.append("generic_hr_link_follow_up")

    anchor_signals = {
        "exact_subject_match",
        "meeting_subject_match",
        "shared_subject_identifier",
        "strong_subject_token_overlap",
        "high_subject_token_overlap",
        "shared_meeting_link",
        "shared_hr_contact",
        "generic_hr_link_follow_up",
    }
    return _dedupe_strings(signals) if anchor_signals & set(signals) else []


def _append_thread_group(
    target: dict[str, object],
    source: dict[str, object],
    merge_signals: list[str],
) -> None:
    combined_messages = list(target["messages"]) + list(source["messages"])
    combined_messages.sort(
        key=lambda item: _parse_date(item.date_header)
        or datetime.min.replace(tzinfo=timezone.utc)
    )
    target["messages"] = combined_messages
    target["source_thread_ids"] = _dedupe_strings(
        list(target["source_thread_ids"]) + list(source["source_thread_ids"])
    )
    target["participants"] = _dedupe_strings(
        list(target["participants"]) + list(source["participants"])
    )
    target["participant_keys"] = {
        _participant_key(item) for item in target["participants"]
    }
    target["subject_tokens"] = set(target["subject_tokens"]) | set(source["subject_tokens"])
    target["subject_identifier_tokens"] = set(target["subject_identifier_tokens"]) | set(
        source["subject_identifier_tokens"]
    )
    target["combined_text"] = "\n\n".join(
        item for item in [str(target["combined_text"]), str(source["combined_text"])] if item
    )
    target["meeting_link_keys"] = set(target["meeting_link_keys"]) | set(
        source["meeting_link_keys"]
    )
    target["external_participant_keys"] = set(target["external_participant_keys"]) | set(
        source["external_participant_keys"]
    )
    target["internal_participant_keys"] = set(target["internal_participant_keys"]) | set(
        source["internal_participant_keys"]
    )
    target["hr_related"] = bool(target["hr_related"] or source["hr_related"])
    target["generic_link_subject"] = bool(
        target["generic_link_subject"] or source["generic_link_subject"]
    )
    target["latest_date"] = max(target["latest_date"], source["latest_date"])
    if source["earliest_date"] < target["earliest_date"]:
        target["earliest_date"] = source["earliest_date"]
        target["canonical_thread_id"] = source["canonical_thread_id"]

    latest_message = combined_messages[-1]
    latest_subject = _clean_subject(latest_message.subject or target["subject"])
    normalized_subject = _normalize_subject(latest_subject)
    target["subject"] = latest_subject
    target["normalized_subject"] = normalized_subject
    target["meeting_subject_key"] = _meeting_subject_key(latest_subject)
    target["looks_like_notification"] = bool(
        target["looks_like_notification"] or source["looks_like_notification"]
    )
    target["merge_signals"] = _dedupe_strings(
        list(target.get("merge_signals", [])) + list(merge_signals)
    )


def _build_thread(group: dict[str, object]) -> EmailThread:
    sorted_messages = list(group["messages"])
    message_models = [_to_thread_message(item) for item in sorted_messages]
    latest_message = message_models[-1] if message_models else None
    combined_text = "\n\n".join(
        f"From: {message.sender}\nSubject: {message.subject}\n"
        f"Snippet: {message.snippet}\nBody: {message.cleaned_body}"
        for message in message_models
    )
    subject = _clean_subject(group["subject"] or "(no subject)")
    participants = list(group["participants"])
    security_markers = _find_markers(subject, combined_text, SENSITIVE_HINTS)
    latest_text = (
        f"{latest_message.snippet}\n{latest_message.cleaned_body}".lower()
        if latest_message
        else ""
    )
    latest_from_me = bool(latest_message and "SENT" in (latest_message.label_ids or []))
    latest_from_external = not latest_from_me
    has_question = any(marker in latest_text for marker in QUESTION_HINTS)
    has_action_request = any(marker in latest_text for marker in ACTION_HINTS)
    resolved = any(marker in latest_text for marker in RESOLVED_HINTS)
    waiting_on_us = latest_from_external and (has_question or has_action_request) and not resolved
    relevance_score = _score_thread(
        subject=subject,
        combined_text=combined_text,
        waiting_on_us=waiting_on_us,
        latest_from_external=latest_from_external,
    )
    relevance_bucket = _bucket_for_score(relevance_score, subject, combined_text)
    included_in_ai = relevance_bucket in {
        RelevanceBucket.MUST_REVIEW,
        RelevanceBucket.IMPORTANT,
    }

    thread = EmailThread(
        external_thread_id=str(group["canonical_thread_id"]),
        source_thread_ids=list(group["source_thread_ids"]),
        grouping_reason=(
            "subject_merge"
            if len(group["source_thread_ids"]) > 1
            else "gmail_thread_id"
        ),
        merge_signals=list(group.get("merge_signals", [])),
        subject=subject,
        participants=participants,
        message_count=len(message_models),
        latest_message_date=latest_message.sent_at if latest_message else None,
        messages=message_models,
        combined_thread_text=combined_text[:10000],
        security_status=(
            SecurityStatus.CLASSIFIED
            if security_markers
            else SecurityStatus.STANDARD
        ),
        sensitivity_markers=security_markers,
        latest_message_from_me=latest_from_me,
        latest_message_from_external=latest_from_external,
        latest_message_has_question=has_question,
        latest_message_has_action_request=has_action_request,
        waiting_on_us=waiting_on_us,
        resolved_or_closed=resolved,
        relevance_score=relevance_score,
        relevance_bucket=relevance_bucket,
        included_in_ai=included_in_ai,
        ai_decision=(
            "must_send_to_ai"
            if included_in_ai and relevance_bucket == RelevanceBucket.MUST_REVIEW
            else "good_candidate"
            if included_in_ai
            else "skip"
        ),
        ai_decision_reason=(
            "Thread is actionable and should be analyzed."
            if included_in_ai
            else "Thread was classified as low-signal or noise."
        ),
    )
    thread.signature = thread.compute_signature()
    return thread


def _to_thread_message(message: InboundEmailMessage) -> ThreadMessage:
    recipients = [addr for _, addr in getaddresses([message.to_address]) if addr]
    cleaned_snippet = clean_email_snippet(message.snippet)
    cleaned_body = clean_email_body(message.body_text)
    return ThreadMessage(
        external_message_id=message.external_message_id,
        sender=message.from_address,
        recipients=recipients,
        subject=message.subject,
        sent_at=_parse_date(message.date_header),
        snippet=cleaned_snippet[:500],
        cleaned_body=cleaned_body[:4000],
        label_ids=message.label_ids,
    )


def _build_participants(messages: list[InboundEmailMessage]) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for message in messages:
        for _, address in getaddresses([message.from_address, message.to_address]):
            cleaned = address.strip().lower()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            values.append(address)
    return values


def _participant_key(value: str) -> str:
    addresses = [addr for _, addr in getaddresses([value]) if addr]
    if addresses:
        return addresses[0].strip().lower()
    return value.strip().lower()


def _parse_date(value: str) -> datetime | None:
    try:
        parsed = parsedate_to_datetime(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, IndexError):
        return None


def _find_markers(subject: str, body: str, markers: tuple[str, ...]) -> list[str]:
    text = f"{subject}\n{body}".lower()
    return [marker for marker in markers if marker in text]


def _clean_subject(value: str) -> str:
    subject = str(value or "").strip()
    return re.sub(r"\s+", " ", subject).strip() or "(no subject)"


def _normalize_subject(value: str) -> str:
    normalized = _clean_subject(value)
    previous = ""
    while previous != normalized:
        previous = normalized
        normalized = REPLY_PREFIX_RE.sub("", normalized)
        normalized = CALENDAR_NOTIFICATION_PREFIX_RE.sub("", normalized)
    normalized = UNKNOWN_SENDER_RE.sub("", normalized)
    normalized = LEADING_SUBJECT_TAG_RE.sub("", normalized)
    normalized = re.sub(r"\s+@\s+.+$", "", normalized)
    normalized = re.sub(r"\([^)]*@[^)]*\)$", "", normalized)
    normalized = re.sub(r"[,:;_/\\-]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip().lower()
    return normalized


def _meeting_subject_key(value: str) -> str:
    normalized = _normalize_subject(value)
    if not normalized:
        return ""
    if not any(keyword in normalized for keyword in ("meeting", "interview", "calendar")):
        return normalized
    compact = re.sub(r"\b(?:mon|tue|wed|thu|fri|sat|sun)\b", " ", normalized)
    compact = re.sub(
        r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b",
        " ",
        compact,
    )
    compact = re.sub(r"\b\d{1,4}(?::\d{2})?(?:am|pm)?\b", " ", compact)
    compact = re.sub(r"\b(?:edt|est|pst|mst|gmt|utc)\b", " ", compact)
    compact = re.sub(r"\s+", " ", compact).strip()
    return compact


def _subject_token_set(normalized_subject: str) -> set[str]:
    tokens: set[str] = set()
    for token in SUBJECT_TOKEN_RE.findall(normalized_subject):
        if token in SUBJECT_STOPWORDS:
            continue
        if len(token) < 3 and not any(character.isdigit() for character in token):
            continue
        tokens.add(token)
    return tokens


def _subject_identifier_tokens(normalized_subject: str) -> set[str]:
    identifiers: set[str] = set()
    for token in _subject_token_set(normalized_subject):
        if not any(character.isdigit() for character in token):
            continue
        if token.isdigit() and len(token) == 4 and 1900 <= int(token) <= 2100:
            continue
        identifiers.add(token)
    return identifiers


def _looks_like_notification_subject(normalized_subject: str) -> bool:
    if any(marker in normalized_subject for marker in STANDALONE_NOTIFICATION_SUBJECT_MARKERS):
        return True
    if "weekly" in normalized_subject and ("recap" in normalized_subject or "digest" in normalized_subject):
        return True
    if "monthly" in normalized_subject and "report" in normalized_subject:
        return True
    if any(marker in normalized_subject for marker in NEWSLETTER_HINTS):
        return True
    return False


def _group_combined_text(messages: list[InboundEmailMessage]) -> str:
    return "\n\n".join(
        "\n".join(
            part
            for part in [
                message.subject,
                clean_email_snippet(message.snippet),
                clean_email_body(message.body_text),
            ]
            if part
        )
        for message in messages
    )


def _meeting_link_keys(text: str) -> set[str]:
    return {
        match.group(1).lower()
        for match in GOOGLE_MEET_LINK_RE.finditer(text)
        if match.group(1)
    }


def _is_hr_related(subject: str, normalized_subject: str, combined_text: str) -> bool:
    lowered = f"{subject}\n{normalized_subject}\n{combined_text}".lower()
    return any(hint in lowered for hint in HR_HINTS)


def _is_generic_link_subject(normalized_subject: str) -> bool:
    return normalized_subject in GENERIC_LINK_SUBJECTS


def _external_participant_keys(participants: list[str]) -> set[str]:
    return {
        key
        for key in (_participant_key(item) for item in participants)
        if key and not _is_internal_email(key)
    }


def _internal_participant_keys(participants: list[str]) -> set[str]:
    return {
        key
        for key in (_participant_key(item) for item in participants)
        if key and _is_internal_email(key)
    }


def _is_internal_email(value: str) -> bool:
    if "@" not in value:
        return False
    domain = value.split("@", 1)[1].strip().lower()
    return domain in INTERNAL_EMAIL_DOMAINS


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _score_thread(
    subject: str,
    combined_text: str,
    waiting_on_us: bool,
    latest_from_external: bool,
) -> int:
    lowered = f"{subject}\n{combined_text}".lower()
    score = 1
    if waiting_on_us:
        score += 2
    if latest_from_external:
        score += 1
    if any(marker in lowered for marker in URGENT_HINTS):
        score += 2
    if any(marker in lowered for marker in ("invoice", "proposal", "meeting", "customer", "partner")):
        score += 1
    if any(marker in lowered for marker in NEWSLETTER_HINTS):
        score -= 2
    return max(1, min(score, 5))


def _bucket_for_score(
    score: int,
    subject: str,
    combined_text: str,
) -> RelevanceBucket:
    lowered = f"{subject}\n{combined_text}".lower()
    if any(marker in lowered for marker in NEWSLETTER_HINTS):
        return RelevanceBucket.NOISE
    if score >= 4:
        return RelevanceBucket.MUST_REVIEW
    if score == 3:
        return RelevanceBucket.IMPORTANT
    if score == 2:
        return RelevanceBucket.MAYBE
    return RelevanceBucket.NOISE
