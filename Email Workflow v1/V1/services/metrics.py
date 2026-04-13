"""Metrics and analysis helpers for the Streamlit review UI."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote


REVIEW_SCALE = {"Yes": 1.0, "Partially": 0.5, "No": 0.0}


@dataclass
class ReviewMetrics:
    total_fetched: int
    total_filtered: int
    total_sent_to_ai: int
    total_fallback_used: int
    total_reviewed: int
    total_correct: int
    total_incorrect: int
    total_partial: int
    category_accuracy_pct: float
    urgency_accuracy_pct: float
    summary_usefulness_pct: float


def build_gmail_links(email: dict[str, Any], gmail_user_index: str = "0") -> tuple[str | None, str]:
    """Build direct and fallback Gmail links from stored message data.

    Strategy:
    1. Use thread id when available (best direct open in Gmail).
    2. Else use message id as a best-effort direct deep link.
    3. Always provide search fallback using sender+subject.
    """

    thread_id = (email.get("thread_id") or "").strip()
    message_id = (email.get("id") or "").strip()
    sender = (email.get("from_address") or "").strip()
    subject = (email.get("subject") or "").strip()

    open_url = None
    user_index = quote((gmail_user_index or "0").strip())
    if thread_id:
        open_url = f"https://mail.google.com/mail/u/{user_index}/#all/{quote(thread_id)}"
    elif message_id:
        open_url = f"https://mail.google.com/mail/u/{user_index}/#all/{quote(message_id)}"

    search_parts: list[str] = []
    if sender:
        search_parts.append(f'from:"{sender}"')
    if subject:
        search_parts.append(f'subject:"{subject}"')
    if message_id and not search_parts:
        search_parts.append(message_id)
    search_query = " ".join(search_parts).strip() or "in:anywhere"
    search_url = f"https://mail.google.com/mail/u/{user_index}/#search/{quote(search_query)}"

    return open_url, search_url


def safe_pct(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100.0, 2)


def is_reviewed(review: dict[str, Any]) -> bool:
    return bool((review or {}).get("ai_result_correct"))


def usefulness_value(choice: str | None) -> float | None:
    if choice is None:
        return None
    return REVIEW_SCALE.get(choice)


def normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def compute_top_metrics(
    run_data: dict[str, Any],
    unified_records: list[dict[str, Any]],
    reviews_by_message_id: dict[str, dict[str, Any]],
) -> ReviewMetrics:
    total_fetched = int(run_data.get("email_count", len(run_data.get("emails", []))))
    total_filtered = int(
        run_data.get(
            "filtered_email_count",
            len([r for r in unified_records if not r.get("included_in_ai", False)]),
        )
    )
    total_sent = int(
        run_data.get(
            "ai_email_count",
            len([r for r in unified_records if r.get("included_in_ai", False)]),
        )
    )
    total_fallback_used = len(
        [e for e in run_data.get("errors", []) if e.get("used_fallback")]
    )

    reviewed_records = [
        (record, reviews_by_message_id.get(record["id"], {}))
        for record in unified_records
        if is_reviewed(reviews_by_message_id.get(record["id"], {}))
    ]
    total_reviewed = len(reviewed_records)
    total_correct = len(
        [1 for _, review in reviewed_records if review.get("ai_result_correct") == "Yes"]
    )
    total_incorrect = len(
        [1 for _, review in reviewed_records if review.get("ai_result_correct") == "No"]
    )
    total_partial = len(
        [1 for _, review in reviewed_records if review.get("ai_result_correct") == "Partially"]
    )

    category_pairs = [
        (
            (record.get("predicted_category") or "").strip().lower(),
            (review.get("correct_category") or "").strip().lower(),
        )
        for record, review in reviewed_records
        if review.get("correct_category") and record.get("predicted_category")
    ]
    urgency_pairs = [
        (
            (record.get("predicted_urgency") or "").strip().lower(),
            (review.get("correct_urgency") or "").strip().lower(),
        )
        for record, review in reviewed_records
        if review.get("correct_urgency") and record.get("predicted_urgency")
    ]
    summary_scores = [
        usefulness_value(review.get("summary_useful"))
        for _, review in reviewed_records
        if review.get("summary_useful")
    ]
    summary_scores = [score for score in summary_scores if score is not None]

    category_accuracy = safe_pct(
        sum(1 for predicted, actual in category_pairs if predicted == actual),
        len(category_pairs),
    )
    urgency_accuracy = safe_pct(
        sum(1 for predicted, actual in urgency_pairs if predicted == actual),
        len(urgency_pairs),
    )
    summary_usefulness = safe_pct(sum(summary_scores), len(summary_scores))

    return ReviewMetrics(
        total_fetched=total_fetched,
        total_filtered=total_filtered,
        total_sent_to_ai=total_sent,
        total_fallback_used=total_fallback_used,
        total_reviewed=total_reviewed,
        total_correct=total_correct,
        total_incorrect=total_incorrect,
        total_partial=total_partial,
        category_accuracy_pct=category_accuracy,
        urgency_accuracy_pct=urgency_accuracy,
        summary_usefulness_pct=summary_usefulness,
    )


def apply_record_filters(
    unified_records: list[dict[str, Any]],
    reviews_by_message_id: dict[str, dict[str, Any]],
    review_state: str,
    ai_filter_state: str,
    category_filter: str,
    urgency_filter: str,
    tag_filter: str,
) -> list[dict[str, Any]]:
    """Filter records according to sidebar controls."""

    filtered = []
    for record in unified_records:
        review = reviews_by_message_id.get(record["id"], {})
        ai_result = review.get("ai_result_correct")
        tags = set(review.get("improvement_tags", []) or [])

        if review_state == "Only reviewed" and not is_reviewed(review):
            continue
        if review_state == "Only not reviewed" and is_reviewed(review):
            continue
        if review_state == "Only correct" and ai_result != "Yes":
            continue
        if review_state == "Only incorrect" and ai_result != "No":
            continue
        if review_state == "Only partially correct" and ai_result != "Partially":
            continue
        if ai_filter_state == "Only AI filtered" and record.get("included_in_ai", False):
            continue
        if ai_filter_state == "Only not AI filtered" and not record.get("included_in_ai", False):
            continue
        if category_filter != "All" and (record.get("predicted_category") or "Unknown") != category_filter:
            continue
        if urgency_filter != "All" and (record.get("predicted_urgency") or "Unknown") != urgency_filter:
            continue
        if tag_filter != "All" and tag_filter not in tags:
            continue
        filtered.append(record)
    return filtered


def category_confusion(
    unified_records: list[dict[str, Any]],
    reviews_by_message_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    confusion = Counter()
    for record in unified_records:
        review = reviews_by_message_id.get(record["id"], {})
        predicted = normalize_text(record.get("predicted_category"))
        actual = normalize_text(review.get("correct_category"))
        if not predicted or not actual:
            continue
        if predicted != actual:
            confusion[(record.get("predicted_category"), review.get("correct_category"))] += 1

    return [
        {"predicted": predicted, "human": actual, "count": count}
        for (predicted, actual), count in confusion.most_common()
    ]


def urgency_mismatch_counts(
    unified_records: list[dict[str, Any]],
    reviews_by_message_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    mismatches = Counter()
    for record in unified_records:
        review = reviews_by_message_id.get(record["id"], {})
        predicted = normalize_text(record.get("predicted_urgency"))
        actual = normalize_text(review.get("correct_urgency"))
        if not predicted or not actual:
            continue
        if predicted != actual:
            mismatches[(record.get("predicted_urgency"), review.get("correct_urgency"))] += 1

    return [
        {"predicted": predicted, "human": actual, "count": count}
        for (predicted, actual), count in mismatches.most_common()
    ]


def common_improvement_tags(reviews_by_message_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    counter = Counter()
    for review in reviews_by_message_id.values():
        for tag in review.get("improvement_tags", []) or []:
            counter[tag] += 1
    return [{"tag": tag, "count": count} for tag, count in counter.most_common()]


def records_needing_improvement(
    unified_records: list[dict[str, Any]],
    reviews_by_message_id: dict[str, dict[str, Any]],
    top_n: int = 10,
) -> list[dict[str, Any]]:
    scored: list[tuple[float, dict[str, Any]]] = []
    for record in unified_records:
        review = reviews_by_message_id.get(record["id"], {})
        if not is_reviewed(review):
            continue

        score = 0.0
        correctness = review.get("ai_result_correct")
        if correctness == "No":
            score += 3.0
        elif correctness == "Partially":
            score += 1.5

        for field_name in ("summary_useful", "next_action_useful", "crm_useful"):
            field_score = usefulness_value(review.get(field_name))
            if field_score is None:
                continue
            score += max(0.0, 1.0 - field_score)

        score += 0.25 * len(review.get("improvement_tags", []) or [])

        merged = dict(record)
        merged["improvement_score"] = round(score, 2)
        merged["review"] = review
        scored.append((score, merged))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in scored[:top_n]]


def generate_recommendations(
    unified_records: list[dict[str, Any]],
    reviews_by_message_id: dict[str, dict[str, Any]],
) -> list[str]:
    """Generate simple rule-based recommendations from review patterns."""

    recommendations: list[str] = []
    reviewed = [
        record
        for record in unified_records
        if is_reviewed(reviews_by_message_id.get(record["id"], {}))
    ]

    if not reviewed:
        return ["Review a few emails first to unlock targeted recommendations."]

    cat_confusions = category_confusion(unified_records, reviews_by_message_id)
    urg_confusions = urgency_mismatch_counts(unified_records, reviews_by_message_id)
    common_tags = common_improvement_tags(reviews_by_message_id)

    if sum(item["count"] for item in cat_confusions) >= 2:
        recommendations.append("Improve category definitions and triage prompt examples.")
    if sum(item["count"] for item in urg_confusions) >= 2:
        recommendations.append("Improve urgency rules and add clearer urgency criteria.")

    summary_scores = [
        usefulness_value(review.get("summary_useful"))
        for review in reviews_by_message_id.values()
        if review.get("summary_useful")
    ]
    summary_scores = [score for score in summary_scores if score is not None]
    if summary_scores and (sum(summary_scores) / len(summary_scores)) < 0.7:
        recommendations.append("Improve summary prompt to be more concrete and concise.")

    tag_names = {item["tag"] for item in common_tags[:5]}
    if "email should have been filtered out" in tag_names:
        recommendations.append("Tighten filtering rules for low-value automated emails.")
    if "email should not have been filtered out" in tag_names:
        recommendations.append("Relax filtering rules or lower relevance threshold for edge cases.")
    if "wrong urgency" in tag_names:
        recommendations.append("Add stronger urgency keyword/rule handling in pre-triage scoring.")
    if "wrong category" in tag_names:
        recommendations.append("Add category examples and counter-examples to triage instructions.")
    filtering_votes = [
        review.get("should_have_been_filtered")
        for review in reviews_by_message_id.values()
        if review.get("should_have_been_filtered")
    ]
    if filtering_votes and filtering_votes.count("Yes") >= 2:
        recommendations.append("Increase pre-AI filtering strictness for low-value emails.")
    if filtering_votes and filtering_votes.count("No") >= 2:
        recommendations.append("Loosen filtering rules to avoid dropping useful emails.")

    if not recommendations:
        recommendations.append("Current quality looks stable; continue collecting reviews for trend analysis.")

    return recommendations
