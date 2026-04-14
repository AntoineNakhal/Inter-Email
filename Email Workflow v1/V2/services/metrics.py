"""Metrics and analysis helpers for the Streamlit review UI."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote


REVIEW_SCALE = {"Yes": 1.0, "Partially": 0.5, "No": 0.0}
RELEVANCE_SORT_ORDER = {
    "must_review": 0,
    "important": 1,
    "maybe": 2,
    "noise": 3,
}
URGENCY_SORT_ORDER = {
    "high": 0,
    "medium": 1,
    "low": 2,
}


@dataclass
class ReviewMetrics:
    total_fetched: int
    total_messages: int
    total_not_auto_analyzed: int
    total_ai_covered: int
    total_fresh_analysis: int
    total_cached_reused: int
    total_new_threads: int
    total_changed_threads: int
    total_fallback_used: int
    total_reviewed: int
    total_correct: int
    total_incorrect: int
    total_partial: int
    reviewed_merged_threads: int
    incorrect_merge_count: int
    category_accuracy_pct: float
    urgency_accuracy_pct: float
    summary_usefulness_pct: float
    merge_accuracy_pct: float
    ai_overreach_count: int
    ai_underreach_count: int


def build_gmail_links(
    record: dict[str, Any], gmail_user_index: str = "0"
) -> tuple[str | None, str]:
    """Build direct and fallback Gmail links from stored thread or message data."""

    thread_id = (record.get("thread_id") or "").strip()
    message_id = (record.get("message_id") or "").strip()
    sender = (record.get("from_address") or record.get("sender") or "").strip()
    subject = (record.get("subject") or "").strip()
    participants = record.get("participants") or []

    open_url = None
    user_index = quote((gmail_user_index or "0").strip())
    prefer_message_link = bool(record.get("prefer_message_link"))
    if prefer_message_link and message_id:
        open_url = f"https://mail.google.com/mail/u/{user_index}/#all/{quote(message_id)}"
    elif thread_id:
        open_url = f"https://mail.google.com/mail/u/{user_index}/#all/{quote(thread_id)}"
    elif message_id:
        open_url = f"https://mail.google.com/mail/u/{user_index}/#all/{quote(message_id)}"

    search_parts: list[str] = []
    if sender:
        search_parts.append(f'from:"{sender}"')
    elif isinstance(participants, list):
        for participant in participants[:2]:
            normalized = str(participant or "").strip()
            if normalized:
                search_parts.append(f'"{normalized}"')
    if subject:
        search_parts.append(f'subject:"{subject}"')
    if thread_id and not search_parts:
        search_parts.append(thread_id)
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


def _safe_record_date(record: dict[str, Any]) -> datetime:
    minimum = datetime.min.replace(tzinfo=timezone.utc)
    value = str(record.get("latest_message_date") or "").strip()
    if not value:
        return minimum
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return minimum
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _is_ai_covered(record: dict[str, Any]) -> bool:
    analysis_status = record.get("analysis_status")
    return bool(record.get("included_in_ai", False)) or analysis_status in {
        "fresh",
        "cached",
    }


def sort_records(
    unified_records: list[dict[str, Any]],
    sort_option: str = "Latest first",
) -> list[dict[str, Any]]:
    """Return a sorted copy of records for the review queue."""

    records = list(unified_records)

    if sort_option == "Oldest first":
        records.sort(
            key=lambda record: (
                _safe_record_date(record),
                normalize_text(record.get("subject")),
            )
        )
        return records

    if sort_option == "Priority first":
        records.sort(key=lambda record: _safe_record_date(record), reverse=True)
        records.sort(key=lambda record: _safe_int(record.get("relevance_score")), reverse=True)
        records.sort(
            key=lambda record: URGENCY_SORT_ORDER.get(
                normalize_text(record.get("predicted_urgency")),
                len(URGENCY_SORT_ORDER),
            )
        )
        records.sort(
            key=lambda record: 0 if record.get("predicted_needs_action_today") is True else 1
        )
        records.sort(
            key=lambda record: RELEVANCE_SORT_ORDER.get(
                normalize_text(record.get("relevance_bucket")),
                len(RELEVANCE_SORT_ORDER),
            )
        )
        return records

    if sort_option == "Urgency first":
        records.sort(key=lambda record: _safe_record_date(record), reverse=True)
        records.sort(key=lambda record: _safe_int(record.get("relevance_score")), reverse=True)
        records.sort(
            key=lambda record: URGENCY_SORT_ORDER.get(
                normalize_text(record.get("predicted_urgency")),
                len(URGENCY_SORT_ORDER),
            )
        )
        return records

    if sort_option == "Highest score first":
        records.sort(key=lambda record: _safe_record_date(record), reverse=True)
        records.sort(key=lambda record: _safe_int(record.get("relevance_score")), reverse=True)
        return records

    if sort_option == "Most messages first":
        records.sort(key=lambda record: _safe_record_date(record), reverse=True)
        records.sort(key=lambda record: _safe_int(record.get("message_count")), reverse=True)
        return records

    if sort_option == "Subject A-Z":
        records.sort(
            key=lambda record: (
                normalize_text(record.get("subject")),
                -_safe_int(record.get("relevance_score")),
            )
        )
        return records

    records.sort(
        key=lambda record: (
            _safe_record_date(record),
            _safe_int(record.get("relevance_score")),
        ),
        reverse=True,
    )
    return records


def compute_top_metrics(
    run_data: dict[str, Any],
    unified_records: list[dict[str, Any]],
    reviews_by_message_id: dict[str, dict[str, Any]],
) -> ReviewMetrics:
    total_fetched = int(
        run_data.get(
            "thread_count",
            run_data.get("email_count", len(unified_records)),
        )
    )
    total_messages = int(
        run_data.get(
            "message_count",
            len(run_data.get("emails", []))
            or sum(int(record.get("message_count", 0)) for record in unified_records),
        )
    )
    total_not_auto_analyzed = int(
        run_data.get(
            "filtered_thread_count",
            run_data.get(
                "filtered_email_count",
                len([r for r in unified_records if not r.get("included_in_ai", False)]),
            ),
        )
    )
    total_ai_covered = int(
        run_data.get(
            "ai_thread_count",
            run_data.get(
                "ai_email_count",
                len([r for r in unified_records if _is_ai_covered(r)]),
            ),
        )
    )
    total_fresh_analysis = int(
        run_data.get(
            "fresh_ai_thread_count",
            len([r for r in unified_records if r.get("analysis_status") == "fresh"]),
        )
    )
    total_cached_reused = int(
        run_data.get(
            "cached_ai_thread_count",
            len([r for r in unified_records if r.get("analysis_status") == "cached"]),
        )
    )
    total_new_threads = int(
        run_data.get(
            "new_thread_count",
            len([r for r in unified_records if r.get("change_status") == "new"]),
        )
    )
    total_changed_threads = int(
        run_data.get(
            "changed_thread_count",
            len([r for r in unified_records if r.get("change_status") == "changed"]),
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
    merge_reviewed_records = [
        (record, reviews_by_message_id.get(record["id"], {}))
        for record in unified_records
        if reviews_by_message_id.get(record["id"], {}).get("merge_correct") in {"Yes", "No"}
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
    reviewed_merged_threads = len(
        [
            1
            for record, _ in merge_reviewed_records
            if len(record.get("source_thread_ids", [])) > 1
        ]
    )
    incorrect_merge_count = len(
        [
            1
            for record, review in merge_reviewed_records
            if len(record.get("source_thread_ids", [])) > 1
            and review.get("merge_correct") == "No"
        ]
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
    merge_accuracy = safe_pct(
        reviewed_merged_threads - incorrect_merge_count,
        reviewed_merged_threads,
    )
    ai_overreach_count = len(
        [
            1
            for record, review in reviewed_records
            if _is_ai_covered(record)
            and review.get("should_have_been_filtered") == "Yes"
        ]
    )
    ai_underreach_count = len(
        [
            1
            for record, review in reviewed_records
            if not _is_ai_covered(record)
            and review.get("should_have_been_filtered") == "No"
        ]
    )

    return ReviewMetrics(
        total_fetched=total_fetched,
        total_messages=total_messages,
        total_not_auto_analyzed=total_not_auto_analyzed,
        total_ai_covered=total_ai_covered,
        total_fresh_analysis=total_fresh_analysis,
        total_cached_reused=total_cached_reused,
        total_new_threads=total_new_threads,
        total_changed_threads=total_changed_threads,
        total_fallback_used=total_fallback_used,
        total_reviewed=total_reviewed,
        total_correct=total_correct,
        total_incorrect=total_incorrect,
        total_partial=total_partial,
        reviewed_merged_threads=reviewed_merged_threads,
        incorrect_merge_count=incorrect_merge_count,
        category_accuracy_pct=category_accuracy,
        urgency_accuracy_pct=urgency_accuracy,
        summary_usefulness_pct=summary_usefulness,
        merge_accuracy_pct=merge_accuracy,
        ai_overreach_count=ai_overreach_count,
        ai_underreach_count=ai_underreach_count,
    )


def apply_record_filters(
    unified_records: list[dict[str, Any]],
    reviews_by_message_id: dict[str, dict[str, Any]],
    review_state: str,
    ai_filter_state: str,
    category_filter: str,
    urgency_filter: str,
    tag_filter: str,
    relevance_filter: str = "All",
    change_filter: str = "All",
    security_filter: str = "All",
    ai_decision_filter: str = "All",
) -> list[dict[str, Any]]:
    """Filter records according to sidebar controls."""

    filtered = []
    for record in unified_records:
        review = reviews_by_message_id.get(record["id"], {})
        ai_result = review.get("ai_result_correct")
        tags = set(review.get("improvement_tags", []) or [])
        analysis_status = record.get("analysis_status")
        security_status = record.get("security_status") or "standard"
        ai_covered = _is_ai_covered(record)

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
        if ai_filter_state == "Only AI-covered" and not ai_covered:
            continue
        if ai_filter_state == "Only not auto-analyzed" and ai_covered:
            continue
        if ai_filter_state == "Only cached" and analysis_status != "cached":
            continue
        if ai_filter_state == "Only fresh this run" and analysis_status != "fresh":
            continue
        if category_filter != "All" and (record.get("predicted_category") or "Unknown") != category_filter:
            continue
        if urgency_filter != "All" and (record.get("predicted_urgency") or "Unknown") != urgency_filter:
            continue
        if relevance_filter != "All" and (record.get("relevance_bucket") or "Unknown") != relevance_filter:
            continue
        if change_filter != "All" and (record.get("change_status") or "Unknown") != change_filter:
            continue
        if security_filter == "Only classified / sensitive" and security_status != "classified":
            continue
        if security_filter == "Only standard" and security_status == "classified":
            continue
        if ai_decision_filter != "All" and (record.get("ai_decision") or "Unknown") != ai_decision_filter:
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


def build_failure_patterns(
    unified_records: list[dict[str, Any]],
    reviews_by_message_id: dict[str, dict[str, Any]],
) -> list[str]:
    """Summarize the most actionable failure themes from manual review data."""

    patterns: list[str] = []
    reviewed_records = [
        (record, reviews_by_message_id.get(record["id"], {}))
        for record in unified_records
        if is_reviewed(reviews_by_message_id.get(record["id"], {}))
    ]
    merge_reviewed_records = [
        (record, reviews_by_message_id.get(record["id"], {}))
        for record in unified_records
        if reviews_by_message_id.get(record["id"], {}).get("merge_correct") in {"Yes", "No"}
    ]
    if not reviewed_records and not merge_reviewed_records:
        return ["No review patterns yet. Review a few threads to unlock targeted feedback."]

    incorrect_merges = [
        record
        for record, review in merge_reviewed_records
        if len(record.get("source_thread_ids", [])) > 1
        and review.get("merge_correct") == "No"
    ]
    if incorrect_merges:
        patterns.append(
            f"{len(incorrect_merges)} merged thread(s) were marked incorrect. Tighten subject-merge rules before expanding them."
        )

    ai_overreach = [
        record
        for record, review in reviewed_records
        if _is_ai_covered(record) and review.get("should_have_been_filtered") == "Yes"
    ]
    if ai_overreach:
        patterns.append(
            f"{len(ai_overreach)} AI-covered thread(s) looked low-value in review. Filtering and AI-eligibility rules are still too loose."
        )

    ai_underreach = [
        record
        for record, review in reviewed_records
        if not _is_ai_covered(record) and review.get("should_have_been_filtered") == "No"
    ]
    if ai_underreach:
        patterns.append(
            f"{len(ai_underreach)} visible thread(s) were judged worth AI coverage. Scoring is still missing some useful work."
        )

    common_tags = common_improvement_tags(reviews_by_message_id)
    if common_tags:
        top_tag = common_tags[0]
        if top_tag["count"] >= 2:
            patterns.append(
                f"Most repeated review tag: {top_tag['tag']} ({top_tag['count']}x). This is the clearest short-term improvement target."
            )

    category_mismatches = sum(item["count"] for item in category_confusion(unified_records, reviews_by_message_id))
    if category_mismatches >= 2:
        patterns.append(
            "Category drift is recurring across reviewed threads. Prompt examples or post-rules need tightening."
        )

    urgency_mismatches = sum(item["count"] for item in urgency_mismatch_counts(unified_records, reviews_by_message_id))
    if urgency_mismatches >= 2:
        patterns.append(
            "Urgency is drifting from reviewer expectations. The latest thread state is not being weighted strongly enough."
        )

    return patterns or ["No dominant failure pattern yet. Keep collecting reviewed threads."]


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
        return ["Review a few threads first to unlock targeted recommendations."]

    cat_confusions = category_confusion(unified_records, reviews_by_message_id)
    urg_confusions = urgency_mismatch_counts(unified_records, reviews_by_message_id)
    common_tags = common_improvement_tags(reviews_by_message_id)

    if sum(item["count"] for item in cat_confusions) >= 2:
        recommendations.append("Improve category definitions and thread triage prompt examples.")
    if sum(item["count"] for item in urg_confusions) >= 2:
        recommendations.append("Improve urgency rules and add clearer thread urgency criteria.")

    summary_scores = [
        usefulness_value(review.get("summary_useful"))
        for review in reviews_by_message_id.values()
        if review.get("summary_useful")
    ]
    summary_scores = [score for score in summary_scores if score is not None]
    if summary_scores and (sum(summary_scores) / len(summary_scores)) < 0.7:
        recommendations.append("Improve the thread summary prompt so it is more concrete and concise.")

    tag_names = {item["tag"] for item in common_tags[:5]}
    if "email should have been filtered out" in tag_names:
        recommendations.append("Tighten filtering rules for low-value automated threads.")
    if "email should not have been filtered out" in tag_names:
        recommendations.append("Relax filtering rules or lower relevance threshold for edge-case threads.")
    if "merge incorrect" in tag_names:
        recommendations.append("Tighten cross-thread merge rules and inspect subject-only merge cases first.")
    if "thread should have been merged" in tag_names:
        recommendations.append("Expand merge rules only in patterns already confirmed by reviewer feedback.")
    if "AI should have covered this" in tag_names:
        recommendations.append("Raise recall for useful threads by promoting similar maybe threads into AI coverage.")
    if "AI should not have covered this" in tag_names:
        recommendations.append("Reduce AI overreach by tightening low-value coverage rules.")
    if "wrong urgency" in tag_names:
        recommendations.append("Add stronger urgency rules that weigh the latest thread state more heavily.")
    if "wrong category" in tag_names:
        recommendations.append("Add thread-level category examples and counter-examples to triage instructions.")
    filtering_votes = [
        review.get("should_have_been_filtered")
        for review in reviews_by_message_id.values()
        if review.get("should_have_been_filtered")
    ]
    if filtering_votes and filtering_votes.count("Yes") >= 2:
        recommendations.append("Increase pre-AI filtering strictness for low-value threads.")
    if filtering_votes and filtering_votes.count("No") >= 2:
        recommendations.append("Loosen filtering rules to avoid dropping useful conversation threads.")

    if not recommendations:
        recommendations.append("Current quality looks stable; continue collecting thread reviews for trend analysis.")

    return recommendations
