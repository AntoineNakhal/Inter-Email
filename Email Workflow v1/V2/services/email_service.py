"""Application service for retrieving, filtering, scoring, and grouping Gmail threads."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from email.utils import getaddresses, parsedate_to_datetime

from config import Settings
from gmail_client import GmailReadonlyClient
from schemas import (
    AgentThread,
    AgentThreadMessage,
    EmailMessage,
    EmailThread,
    ThreadMessage,
)


class EmailService:
    """Keeps Gmail fetching and thread grouping separate from agent orchestration."""

    AUTO_ANALYSIS_BUCKETS = {"must_review", "important"}
    AUTO_ANALYSIS_SCORE_THRESHOLD = 2
    SENSITIVE_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("Protected A", ("protected a", "protected-a")),
        ("Protected B", ("protected b", "protected-b")),
        ("TLP Amber", ("tlp amber", "tlp:amber", "tlp-amber")),
        ("TLP Red", ("tlp red", "tlp:red", "tlp-red")),
        (
            "CUI",
            (
                "controlled unclassified information",
                " controlled unclassified ",
                " cui ",
                "(cui)",
            ),
        ),
    )
    SUBJECT_LIMIT = 200
    PARTICIPANT_LIMIT = 200
    SNIPPET_LIMIT = 500
    BODY_LIMIT = 1000
    THREAD_TEXT_LIMIT = 6000
    AI_THREAD_TEXT_LIMIT = 5000
    AI_MESSAGE_LIMIT = 12
    SUBJECT_MERGE_WINDOW_DAYS = 21
    REPLY_FORWARD_PREFIX_RE = re.compile(
        r"^(?:(?:re|fw|fwd)\s*:\s*)+",
        re.IGNORECASE,
    )
    LEADING_SUBJECT_TAG_RE = re.compile(r"^(?:\[[^\]]+\]\s*)+", re.IGNORECASE)
    SUBJECT_TOKEN_RE = re.compile(r"[a-z0-9]+")
    SUBJECT_STOPWORDS = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "this",
        "that",
        "your",
        "our",
        "regarding",
        "about",
        "please",
        "follow",
        "need",
        "update",
        "question",
        "reply",
        "response",
        "external",
        "email",
    }
    NEWSLETTER_SENDER_MARKERS = (
        "no-reply",
        "noreply",
        "newsletter",
        "marketing",
        "promo",
        "promotions",
    )
    NEWSLETTER_SUBJECT_MARKERS = (
        "unsubscribe",
        "weekly digest",
        "newsletter",
        "sale",
        "discount",
        "deal",
        "offer",
        "promotion",
    )
    STANDALONE_NOTIFICATION_SUBJECT_MARKERS = (
        "weekly recap",
        "weekly digest",
        "monthly report",
        "report is ready",
        "log in code",
        "login code",
        "security alert",
        "verification code",
        "one-time passcode",
        "password reset",
    )
    CALENDAR_SUBJECT_MARKERS = (
        "invitation",
        "accepted",
        "declined",
        "tentative",
        "cancelled",
        "canceled",
        "google calendar",
    )
    CALENDAR_MONTH_OR_DAY_MARKERS = (
        "mon",
        "tue",
        "wed",
        "thu",
        "fri",
        "sat",
        "sun",
        "jan",
        "feb",
        "mar",
        "apr",
        "may",
        "jun",
        "jul",
        "aug",
        "sep",
        "oct",
        "nov",
        "dec",
    )
    TIME_TOKEN_RE = re.compile(r"^\d{1,4}(?:am|pm)$", re.IGNORECASE)
    CONVERSATION_MERGE_KEYWORDS = (
        "rfq",
        "quote",
        "quotation",
        "proposal",
        "contract",
        "invoice",
        "payment",
        "meeting",
        "event",
        "customer",
        "partner",
        "support",
        "renewal",
        "project",
        "call-up",
        "solicitation",
        "tender",
    )
    HIGH_VALUE_KEYWORDS = (
        "urgent",
        "asap",
        "security",
        "security alert",
        "invoice",
        "invoice due",
        "payment",
        "payment due",
        "billing",
        "renewal",
        "proposal",
        "contract",
        "meeting",
        "event",
        "action required",
        "domain",
        "customer",
        "partner",
        "client",
        "support",
        "alert",
        "escalation",
        "deadline",
        "receipt",
        "review",
        "rfq",
        "quote",
        "quotation",
    )
    ACTION_KEYWORDS = (
        "please",
        "can you",
        "reply",
        "review",
        "confirm",
        "approve",
        "schedule",
        "follow up",
        "let me know",
        "need",
        "action required",
        "next steps",
    )
    URGENT_KEYWORDS = (
        "urgent",
        "asap",
        "today",
        "immediately",
        "deadline",
        "security",
        "payment due",
        "invoice due",
        "action required",
    )
    QUESTION_KEYWORDS = (
        "can you",
        "could you",
        "would you",
        "please advise",
        "let me know",
        "any update",
        "what do you think",
        "do you have",
        "are you able",
        "when can",
        "who can",
    )
    RESOLVED_KEYWORDS = (
        "resolved",
        "all set",
        "no further action",
        "no action needed",
        "nothing else needed",
        "completed",
        "done",
        "closed",
        "issue is fixed",
        "we can close",
        "no reply needed",
        "handled",
    )

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = GmailReadonlyClient(
            credentials_path=settings.credentials_path,
            token_path=settings.token_path,
        )

    def fetch_recent_emails(self, max_results: int) -> list[EmailMessage]:
        """Fetch recent Gmail-triggered threads and keep the full thread history."""

        safe_max_results = max(1, max_results)
        raw_messages = self.client.list_recent_messages(
            max_results=safe_max_results,
            source=self.settings.gmail_thread_source,
        )
        sanitized_messages = [self._sanitize_email(message) for message in raw_messages]
        return [EmailMessage.model_validate(message) for message in sanitized_messages]

    def fetch_recent_threads(self, max_results: int) -> list[EmailThread]:
        """Fetch Gmail messages and group them into thread records."""

        emails = self.fetch_recent_emails(max_results=max_results)
        return self.group_messages_by_thread(emails)

    def group_messages_by_thread(self, emails: list[EmailMessage]) -> list[EmailThread]:
        """Group Gmail messages into conversation threads.

        Step 1 uses Gmail's native `thread_id`.
        Step 2 does a conservative subject-based merge for split conversations.
        """

        grouped_messages: dict[str, list[tuple[int, EmailMessage]]] = defaultdict(list)
        for index, email in enumerate(emails):
            grouped_messages[email.thread_id or email.id].append((index, email))

        merged_groups = self._merge_related_thread_groups(grouped_messages)
        threads = [
            self._build_thread_from_group(group)
            for group in merged_groups
        ]

        threads.sort(key=self._thread_sort_key, reverse=True)
        return threads

    def select_threads_for_ai(self, threads: list[EmailThread]) -> list[AgentThread]:
        """Classify threads by relevance and return the ones to analyze automatically."""

        candidates: list[AgentThread] = []

        for thread in threads:
            score = self._score_thread(thread)
            filtered_reason = self._filter_reason(thread)
            sensitive_markers = self._detect_sensitive_markers(thread)
            bucket, bucket_reason = self._classify_thread_bucket(
                thread=thread,
                score=score,
                filtered_reason=filtered_reason,
            )
            thread.relevance_score = score
            thread.relevance_bucket = bucket

            if sensitive_markers:
                thread.security_status = "classified"
                thread.sensitivity_markers = sensitive_markers
                thread.sensitivity_reason = (
                    "Sensitive government-handling markers were detected in the thread "
                    "content before AI processing."
                )
                thread.relevance_score = 5
                thread.relevance_bucket = "must_review"
                thread.included_in_ai = False
                thread.analysis_status = "guardrailed"
                thread.selection_reason = self._selection_reason(
                    (
                        "Held out of AI because sensitive/classified markers were "
                        f"detected: {', '.join(sensitive_markers)}."
                    ),
                    thread,
                )
                thread.ai_decision = "blocked_sensitive"
                thread.ai_decision_reason = thread.selection_reason
                continue

            if filtered_reason:
                thread.included_in_ai = False
                thread.analysis_status = "skipped"
                thread.selection_reason = self._selection_reason(
                    f"Relevance bucket {bucket}: {bucket_reason}",
                    thread,
                )
                thread.ai_decision = "skip"
                thread.ai_decision_reason = thread.selection_reason
                continue

            auto_analyze = score >= self.AUTO_ANALYSIS_SCORE_THRESHOLD
            thread.included_in_ai = auto_analyze
            if auto_analyze:
                thread.analysis_status = None
            elif bucket == "noise":
                thread.analysis_status = "skipped"
            else:
                thread.analysis_status = "not_requested"

            if auto_analyze:
                thread.selection_reason = self._selection_reason(
                    (
                        f"Auto-analyzed because relevance score {score} met the "
                        f"score threshold {self.AUTO_ANALYSIS_SCORE_THRESHOLD}. "
                        f"Bucket {bucket}: {bucket_reason}"
                    ),
                    thread,
                )
                thread.ai_decision = (
                    "must_send_to_ai"
                    if bucket == "must_review" or score >= 3
                    else "good_candidate"
                )
                thread.ai_decision_reason = thread.selection_reason
                candidates.append(self.build_agent_thread(thread))
                continue

            if bucket == "noise":
                thread.selection_reason = self._selection_reason(
                    (
                        f"Skipped because relevance score {score} is below the "
                        f"score threshold {self.AUTO_ANALYSIS_SCORE_THRESHOLD}. "
                        f"Bucket {bucket}: {bucket_reason}"
                    ),
                    thread,
                )
                thread.ai_decision = "skip"
                thread.ai_decision_reason = thread.selection_reason
            else:
                thread.selection_reason = self._selection_reason(
                    (
                        f"Visible in review, but not auto-analyzed because relevance "
                        f"score {score} is below the score threshold "
                        f"{self.AUTO_ANALYSIS_SCORE_THRESHOLD}. "
                        f"Bucket {bucket}: {bucket_reason}"
                    ),
                    thread,
                )
                thread.ai_decision = "maybe"
                thread.ai_decision_reason = thread.selection_reason

        return candidates

    def build_agent_thread(self, thread: EmailThread) -> AgentThread:
        """Build the compact thread payload used by AI or cached summary steps."""

        return AgentThread(
            thread_id=thread.thread_id,
            subject=self._clean_text(thread.subject, self.SUBJECT_LIMIT),
            participants=[
                self._clean_text(participant, self.PARTICIPANT_LIMIT)
                for participant in thread.participants[:12]
            ],
            message_count=thread.message_count,
            latest_message_date=self._clean_text(
                thread.latest_message_date, self.PARTICIPANT_LIMIT
            ),
            messages=self._build_agent_thread_messages(thread),
            combined_thread_text=thread.combined_thread_text[
                : self.AI_THREAD_TEXT_LIMIT
            ],
            relevance_score=thread.relevance_score or self._score_thread(thread),
        )

    def _build_agent_thread_messages(
        self, thread: EmailThread
    ) -> list[AgentThreadMessage]:
        """Keep the agent payload compact while preserving message order."""

        selected_messages = thread.messages[-self.AI_MESSAGE_LIMIT :]
        return [
            AgentThreadMessage(
                message_id=message.message_id,
                sender=self._clean_text(message.sender, self.PARTICIPANT_LIMIT),
                subject=self._clean_text(message.subject, self.SUBJECT_LIMIT),
                date=self._clean_text(message.date, self.PARTICIPANT_LIMIT),
                snippet=self._clean_text(message.snippet, self.SNIPPET_LIMIT),
                cleaned_body=self._clean_text(message.cleaned_body, self.BODY_LIMIT),
            )
            for message in selected_messages
        ]

    def _sanitize_email(
        self, message: dict[str, str | list[str]]
    ) -> dict[str, str | list[str]]:
        """Normalize and trim Gmail message data before it touches the agents."""

        return {
            "id": message.get("id", ""),
            "thread_id": message.get("thread_id", ""),
            "subject": self._clean_text(message.get("subject", ""), self.SUBJECT_LIMIT),
            "from_address": self._clean_text(
                message.get("from_address", ""), self.PARTICIPANT_LIMIT
            ),
            "to_address": self._clean_text(
                message.get("to_address", ""), self.PARTICIPANT_LIMIT
            ),
            "date": self._clean_text(message.get("date", ""), self.PARTICIPANT_LIMIT),
            "snippet": self._clean_text(message.get("snippet", ""), self.SNIPPET_LIMIT),
            "body_text": self._clean_text(message.get("body_text", ""), self.BODY_LIMIT),
            "label_ids": [
                str(label) for label in (message.get("label_ids", []) or [])
            ],
        }

    def _clean_text(self, value: str, limit: int) -> str:
        """Remove HTML, URLs, and control characters so payloads stay compact."""

        normalized = value or ""
        normalized = re.sub(r"(?is)<style.*?>.*?</style>", " ", normalized)
        normalized = re.sub(r"(?is)<script.*?>.*?</script>", " ", normalized)
        normalized = re.sub(r"(?s)<[^>]+>", " ", normalized)
        normalized = re.sub(r"https?://\S+", " ", normalized)
        normalized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", normalized)
        normalized = (
            normalized.replace("&nbsp;", " ")
            .replace("&#39;", "'")
            .replace("&amp;", "&")
        )
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized[:limit]

    def _message_sort_key(
        self, email: EmailMessage, index: int
    ) -> tuple[datetime, int]:
        return (self._parse_date(email.date), index)

    def _build_thread_from_group(self, group: dict[str, object]) -> EmailThread:
        """Build one stored thread record from a grouped set of emails."""

        indexed_messages = group["indexed_messages"]
        ordered_emails = [email for _, email in indexed_messages]
        latest_email = ordered_emails[-1]
        thread_subject = self._choose_thread_subject(ordered_emails)
        participants = self._collect_participants(ordered_emails)
        combined_thread_text = self._build_combined_thread_text(ordered_emails)
        thread_signals = self._build_thread_signals(
            emails=ordered_emails,
            participants=participants,
            subject=thread_subject,
        )
        thread_messages = [
            ThreadMessage(
                message_id=email.id,
                sender=email.from_address,
                subject=email.subject,
                date=email.date,
                snippet=email.snippet,
                cleaned_body=email.body_text,
            )
            for email in ordered_emails
        ]

        return EmailThread(
            thread_id=str(group["thread_id"]),
            source_thread_ids=list(group["source_thread_ids"]),
            grouping_reason=str(group["grouping_reason"]),
            merge_signals=list(group.get("merge_signals", [])),
            merge_confidence=group.get("merge_confidence"),
            subject=thread_subject,
            participants=participants,
            message_count=len(thread_messages),
            latest_message_date=latest_email.date,
            messages=thread_messages,
            combined_thread_text=combined_thread_text,
            latest_message_from_me=thread_signals["latest_message_from_me"],
            latest_message_from_external=thread_signals["latest_message_from_external"],
            latest_message_has_question=thread_signals["latest_message_has_question"],
            latest_message_has_action_request=thread_signals[
                "latest_message_has_action_request"
            ],
            waiting_on_us=thread_signals["waiting_on_us"],
            resolved_or_closed=thread_signals["resolved_or_closed"],
        )

    def _merge_related_thread_groups(
        self,
        grouped_messages: dict[str, list[tuple[int, EmailMessage]]],
    ) -> list[dict[str, object]]:
        """Merge obvious split conversations when subject/context strongly match."""

        groups = [
            self._build_subject_group(thread_id, indexed_messages)
            for thread_id, indexed_messages in grouped_messages.items()
        ]
        groups.sort(key=lambda item: item["latest_date"])

        merged_groups: list[dict[str, object]] = []
        for group in groups:
            merged = False
            for cluster in reversed(merged_groups):
                merge_details = self._evaluate_subject_group_merge(cluster, group)
                if merge_details is not None:
                    self._append_subject_group(cluster, group, merge_details)
                    merged = True
                    break

            if not merged:
                merged_groups.append(group)

        return merged_groups

    def _build_subject_group(
        self,
        thread_id: str,
        indexed_messages: list[tuple[int, EmailMessage]],
    ) -> dict[str, object]:
        """Create a small internal structure used by the merge pass."""

        ordered_indexed_messages = sorted(
            indexed_messages,
            key=lambda item: self._message_sort_key(item[1], item[0]),
        )
        ordered_emails = [email for _, email in ordered_indexed_messages]
        subject = self._choose_thread_subject(ordered_emails)
        participants = self._collect_participants(ordered_emails)

        return {
            "thread_id": thread_id,
            "source_thread_ids": [thread_id],
            "grouping_reason": "gmail_thread_id",
            "merge_signals": ["gmail_thread_id"],
            "merge_confidence": "high",
            "indexed_messages": ordered_indexed_messages,
            "normalized_subject": self._normalize_subject(subject),
            "subject_tokens": self._subject_token_set(subject),
            "subject_identifier_tokens": self._subject_identifier_tokens(subject),
            "latest_date": self._parse_date(ordered_emails[-1].date),
            "participants": participants,
            "participant_keys": {item.lower() for item in participants},
            "has_reply_or_forward_subject": any(
                self._subject_has_reply_or_forward_prefix(email.subject)
                for email in ordered_emails
            ),
            "looks_like_notification": self._looks_like_standalone_notification_subject(
                subject
            ),
            "looks_like_calendar_thread": self._looks_like_calendar_subject(subject),
            "has_business_signal": self._subject_has_business_signal(subject),
        }

    def _evaluate_subject_group_merge(
        self,
        left: dict[str, object],
        right: dict[str, object],
    ) -> dict[str, object] | None:
        """Return merge diagnostics when two Gmail thread groups are safe to combine."""

        date_gap = abs((left["latest_date"] - right["latest_date"]).days)
        if date_gap > self.SUBJECT_MERGE_WINDOW_DAYS:
            return None

        if left["looks_like_notification"] or right["looks_like_notification"]:
            return None

        if left["looks_like_calendar_thread"] or right["looks_like_calendar_thread"]:
            return None

        relationship = self._subject_relationship_details(left, right)
        if not relationship["signals"]:
            return None

        participant_overlap = bool(left["participant_keys"] & right["participant_keys"])
        shared_identifiers = bool(
            left["subject_identifier_tokens"] & right["subject_identifier_tokens"]
        )
        has_reply_forward_signal = bool(
            left["has_reply_or_forward_subject"] or right["has_reply_or_forward_subject"]
        )
        both_have_business_signal = bool(
            left["has_business_signal"] and right["has_business_signal"]
        )

        score = 0
        signals = list(relationship["signals"])
        anchor_signal = False

        if relationship["exact_subject_match"]:
            score += 2
            anchor_signal = True
        elif relationship["contained_subject_match"]:
            score += 1

        if relationship["strong_token_overlap"]:
            score += 2
        elif relationship["token_overlap"]:
            score += 1

        if participant_overlap:
            signals.append("participant_overlap")
            score += 3
            anchor_signal = True

        if shared_identifiers:
            signals.append("shared_subject_identifier")
            score += 3
            anchor_signal = True

        if has_reply_forward_signal:
            signals.append("reply_or_forward_subject")
            score += 1

        if both_have_business_signal:
            signals.append("shared_business_context")
            score += 1

        if date_gap <= 3:
            signals.append("recent_time_window")
            score += 1

        if not anchor_signal and not (
            relationship["exact_subject_match"]
            and (
                both_have_business_signal
                or has_reply_forward_signal
                or date_gap <= 3
            )
        ):
            return None

        if score < 4:
            return None

        return {
            "signals": self._dedupe_strings(signals),
            "confidence": self._merge_confidence_from_score(score),
            "score": score,
        }

    def _should_merge_subject_group(
        self,
        left: dict[str, object],
        right: dict[str, object],
    ) -> bool:
        """Return True when two Gmail threads should become one conversation card."""

        return self._evaluate_subject_group_merge(left, right) is not None

    def _append_subject_group(
        self,
        target: dict[str, object],
        source: dict[str, object],
        merge_details: dict[str, object],
    ) -> None:
        """Merge one subject group into another in place."""

        combined_messages = list(target["indexed_messages"]) + list(source["indexed_messages"])
        combined_messages.sort(key=lambda item: self._message_sort_key(item[1], item[0]))
        target["indexed_messages"] = combined_messages

        source_thread_ids = list(target["source_thread_ids"]) + list(source["source_thread_ids"])
        deduped_thread_ids: list[str] = []
        seen_thread_ids: set[str] = set()
        for thread_id in source_thread_ids:
            if thread_id in seen_thread_ids:
                continue
            seen_thread_ids.add(thread_id)
            deduped_thread_ids.append(thread_id)
        target["source_thread_ids"] = deduped_thread_ids

        participants = list(target["participants"]) + list(source["participants"])
        deduped_participants: list[str] = []
        seen_participants: set[str] = set()
        for participant in participants:
            key = participant.lower()
            if key in seen_participants:
                continue
            seen_participants.add(key)
            deduped_participants.append(participant)
        target["participants"] = deduped_participants
        target["participant_keys"] = seen_participants
        target["latest_date"] = max(target["latest_date"], source["latest_date"])
        target["has_reply_or_forward_subject"] = bool(
            target["has_reply_or_forward_subject"] or source["has_reply_or_forward_subject"]
        )
        target["looks_like_notification"] = bool(
            target["looks_like_notification"] or source["looks_like_notification"]
        )
        target["looks_like_calendar_thread"] = bool(
            target["looks_like_calendar_thread"] or source["looks_like_calendar_thread"]
        )
        target["has_business_signal"] = bool(
            target["has_business_signal"] or source["has_business_signal"]
        )
        target["subject_tokens"] = set(target["subject_tokens"]) | set(source["subject_tokens"])
        target["subject_identifier_tokens"] = set(
            target["subject_identifier_tokens"]
        ) | set(source["subject_identifier_tokens"])
        target["grouping_reason"] = "subject_merge"
        target["merge_signals"] = self._dedupe_strings(
            list(target.get("merge_signals", []))
            + list(source.get("merge_signals", []))
            + list(merge_details.get("signals", []))
        )
        target["merge_confidence"] = self._lowest_merge_confidence(
            target.get("merge_confidence"),
            merge_details.get("confidence"),
        )

        latest_thread_id = ""
        latest_date = datetime.min.replace(tzinfo=timezone.utc)
        for _, email in combined_messages:
            email_date = self._parse_date(email.date)
            if email_date >= latest_date:
                latest_date = email_date
                latest_thread_id = email.thread_id or email.id
        if latest_thread_id:
            target["thread_id"] = latest_thread_id

    def _thread_sort_key(self, thread: EmailThread) -> datetime:
        return self._parse_date(thread.latest_message_date)

    def _parse_date(self, value: str) -> datetime:
        """Parse Gmail dates conservatively and fall back to the oldest value."""

        minimum = datetime.min.replace(tzinfo=timezone.utc)
        if not value:
            return minimum

        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError):
            return minimum

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _choose_thread_subject(self, emails: list[EmailMessage]) -> str:
        for email in reversed(emails):
            if email.subject:
                return email.subject
        return "(No subject)"

    def _normalize_subject(self, value: str) -> str:
        """Strip reply prefixes so split threads can share one conversation key."""

        normalized = self.REPLY_FORWARD_PREFIX_RE.sub("", value or "")
        normalized = self.LEADING_SUBJECT_TAG_RE.sub("", normalized)
        normalized = re.sub(r"[,:;_/\\-]+", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip().lower()
        if normalized in {"", "(no subject)"}:
            return ""
        return normalized

    def _subject_token_set(self, value: str) -> set[str]:
        """Extract meaningful subject words for cross-thread merge checks."""

        normalized = self._normalize_subject(value)
        tokens: set[str] = set()
        for token in self.SUBJECT_TOKEN_RE.findall(normalized):
            if token in self.SUBJECT_STOPWORDS:
                continue
            if len(token) < 3 and not any(character.isdigit() for character in token):
                continue
            tokens.add(token)
        return tokens

    def _subject_identifier_tokens(self, value: str) -> set[str]:
        """Keep business identifiers like RFQ or solicitation numbers."""

        identifiers: set[str] = set()
        for token in self._subject_token_set(value):
            if not any(character.isdigit() for character in token):
                continue
            if self._is_low_signal_identifier_token(token):
                continue
            identifiers.add(token)
        return identifiers

    def _subjects_look_related(
        self,
        left: dict[str, object],
        right: dict[str, object],
    ) -> bool:
        """Allow merge when subjects clearly point to the same real conversation."""

        return bool(self._subject_relationship_details(left, right)["signals"])

    def _subject_relationship_details(
        self,
        left: dict[str, object],
        right: dict[str, object],
    ) -> dict[str, object]:
        """Describe how strongly two normalized subjects point to the same work item."""

        left_subject = str(left["normalized_subject"])
        right_subject = str(right["normalized_subject"])
        if not left_subject or not right_subject:
            return {
                "signals": [],
                "exact_subject_match": False,
                "contained_subject_match": False,
                "strong_token_overlap": False,
                "token_overlap": False,
            }

        signals: list[str] = []
        exact_subject_match = False
        contained_subject_match = False
        strong_token_overlap = False
        token_overlap = False

        if left_subject == right_subject:
            signals.append("exact_subject_match")
            exact_subject_match = True

        shorter_subject, longer_subject = sorted(
            (left_subject, right_subject),
            key=len,
        )
        if len(shorter_subject) >= 12 and shorter_subject in longer_subject:
            signals.append("subject_contains_other")
            contained_subject_match = True

        left_identifiers = set(left["subject_identifier_tokens"])
        right_identifiers = set(right["subject_identifier_tokens"])
        if left_identifiers & right_identifiers:
            signals.append("shared_subject_identifier")

        left_tokens = set(left["subject_tokens"])
        right_tokens = set(right["subject_tokens"])
        if not left_tokens or not right_tokens:
            return {
                "signals": self._dedupe_strings(signals),
                "exact_subject_match": exact_subject_match,
                "contained_subject_match": contained_subject_match,
                "strong_token_overlap": strong_token_overlap,
                "token_overlap": token_overlap,
            }

        shared_tokens = left_tokens & right_tokens
        minimum_token_count = min(len(left_tokens), len(right_tokens))
        if len(shared_tokens) >= 4:
            signals.append("strong_subject_token_overlap")
            strong_token_overlap = True

        if minimum_token_count >= 3 and len(shared_tokens) >= 3:
            overlap_ratio = len(shared_tokens) / float(minimum_token_count)
            if overlap_ratio >= 0.6:
                signals.append("high_subject_token_overlap")
                token_overlap = True

        return {
            "signals": self._dedupe_strings(signals),
            "exact_subject_match": exact_subject_match,
            "contained_subject_match": contained_subject_match,
            "strong_token_overlap": strong_token_overlap,
            "token_overlap": token_overlap,
        }

    def _subject_has_reply_or_forward_prefix(self, value: str) -> bool:
        return bool(self.REPLY_FORWARD_PREFIX_RE.match(value or ""))

    def _looks_like_standalone_notification_subject(self, value: str) -> bool:
        normalized = self._normalize_subject(value)
        if any(
            marker in normalized for marker in self.STANDALONE_NOTIFICATION_SUBJECT_MARKERS
        ):
            return True
        if "weekly" in normalized and ("recap" in normalized or "digest" in normalized):
            return True
        if "monthly" in normalized and "report" in normalized:
            return True
        return False

    def _looks_like_calendar_subject(self, value: str) -> bool:
        """Return True for calendar-style invitation subjects that should never snowball."""

        normalized = self._normalize_subject(value)
        if not normalized:
            return False

        has_calendar_marker = any(
            marker in normalized for marker in self.CALENDAR_SUBJECT_MARKERS
        )
        has_time_marker = bool(
            re.search(r"\b\d{1,4}(?:am|pm)\b", normalized, re.IGNORECASE)
        )
        has_day_or_month_marker = any(
            re.search(rf"\b{marker}\b", normalized)
            for marker in self.CALENDAR_MONTH_OR_DAY_MARKERS
        )

        if "google calendar" in normalized:
            return True

        return bool(has_calendar_marker and (has_time_marker or has_day_or_month_marker))

    def _subject_has_business_signal(self, value: str) -> bool:
        normalized = self._normalize_subject(value)
        return any(keyword in normalized for keyword in self.CONVERSATION_MERGE_KEYWORDS)

    def _is_low_signal_identifier_token(self, token: str) -> bool:
        """Filter out date/time tokens that are too weak for cross-thread merging."""

        normalized = str(token or "").strip().lower()
        if not normalized:
            return True

        if self.TIME_TOKEN_RE.match(normalized):
            return True

        if normalized.isdigit():
            numeric_value = int(normalized)
            if len(normalized) <= 2:
                return True
            if 1900 <= numeric_value <= 2100:
                return True
            return False

        has_alpha = any(character.isalpha() for character in normalized)
        has_digit = any(character.isdigit() for character in normalized)
        if has_alpha and has_digit:
            if normalized.endswith("am") or normalized.endswith("pm"):
                return True
            return len(normalized) < 4

        return True

    def _merge_confidence_from_score(self, score: int) -> str:
        if score >= 6:
            return "high"
        if score >= 4:
            return "medium"
        return "low"

    def _lowest_merge_confidence(
        self,
        left: str | None,
        right: str | None,
    ) -> str | None:
        ranking = {"low": 0, "medium": 1, "high": 2}
        candidates = [value for value in [left, right] if value in ranking]
        if not candidates:
            return None
        return min(candidates, key=lambda value: ranking[value])

    def _dedupe_strings(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for value in values:
            normalized = str(value or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped

    def _detect_sensitive_markers(self, thread: EmailThread) -> list[str]:
        """Return sensitive markings that should keep the thread out of AI."""

        text = f" {thread.subject.lower()} {thread.combined_thread_text.lower()} "
        markers: list[str] = []
        for label, variants in self.SENSITIVE_MARKERS:
            if any(variant in text for variant in variants):
                markers.append(label)
        return markers

    def _collect_participants(self, emails: list[EmailMessage]) -> list[str]:
        participants: list[str] = []
        seen: set[str] = set()

        for email in emails:
            raw_people = [email.from_address, *self._split_people(email.to_address)]
            for person in raw_people:
                normalized = self._normalize_person(person)
                if not normalized:
                    continue
                key = normalized.lower()
                if key in seen:
                    continue
                seen.add(key)
                participants.append(normalized)

        return participants

    def _split_people(self, value: str) -> list[str]:
        if not value:
            return []
        addresses = getaddresses([value])
        if not addresses:
            return [part.strip() for part in re.split(r"[;,]", value) if part.strip()]

        normalized_people: list[str] = []
        for name, address in addresses:
            person = self._format_person(name, address)
            if person:
                normalized_people.append(person)

        return normalized_people or [
            part.strip() for part in re.split(r"[;,]", value) if part.strip()
        ]

    def _format_person(self, name: str, address: str) -> str:
        cleaned_name = re.sub(r"\s+", " ", (name or "")).strip().strip('"')
        cleaned_address = re.sub(r"\s+", " ", (address or "")).strip().strip('"')
        if cleaned_name and cleaned_address:
            return f"{cleaned_name} <{cleaned_address}>"
        return cleaned_name or cleaned_address

    def _normalize_person(self, value: str) -> str:
        cleaned = re.sub(r"\s+", " ", (value or "")).strip().strip('"')
        return cleaned[: self.PARTICIPANT_LIMIT]

    def _build_combined_thread_text(self, emails: list[EmailMessage]) -> str:
        """Create one readable conversation transcript for thread-level AI review."""

        blocks: list[str] = []
        remaining = self.THREAD_TEXT_LIMIT

        for position, email in enumerate(emails, start=1):
            lines = [
                f"Message {position} of {len(emails)}",
                f"From: {email.from_address or 'Unknown sender'}",
                f"Date: {email.date or 'Unknown date'}",
            ]
            if email.subject:
                lines.append(f"Subject: {email.subject}")
            if email.snippet:
                lines.append(f"Snippet: {email.snippet}")
            if email.body_text:
                lines.append(f"Body: {email.body_text}")

            block = "\n".join(lines).strip()
            if not block:
                continue

            if len(block) + 2 > remaining:
                truncated = block[: max(0, remaining - 22)].rstrip()
                if truncated:
                    blocks.append(f"{truncated}\n[Thread truncated]")
                else:
                    blocks.append("[Thread truncated]")
                break

            blocks.append(block)
            remaining -= len(block) + 2

        return "\n\n".join(blocks)

    def _build_thread_signals(
        self,
        emails: list[EmailMessage],
        participants: list[str],
        subject: str,
    ) -> dict[str, bool]:
        """Compute simple thread-state signals used by scoring and the review UI."""

        latest_email = emails[-1] if emails else None
        latest_text = self._compose_message_text(
            subject=subject,
            subject_line=latest_email.subject if latest_email else "",
            snippet=latest_email.snippet if latest_email else "",
            body=latest_email.body_text if latest_email else "",
        )
        latest_message_from_me = self._is_sent_message(latest_email)
        latest_message_from_external = bool(
            latest_email
            and self._is_external_sender(
                latest_email=latest_email,
                emails=emails,
                participants=participants,
            )
        )
        latest_message_has_question = self._text_has_question(latest_text)
        latest_message_has_action_request = self._text_has_action_request(latest_text)
        resolved_or_closed = self._text_is_resolved_or_closed(
            latest_text,
            has_question=latest_message_has_question,
            has_action_request=latest_message_has_action_request,
        )
        waiting_on_us = (
            latest_message_from_external
            and not resolved_or_closed
            and (latest_message_has_question or latest_message_has_action_request)
        )

        return {
            "latest_message_from_me": latest_message_from_me,
            "latest_message_from_external": latest_message_from_external,
            "latest_message_has_question": latest_message_has_question,
            "latest_message_has_action_request": latest_message_has_action_request,
            "waiting_on_us": waiting_on_us,
            "resolved_or_closed": resolved_or_closed,
        }

    def _compose_message_text(
        self,
        subject: str,
        subject_line: str,
        snippet: str,
        body: str,
    ) -> str:
        return " ".join(
            part.lower()
            for part in [subject, subject_line, snippet, body]
            if part
        )

    def _score_thread(self, thread: EmailThread) -> int:
        """Assign a simple 1-5 relevance score used for debug and tie-breaking."""

        latest_message = thread.messages[-1] if thread.messages else None
        latest_text = self._compose_message_text(
            subject=thread.subject,
            subject_line=latest_message.subject if latest_message else "",
            snippet=latest_message.snippet if latest_message else "",
            body=latest_message.cleaned_body if latest_message else "",
        )
        full_text = f"{thread.subject.lower()} {thread.combined_thread_text.lower()}"
        score = 1

        if any(keyword in full_text for keyword in self.HIGH_VALUE_KEYWORDS):
            score += 1
        if any(keyword in latest_text for keyword in self.URGENT_KEYWORDS):
            score += 2
        if thread.latest_message_has_question:
            score += 1
        if thread.latest_message_has_action_request:
            score += 1
        if thread.waiting_on_us:
            score += 1
        if self._has_external_participants(thread):
            score += 1
        if thread.resolved_or_closed:
            score -= 3

        return max(1, min(score, 5))

    def _classify_thread_bucket(
        self,
        thread: EmailThread,
        score: int,
        filtered_reason: str | None,
    ) -> tuple[str, str]:
        """Place a thread in a simple daily relevance bucket."""

        if filtered_reason:
            return "noise", filtered_reason

        latest_message = thread.messages[-1] if thread.messages else None
        latest_text = self._compose_message_text(
            subject=thread.subject,
            subject_line=latest_message.subject if latest_message else "",
            snippet=latest_message.snippet if latest_message else "",
            body=latest_message.cleaned_body if latest_message else "",
        )
        full_text = f"{thread.subject.lower()} {thread.combined_thread_text.lower()}"
        has_high_value_signal = any(
            keyword in full_text for keyword in self.HIGH_VALUE_KEYWORDS
        )
        latest_is_urgent = any(
            keyword in latest_text for keyword in self.URGENT_KEYWORDS
        )
        latest_needs_follow_up = bool(
            thread.latest_message_has_question or thread.latest_message_has_action_request
        )
        has_external_participants = self._has_external_participants(thread)

        if thread.resolved_or_closed and not thread.waiting_on_us:
            return "noise", "Latest thread state looks resolved or closed."

        if thread.waiting_on_us and (
            latest_is_urgent or has_high_value_signal or thread.message_count >= 2
        ):
            return (
                "must_review",
                "Latest inbound message looks like it needs a reply or action from us.",
            )

        if (
            latest_is_urgent
            and latest_needs_follow_up
            and not thread.latest_message_from_me
        ):
            return "must_review", "Latest thread state looks urgent and active."

        if thread.waiting_on_us:
            return "important", "Latest inbound message likely needs follow-up."

        if has_high_value_signal and (
            latest_needs_follow_up or has_external_participants or score >= 4
        ):
            return (
                "important",
                "Business-value thread with active follow-up signals.",
            )

        if (
            score >= self.settings.ai_relevance_threshold
            or has_high_value_signal
            or latest_needs_follow_up
            or (has_external_participants and thread.message_count >= 2)
        ):
            return "maybe", "Thread may still be useful for AI review."

        return "noise", "Low-signal thread with no current action detected."

    def _filter_reason(self, thread: EmailThread) -> str | None:
        """Return a reason when a thread should be excluded from AI processing."""

        latest_message = thread.messages[-1] if thread.messages else None
        latest_sender = latest_message.sender.lower() if latest_message else ""
        latest_subject = (latest_message.subject or thread.subject).lower()
        full_text = f"{thread.subject.lower()} {thread.combined_thread_text.lower()}"
        latest_text = " ".join(
            [
                latest_subject,
                (latest_message.snippet.lower() if latest_message else ""),
                (latest_message.cleaned_body.lower() if latest_message else ""),
            ]
        )
        has_high_value_signal = any(
            keyword in full_text for keyword in self.HIGH_VALUE_KEYWORDS
        )
        sender_looks_promotional = any(
            marker in latest_sender for marker in self.NEWSLETTER_SENDER_MARKERS
        )
        subject_looks_promotional = any(
            marker in latest_subject for marker in self.NEWSLETTER_SUBJECT_MARKERS
        )

        if has_high_value_signal:
            return None

        if sender_looks_promotional and (
            subject_looks_promotional or "unsubscribe" in full_text
        ):
            return "Filtered as obvious promotional or newsletter mail."

        if subject_looks_promotional and (
            sender_looks_promotional or "unsubscribe" in latest_text
        ):
            return "Filtered as obvious promotional or newsletter mail."

        if "unsubscribe" in full_text and thread.message_count == 1:
            return "Filtered as obvious promotional or newsletter mail."

        return None

    def _has_external_participants(self, thread: EmailThread) -> bool:
        """Treat a thread as external when it includes more than one email domain."""

        return self._has_multiple_participant_domains(thread.participants)

    def _has_multiple_participant_domains(self, participants: list[str]) -> bool:
        domains = {
            domain
            for participant in participants
            if (domain := self._extract_domain(participant))
        }
        return len(domains) > 1

    def _is_sent_message(self, email: EmailMessage | None) -> bool:
        if email is None:
            return False
        return "SENT" in {str(label).upper() for label in email.label_ids}

    def _is_external_sender(
        self,
        latest_email: EmailMessage,
        emails: list[EmailMessage],
        participants: list[str],
    ) -> bool:
        if self._is_sent_message(latest_email):
            return False

        sender_domain = self._extract_domain(latest_email.from_address)
        if not sender_domain:
            return self._has_multiple_participant_domains(participants)

        internal_domains = self._collect_internal_domains(emails)
        if internal_domains:
            return sender_domain not in internal_domains

        other_domains = {
            domain
            for participant in participants
            if (domain := self._extract_domain(participant))
        }
        other_domains.discard(sender_domain)
        return bool(other_domains)

    def _collect_internal_domains(self, emails: list[EmailMessage]) -> set[str]:
        internal_domains: set[str] = set()

        for email in emails:
            if self._is_sent_message(email):
                sender_domain = self._extract_domain(email.from_address)
                if sender_domain:
                    internal_domains.add(sender_domain)
                continue

            for person in self._split_people(email.to_address):
                recipient_domain = self._extract_domain(person)
                if recipient_domain:
                    internal_domains.add(recipient_domain)

        return internal_domains

    def _text_has_question(self, text: str) -> bool:
        return "?" in text or self._text_contains_any(text, self.QUESTION_KEYWORDS)

    def _text_has_action_request(self, text: str) -> bool:
        return self._text_contains_any(text, self.ACTION_KEYWORDS)

    def _text_is_resolved_or_closed(
        self,
        text: str,
        has_question: bool,
        has_action_request: bool,
    ) -> bool:
        if has_question or has_action_request:
            return False
        return self._text_contains_any(text, self.RESOLVED_KEYWORDS)

    def _text_contains_any(self, text: str, phrases: tuple[str, ...]) -> bool:
        normalized = f" {text.lower()} "

        for phrase in phrases:
            candidate = phrase.lower().strip()
            if not candidate:
                continue
            if " " in candidate or "-" in candidate:
                if candidate in normalized:
                    return True
                continue
            if re.search(rf"\b{re.escape(candidate)}\b", normalized):
                return True

        return False

    def _selection_signal_labels(self, thread: EmailThread) -> list[str]:
        labels: list[str] = []
        if thread.waiting_on_us:
            labels.append("waiting on us")
        if thread.latest_message_has_action_request:
            labels.append("latest message asks for action")
        if thread.latest_message_has_question:
            labels.append("latest message asks a question")
        if thread.latest_message_from_external:
            labels.append("latest message is inbound")
        if thread.latest_message_from_me:
            labels.append("latest message is from us")
        if self._has_external_participants(thread):
            labels.append("external participants")
        if thread.resolved_or_closed:
            labels.append("thread looks resolved")
        return labels

    def _selection_reason(self, base_reason: str, thread: EmailThread) -> str:
        labels = self._selection_signal_labels(thread)
        if not labels:
            return base_reason
        return f"{base_reason} Signals: {', '.join(labels[:4])}."

    def _extract_domain(self, value: str) -> str:
        match = re.search(r"@([A-Za-z0-9.-]+)", value or "")
        return match.group(1).lower() if match else ""
