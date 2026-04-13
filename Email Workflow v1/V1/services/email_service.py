"""Application service for retrieving, filtering, and scoring emails."""

from __future__ import annotations

import re

from config import Settings
from gmail_client import GmailReadonlyClient
from schemas import AgentEmail, EmailMessage, EmailSelection


class EmailService:
    """Keeps Gmail fetching separate from agent orchestration."""

    SUBJECT_LIMIT = 200
    SENDER_LIMIT = 200
    SNIPPET_LIMIT = 500
    BODY_LIMIT = 1000
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
    LOW_VALUE_LABELS = {
        "CATEGORY_PROMOTIONS",
        "CATEGORY_SOCIAL",
        "CATEGORY_FORUMS",
        "SPAM",
    }
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
    )

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = GmailReadonlyClient(
            credentials_path=settings.credentials_path,
            token_path=settings.token_path,
        )

    def fetch_recent_emails(self, max_results: int) -> list[EmailMessage]:
        """Fetch emails, trim noisy content, and validate the result."""

        safe_max_results = max(1, max_results)
        raw_messages = self.client.list_recent_messages(max_results=safe_max_results)
        sanitized_messages = [self._sanitize_email(message) for message in raw_messages]
        return [EmailMessage.model_validate(message) for message in sanitized_messages]

    def select_emails_for_ai(
        self, emails: list[EmailMessage]
    ) -> tuple[list[AgentEmail], list[EmailSelection]]:
        """Filter and score emails before sending them to the AI pipeline."""

        candidates: list[tuple[int, AgentEmail]] = []
        selection_log: list[EmailSelection] = []

        for index, email in enumerate(emails):
            score = self._score_email(email)
            filtered_reason = self._filter_reason(email)
            agent_email = AgentEmail(
                id=email.id,
                subject=self._clean_text(email.subject, self.SUBJECT_LIMIT),
                sender=self._clean_text(email.from_address, self.SENDER_LIMIT),
                snippet=self._clean_text(email.snippet, self.SNIPPET_LIMIT),
                body=self._clean_text(email.body_text, self.BODY_LIMIT),
                relevance_score=score,
            )

            if filtered_reason:
                selection_log.append(
                    EmailSelection(
                        message_id=email.id,
                        subject=agent_email.subject,
                        sender=agent_email.sender,
                        relevance_score=score,
                        included_in_ai=False,
                        reason=filtered_reason,
                    )
                )
                continue

            if score < self.settings.ai_relevance_threshold:
                selection_log.append(
                    EmailSelection(
                        message_id=email.id,
                        subject=agent_email.subject,
                        sender=agent_email.sender,
                        relevance_score=score,
                        included_in_ai=False,
                        reason=(
                            f"Relevance score {score} is below the threshold "
                            f"{self.settings.ai_relevance_threshold}."
                        ),
                    )
                )
                continue

            candidates.append((index, agent_email))

        top_candidates = sorted(
            candidates,
            key=lambda item: (-item[1].relevance_score, item[0]),
        )[: self.settings.ai_max_emails]
        selected_ids = {email.id for _, email in top_candidates}
        selected_emails = [
            email for _, email in sorted(top_candidates, key=lambda item: item[0])
        ]
        logged_ids = {entry.message_id for entry in selection_log}

        for _, email in candidates:
            if email.id in selected_ids:
                selection_log.append(
                    EmailSelection(
                        message_id=email.id,
                        subject=email.subject,
                        sender=email.sender,
                        relevance_score=email.relevance_score,
                        included_in_ai=True,
                        reason="Passed filtering and relevance scoring.",
                    )
                )
            elif email.id not in logged_ids:
                selection_log.append(
                    EmailSelection(
                        message_id=email.id,
                        subject=email.subject,
                        sender=email.sender,
                        relevance_score=email.relevance_score,
                        included_in_ai=False,
                        reason=(
                            f"Skipped because only the top {self.settings.ai_max_emails} "
                            "emails are sent to AI."
                        ),
                    )
                )

        return selected_emails, selection_log

    def _sanitize_email(
        self, message: dict[str, str | list[str]]
    ) -> dict[str, str | list[str]]:
        """Normalize and trim Gmail message data before it touches the agents."""

        return {
            "id": message.get("id", ""),
            "thread_id": message.get("thread_id", ""),
            "subject": self._clean_text(message.get("subject", ""), self.SUBJECT_LIMIT),
            "from_address": self._clean_text(
                message.get("from_address", ""), self.SENDER_LIMIT
            ),
            "to_address": self._clean_text(
                message.get("to_address", ""), self.SENDER_LIMIT
            ),
            "date": self._clean_text(message.get("date", ""), self.SENDER_LIMIT),
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

    def _score_email(self, email: EmailMessage) -> int:
        """Assign a simple 1-5 relevance score before AI usage."""

        text = " ".join(
            [
                email.subject.lower(),
                email.snippet.lower(),
                email.body_text.lower(),
            ]
        )
        score = 1

        if any(keyword in text for keyword in self.HIGH_VALUE_KEYWORDS):
            score += 1
        if any(keyword in text for keyword in self.URGENT_KEYWORDS):
            score += 2
        if any(keyword in text for keyword in self.ACTION_KEYWORDS):
            score += 1
        if self._is_external_sender(email):
            score += 1

        return max(1, min(score, 5))

    def _filter_reason(self, email: EmailMessage) -> str | None:
        """Return a reason when an email should be excluded from AI processing."""

        sender = email.from_address.lower()
        subject = email.subject.lower()
        text = f"{subject} {email.snippet.lower()} {email.body_text.lower()}"
        has_high_value_signal = any(
            keyword in text for keyword in self.HIGH_VALUE_KEYWORDS
        )
        sender_looks_promotional = any(
            marker in sender for marker in self.NEWSLETTER_SENDER_MARKERS
        )
        subject_looks_promotional = any(
            marker in subject for marker in self.NEWSLETTER_SUBJECT_MARKERS
        )
        has_low_value_label = any(label in self.LOW_VALUE_LABELS for label in email.label_ids)

        if has_high_value_signal:
            return None

        if has_low_value_label:
            return "Filtered as obvious promotional or social mail by Gmail label."

        if sender_looks_promotional and (
            subject_looks_promotional or "unsubscribe" in text
        ):
            return "Filtered as obvious promotional or newsletter mail."

        if subject_looks_promotional and ("unsubscribe" in text or sender_looks_promotional):
            return "Filtered as obvious promotional or newsletter mail."

        return None

    def _is_external_sender(self, email: EmailMessage) -> bool:
        """Treat emails from a different domain than the recipient as external."""

        sender_domain = self._extract_domain(email.from_address)
        recipient_domain = self._extract_domain(email.to_address)
        return bool(
            sender_domain
            and recipient_domain
            and sender_domain != recipient_domain
        )

    def _extract_domain(self, value: str) -> str:
        match = re.search(r"@([A-Za-z0-9.-]+)", value or "")
        return match.group(1).lower() if match else ""
