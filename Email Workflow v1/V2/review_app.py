"""Local Streamlit review UI for Gmail thread triage output quality checks."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import defaultdict
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from datetime import datetime, timezone

import streamlit as st

from services.metrics import (
    apply_record_filters,
    build_gmail_links,
    category_confusion,
    common_improvement_tags,
    compute_top_metrics,
    generate_recommendations,
    records_needing_improvement,
    normalize_text,
    urgency_mismatch_counts,
)
from services.review_store import (
    DEFAULT_ACCOUNT_OUTPUT_PATH,
    DEFAULT_REVIEW_OUTPUT_PATH,
    load_gmail_accounts,
    load_review_results,
    normalize_review_payload,
    save_gmail_accounts,
    save_review_results,
    upsert_gmail_account,
    upsert_review_result,
)


CATEGORY_OPTIONS = [
    "Urgent / Executive",
    "Customer / Partner",
    "Events / Logistics",
    "Finance / Admin",
    "FYI / Low Priority",
]
URGENCY_OPTIONS = ["Low", "Medium", "High"]
REVIEW_OPTIONS = ["Yes", "No", "Partially"]
CRM_OPTIONS = ["Yes", "No", "Partially", "Not applicable"]
FILTER_NEEDED_OPTIONS = ["N/A", "Yes", "No"]
IMPROVEMENT_TAG_OPTIONS = [
    "wrong category",
    "wrong urgency",
    "summary too vague",
    "summary too long",
    "next action weak",
    "CRM extraction incomplete",
    "email should have been filtered out",
    "email should not have been filtered out",
    "other",
]
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

PROJECT_ROOT = Path(__file__).resolve().parent
BACKEND_RUN_LOG = PROJECT_ROOT / "data" / "outputs" / "backend_run.log"


def _safe_file_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value)
    return cleaned.strip("._") or "gmail_account"


def _launch_backend_pipeline(
    token_path: str | None = None,
    thread_source: str = "anywhere",
) -> tuple[subprocess.Popen[str] | None, str]:
    """Start the local backend app.py in the background."""

    project_app = PROJECT_ROOT / "app.py"
    if not project_app.exists():
        return None, f"Could not find backend app: {project_app}"

    env = os.environ.copy()
    if token_path:
        env["GMAIL_TOKEN_FILE"] = token_path
    env["GMAIL_THREAD_SOURCE"] = thread_source

    BACKEND_RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(BACKEND_RUN_LOG, "a", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [sys.executable, str(project_app)],
            cwd=str(PROJECT_ROOT),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=env,
        )
    return (
        process,
        f"Started backend pipeline process (pid={process.pid}, source={thread_source}).",
    )


def render_skeleton_cards(count: int = 3) -> None:
    """Render simple loading placeholders while data is being prepared."""

    st.markdown(
        """
        <style>
        .skeleton-card {
            border: 1px solid rgba(49, 51, 63, 0.12);
            border-radius: 14px;
            padding: 1rem;
            margin-bottom: 0.9rem;
            background: linear-gradient(90deg, rgba(128,128,128,0.08) 25%, rgba(128,128,128,0.16) 37%, rgba(128,128,128,0.08) 63%);
            background-size: 400% 100%;
            animation: shimmer 1.2s ease-in-out infinite;
        }
        .skeleton-line {
            height: 12px;
            border-radius: 999px;
            background: rgba(128,128,128,0.18);
            margin: 0.45rem 0;
        }
        .skeleton-line.short { width: 35%; }
        .skeleton-line.medium { width: 60%; }
        .skeleton-line.long { width: 90%; }
        @keyframes shimmer {
            0% { background-position: 100% 0; }
            100% { background-position: 0 0; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    for _ in range(count):
        st.markdown(
            """
            <div class="skeleton-card">
                <div class="skeleton-line long"></div>
                <div class="skeleton-line medium"></div>
                <div class="skeleton-line short"></div>
                <div class="skeleton-line long"></div>
            </div>
            """,
            unsafe_allow_html=True,
        )


@st.fragment(run_every="2s")
def render_loading_queue() -> None:
    """Poll the background backend process and keep the queue area feeling live."""

    backend_process = st.session_state.get("backend_process")
    if backend_process is None:
        return

    process_state = backend_process.poll()
    if process_state is None:
        st.info(
            "Backend pipeline is fetching and rebuilding the thread list. "
            "This queue refreshes automatically every 2 seconds."
        )
        render_skeleton_cards(4)
        return

    st.session_state["backend_process"] = None
    st.session_state["last_backend_exit_code"] = process_state
    st.rerun()


def build_page_tokens(total_pages: int, current_page: int) -> list[int | str]:
    """Return a compact, stable page list.

    Examples:
    1 2 3 4 ... 20
    1 ... 3 4 5 ... 20
    1 ... 17 18 19 20
    """

    if total_pages <= 5:
        return list(range(1, total_pages + 1))

    # Near the start
    if current_page <= 3:
        return [1, 2, 3, 4, "...", total_pages]

    # Near the end
    if current_page >= total_pages - 2:
        return [1, "...", total_pages - 3, total_pages - 2, total_pages - 1, total_pages]

    # Middle
    return [1, "...", current_page - 1, current_page, current_page + 1, "...", total_pages]


def reset_review_page() -> None:
    """Jump back to the first page when page size changes."""

    st.session_state["review_page"] = 1


def render_review_pagination(
    current_page: int,
    total_pages: int,
    key_prefix: str,
) -> None:
    """Render a compact centered pagination bar."""

    tokens = ["<"] + build_page_tokens(total_pages, current_page) + [">"]
    outer_left, outer_center, outer_right = st.columns([2, 5, 2])

    with outer_center:
        nav_cols = st.columns(len(tokens))
        for index, token in enumerate(tokens):
            with nav_cols[index]:
                if token == "...":
                    st.markdown(
                        "<div style='text-align:center;padding-top:0.35rem;'>...</div>",
                        unsafe_allow_html=True,
                    )
                    continue

                if token == "<":
                    if st.button(
                        "<",
                        key=f"{key_prefix}_prev",
                        use_container_width=True,
                        disabled=current_page <= 1,
                    ):
                        st.session_state["review_page"] = current_page - 1
                        st.rerun()
                    continue

                if token == ">":
                    if st.button(
                        ">",
                        key=f"{key_prefix}_next",
                        use_container_width=True,
                        disabled=current_page >= total_pages,
                    ):
                        st.session_state["review_page"] = current_page + 1
                        st.rerun()
                    continue

                page_num = int(token)
                is_current = page_num == current_page
                if st.button(
                    str(page_num),
                    key=f"{key_prefix}_page_{page_num}",
                    use_container_width=True,
                    type="primary" if is_current else "secondary",
                    disabled=is_current,
                ):
                    st.session_state["review_page"] = page_num
                    st.rerun()


def _connect_gmail_account(credentials_path: Path, token_dir: Path) -> dict[str, Any]:
    """Run the Gmail OAuth flow and store the connected account locally.

    This is intentionally simple: the user clicks one button, signs in once,
    and we persist the token plus account metadata for later switching.
    """

    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    if not credentials_path.exists():
        raise FileNotFoundError(
            f"Missing Gmail OAuth credentials file: {credentials_path}"
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), GMAIL_SCOPES)
    creds = flow.run_local_server(port=0)
    service = build("gmail", "v1", credentials=creds)
    profile = service.users().getProfile(userId="me").execute()

    email_address = str(profile.get("emailAddress", "")).strip() or "gmail-account"
    token_dir.mkdir(parents=True, exist_ok=True)
    token_path = token_dir / f"{_safe_file_name(email_address)}.json"
    token_path.write_text(creds.to_json(), encoding="utf-8")

    return {
        "name": email_address,
        "email_address": email_address,
        "gmail_user_index": "0",
        "token_path": str(token_path),
        "connected_at": datetime.now(timezone.utc).isoformat(),
    }


def load_pipeline_output(path: str | Path) -> dict[str, Any]:
    output_path = Path(path)
    if not output_path.exists():
        return {}
    try:
        return json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _safe_email_date(value: str) -> datetime:
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


def format_selection_signals(record: dict[str, Any]) -> str:
    labels: list[str] = []

    if record.get("waiting_on_us"):
        labels.append("waiting on us")
    if record.get("latest_message_has_action_request"):
        labels.append("latest message asks for action")
    if record.get("latest_message_has_question"):
        labels.append("latest message asks a question")
    if record.get("latest_message_from_external"):
        labels.append("latest message is inbound")
    if record.get("latest_message_from_me"):
        labels.append("latest message is from us")
    if record.get("resolved_or_closed"):
        labels.append("thread looks resolved")

    return ", ".join(labels) if labels else "No strong thread-state signals detected."


def format_record_badges(record: dict[str, Any]) -> str:
    labels: list[str] = []

    change_status = str(record.get("change_status") or "").strip().lower()
    analysis_status = str(record.get("analysis_status") or "").strip().lower()
    relevance_bucket = str(record.get("relevance_bucket") or "").strip().lower()

    if change_status == "new":
        labels.append("New")
    elif change_status == "changed":
        labels.append("Changed")
    elif change_status == "unchanged":
        labels.append("Unchanged")

    if analysis_status == "fresh":
        labels.append("Analyzed this run")
    elif analysis_status == "cached":
        labels.append("Cached")
    elif analysis_status == "not_requested":
        labels.append("Not auto-analyzed")
    elif analysis_status == "skipped":
        labels.append("Skipped as noise")

    if relevance_bucket == "must_review":
        labels.append("Must review")
    elif relevance_bucket == "important":
        labels.append("Important")
    elif relevance_bucket == "maybe":
        labels.append("Maybe")
    elif relevance_bucket == "noise":
        labels.append("Noise")

    return " | ".join(labels) if labels else "No status badges available."


def _normalize_v2_thread_records(run_data: dict[str, Any]) -> list[dict[str, Any]]:
    global_next_actions = run_data.get("summary", {}).get("next_actions", [])
    unified_records: list[dict[str, Any]] = []

    for thread in run_data.get("threads", []):
        messages = thread.get("messages", [])
        latest_message = messages[-1] if messages else {}
        participants = thread.get("participants", [])

        unified_records.append(
            {
                "id": thread.get("thread_id", ""),
                "thread_id": thread.get("thread_id", ""),
                "subject": thread.get("subject", ""),
                "source_thread_ids": thread.get("source_thread_ids", []),
                "grouping_reason": thread.get("grouping_reason", "gmail_thread_id"),
                "participants": participants,
                "participants_display": ", ".join(participants) or "Unknown participants",
                "message_count": thread.get("message_count", len(messages)),
                "latest_message_date": thread.get("latest_message_date", ""),
                "latest_message_sender": latest_message.get("sender", ""),
                "latest_message_preview": (
                    latest_message.get("snippet") or latest_message.get("cleaned_body") or ""
                )[:220],
                "messages": messages,
                "combined_thread_text": thread.get("combined_thread_text", ""),
                "latest_message_from_me": bool(thread.get("latest_message_from_me", False)),
                "latest_message_from_external": bool(
                    thread.get("latest_message_from_external", False)
                ),
                "latest_message_has_question": bool(
                    thread.get("latest_message_has_question", False)
                ),
                "latest_message_has_action_request": bool(
                    thread.get("latest_message_has_action_request", False)
                ),
                "waiting_on_us": bool(thread.get("waiting_on_us", False)),
                "resolved_or_closed": bool(thread.get("resolved_or_closed", False)),
                "included_in_ai": bool(thread.get("included_in_ai", False)),
                "relevance_bucket": thread.get("relevance_bucket")
                or thread.get("selection_bucket"),
                "change_status": thread.get("change_status"),
                "analysis_status": thread.get("analysis_status"),
                "last_analysis_at": thread.get("last_analysis_at"),
                "selection_reason": thread.get("selection_reason", "No selection info available."),
                "relevance_score": thread.get("relevance_score"),
                "predicted_category": thread.get("predicted_category"),
                "predicted_urgency": thread.get("predicted_urgency"),
                "predicted_summary": thread.get("predicted_summary"),
                "predicted_status": thread.get("predicted_status"),
                "predicted_needs_action_today": thread.get("predicted_needs_action_today"),
                "predicted_next_action": thread.get("predicted_next_action"),
                "global_next_actions": global_next_actions,
                "crm_contact_name": thread.get("crm_contact_name"),
                "crm_company": thread.get("crm_company"),
                "crm_opportunity_type": thread.get("crm_opportunity_type"),
                "crm_urgency": thread.get("crm_urgency"),
            }
        )

    return unified_records


def _build_legacy_thread_records(run_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Build thread cards from old V1 output so the copied sample data still loads."""

    triage_map = {
        item.get("message_id"): item
        for item in run_data.get("triage", [])
        if item.get("message_id")
    }
    crm_map = {
        item.get("message_id"): item
        for item in run_data.get("crm_records", [])
        if item.get("message_id")
    }
    selection_map = {
        item.get("message_id"): item
        for item in run_data.get("email_selection", [])
        if item.get("message_id")
    }
    global_next_actions = run_data.get("summary", {}).get("next_actions", [])

    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "thread_id": "",
            "participants": [],
            "messages": [],
            "selection_reasons": [],
            "scores": [],
            "included_in_ai": False,
            "latest_triage": {},
            "latest_crm": {},
            "selection_reason": "No selection info available.",
        }
    )

    for index, email in enumerate(run_data.get("emails", [])):
        thread_id = email.get("thread_id") or email.get("id", "")
        grouped_thread = grouped[thread_id]
        grouped_thread["thread_id"] = thread_id
        grouped_thread["messages"].append(
            {
                "message_id": email.get("id", ""),
                "sender": email.get("from_address", ""),
                "subject": email.get("subject", ""),
                "date": email.get("date", ""),
                "snippet": email.get("snippet", ""),
                "cleaned_body": email.get("body_text", ""),
                "_sort_index": index,
            }
        )

        participants = grouped_thread["participants"]
        for participant in [email.get("from_address", ""), *str(email.get("to_address", "")).split(",")]:
            normalized = str(participant or "").strip().strip('"')
            if normalized and normalized not in participants:
                participants.append(normalized)

        selection = selection_map.get(email.get("id", ""), {})
        if selection:
            grouped_thread["selection_reason"] = selection.get(
                "reason", grouped_thread["selection_reason"]
            )
            grouped_thread["included_in_ai"] = grouped_thread["included_in_ai"] or bool(
                selection.get("included_in_ai", False)
            )
            if selection.get("relevance_score") is not None:
                grouped_thread["scores"].append(selection.get("relevance_score"))

        triage = triage_map.get(email.get("id", ""), {})
        if triage:
            grouped_thread["latest_triage"] = triage

        crm = crm_map.get(email.get("id", ""), {})
        if crm:
            grouped_thread["latest_crm"] = crm

    unified_records: list[dict[str, Any]] = []
    for thread in grouped.values():
        ordered_messages = sorted(
            thread["messages"],
            key=lambda item: (_safe_email_date(item.get("date", "")), item["_sort_index"]),
        )
        for item in ordered_messages:
            item.pop("_sort_index", None)

        latest_message = ordered_messages[-1] if ordered_messages else {}
        latest_triage = thread["latest_triage"]
        latest_crm = thread["latest_crm"]
        subject = next(
            (
                message.get("subject")
                for message in reversed(ordered_messages)
                if message.get("subject")
            ),
            "(No subject)",
        )
        combined_thread_text = "\n\n".join(
            (
                "\n".join(
                    [
                        f"From: {message.get('sender') or 'Unknown sender'}",
                        f"Date: {message.get('date') or 'Unknown date'}",
                        f"Subject: {message.get('subject') or '(No subject)'}",
                        f"Snippet: {message.get('snippet') or ''}",
                        f"Body: {message.get('cleaned_body') or ''}",
                    ]
                ).strip()
            )
            for message in ordered_messages
        )[:5000]

        unified_records.append(
            {
                "id": thread["thread_id"],
                "thread_id": thread["thread_id"],
                "subject": subject,
                "participants": thread["participants"],
                "participants_display": ", ".join(thread["participants"]) or "Unknown participants",
                "message_count": len(ordered_messages),
                "latest_message_date": latest_message.get("date", ""),
                "latest_message_sender": latest_message.get("sender", ""),
                "latest_message_preview": (
                    latest_message.get("snippet") or latest_message.get("cleaned_body") or ""
                )[:220],
                "messages": ordered_messages,
                "combined_thread_text": combined_thread_text,
                "latest_message_from_me": False,
                "latest_message_from_external": False,
                "latest_message_has_question": False,
                "latest_message_has_action_request": False,
                "waiting_on_us": False,
                "resolved_or_closed": False,
                "included_in_ai": bool(thread["included_in_ai"]),
                "relevance_bucket": None,
                "change_status": None,
                "analysis_status": "fresh" if thread["included_in_ai"] else "not_requested",
                "last_analysis_at": None,
                "selection_reason": thread["selection_reason"],
                "relevance_score": max(thread["scores"]) if thread["scores"] else None,
                "predicted_category": latest_triage.get("category"),
                "predicted_urgency": latest_triage.get("urgency"),
                "predicted_summary": latest_triage.get("summary"),
                "predicted_status": None,
                "predicted_needs_action_today": None,
                "predicted_next_action": latest_crm.get("next_action"),
                "global_next_actions": global_next_actions,
                "crm_contact_name": latest_crm.get("contact_name"),
                "crm_company": latest_crm.get("company"),
                "crm_opportunity_type": latest_crm.get("opportunity_type"),
                "crm_urgency": latest_crm.get("urgency"),
            }
        )

    unified_records.sort(
        key=lambda item: _safe_email_date(item.get("latest_message_date", "")),
        reverse=True,
    )
    return unified_records


def build_unified_records(run_data: dict[str, Any]) -> list[dict[str, Any]]:
    if run_data.get("threads"):
        return _normalize_v2_thread_records(run_data)
    return _build_legacy_thread_records(run_data)


def review_defaults() -> dict[str, Any]:
    return {
        "ai_result_correct": None,
        "correct_category": None,
        "correct_urgency": None,
        "summary_useful": None,
        "next_action_useful": None,
        "crm_useful": None,
        "should_have_been_filtered": "N/A",
        "notes": "",
        "improvement_tags": [],
    }


def gather_review_from_state(message_id: str) -> dict[str, Any]:
    return {
        "ai_result_correct": st.session_state.get(f"{message_id}_ai_result_correct"),
        "correct_category": st.session_state.get(f"{message_id}_correct_category"),
        "correct_urgency": st.session_state.get(f"{message_id}_correct_urgency"),
        "summary_useful": st.session_state.get(f"{message_id}_summary_useful"),
        "next_action_useful": st.session_state.get(f"{message_id}_next_action_useful"),
        "crm_useful": st.session_state.get(f"{message_id}_crm_useful"),
        "should_have_been_filtered": st.session_state.get(
            f"{message_id}_should_have_been_filtered", "N/A"
        ),
        "notes": st.session_state.get(f"{message_id}_notes", ""),
        "improvement_tags": st.session_state.get(f"{message_id}_improvement_tags", []),
    }


def on_review_change(message_id: str) -> None:
    """Autosave callback for review field changes."""

    reviews = st.session_state.get("review_results_data", {})
    upsert_review_result(reviews, message_id, gather_review_from_state(message_id))
    save_review_results(reviews, st.session_state["review_results_path"])
    st.session_state["review_results_data"] = reviews


def display_metrics(run_data: dict[str, Any], records: list[dict[str, Any]], reviews: dict[str, dict[str, Any]]) -> None:
    metrics = compute_top_metrics(run_data, records, reviews)
    row1 = st.columns(5)
    row1[0].metric("Threads fetched", metrics.total_fetched)
    row1[1].metric("Analyzed / cached", metrics.total_ai_covered)
    row1[2].metric("Fresh analysis", metrics.total_fresh_analysis)
    row1[3].metric("Cached reused", metrics.total_cached_reused)
    row1[4].metric("Not auto-analyzed", metrics.total_not_auto_analyzed)

    row2 = st.columns(5)
    row2[0].metric("New threads", metrics.total_new_threads)
    row2[1].metric("Changed threads", metrics.total_changed_threads)
    row2[2].metric("Total reviewed", metrics.total_reviewed)
    row2[3].metric("Total correct", metrics.total_correct)
    row2[4].metric("Total incorrect", metrics.total_incorrect)

    row3 = st.columns(4)
    row3[0].metric("Total fallback used", metrics.total_fallback_used)
    row3[1].metric("Total partially correct", metrics.total_partial)
    row3[2].metric("Category accuracy %", metrics.category_accuracy_pct)
    row3[3].metric("Urgency accuracy %", metrics.urgency_accuracy_pct)
    st.caption(f"Summary usefulness: {metrics.summary_usefulness_pct}%")
    st.caption(f"Loaded {metrics.total_messages} child messages across the visible thread dataset.")


def review_widget(
    label: str,
    options: list[str],
    key: str,
    message_id: str,
    index: int | None = None,
) -> None:
    if key not in st.session_state:
        if index is not None and 0 <= index < len(options):
            st.session_state[key] = options[index]
        else:
            st.session_state[key] = None
    kwargs: dict[str, Any] = {
        "label": label,
        "options": options,
        "key": key,
        "placeholder": "Select...",
        "on_change": on_review_change,
        "args": (message_id,),
    }
    st.selectbox(**kwargs)


def review_multiselect(
    label: str,
    options: list[str],
    key: str,
    message_id: str,
    default: list[str] | None = None,
) -> None:
    if key not in st.session_state:
        st.session_state[key] = default or []
    st.multiselect(
        label,
        options=options,
        key=key,
        on_change=on_review_change,
        args=(message_id,),
    )


def review_text_area(
    label: str,
    key: str,
    message_id: str,
    default: str = "",
    height: int = 80,
) -> None:
    if key not in st.session_state:
        st.session_state[key] = default
    st.text_area(
        label,
        key=key,
        height=height,
        on_change=on_review_change,
        args=(message_id,),
    )


def main() -> None:
    st.set_page_config(page_title="Gmail Triage Review UI", layout="wide")
    st.title("Gmail Triage Evaluation UI")
    st.caption("Local review tool for evaluating AI triage quality.")

    st.sidebar.header("Data Source")
    run_output_path = st.sidebar.text_input(
        "Pipeline output JSON",
        value="data/outputs/latest_run.json",
    )
    review_output_path = st.sidebar.text_input(
        "Review output JSON",
        value=DEFAULT_REVIEW_OUTPUT_PATH,
    )
    account_output_path = st.sidebar.text_input(
        "Gmail account profiles JSON",
        value=DEFAULT_ACCOUNT_OUTPUT_PATH,
    )

    if (
        "review_results_path" not in st.session_state
        or st.session_state["review_results_path"] != review_output_path
    ):
        st.session_state["review_results_path"] = review_output_path
        st.session_state["review_results_data"] = load_review_results(review_output_path)

    if (
        "gmail_accounts_path" not in st.session_state
        or st.session_state["gmail_accounts_path"] != account_output_path
    ):
        st.session_state["gmail_accounts_path"] = account_output_path
        st.session_state["gmail_accounts_data"] = load_gmail_accounts(account_output_path)

    st.sidebar.header("Gmail Accounts")
    account_data = st.session_state["gmail_accounts_data"]
    account_names = [item.get("name") for item in account_data.get("accounts", []) if item.get("name")]
    active_account = account_data.get("active_account")
    credentials_path = Path(
        os.getenv("GMAIL_CREDENTIALS_FILE", "data/raw/google_credentials.json")
    )
    token_dir = Path(os.getenv("GMAIL_ACCOUNT_TOKEN_DIR", "data/raw/gmail_tokens"))

    if st.sidebar.button("Connect Gmail account"):
        try:
            new_account = _connect_gmail_account(credentials_path, token_dir)
            account_data = upsert_gmail_account(account_data, new_account)
            save_gmail_accounts(account_data, account_output_path)
            st.session_state["gmail_accounts_data"] = account_data
            st.sidebar.success(f"Connected: {new_account['name']}")
            st.rerun()
        except Exception as exc:
            st.sidebar.error(f"Could not connect Gmail account: {exc}")

    if account_names:
        selected_account = st.sidebar.selectbox(
            "Connected accounts",
            options=account_names,
            index=account_names.index(active_account) if active_account in account_names else 0,
        )
        if selected_account != active_account:
            account_data["active_account"] = selected_account
            save_gmail_accounts(account_data, account_output_path)
            st.session_state["gmail_accounts_data"] = account_data
            st.sidebar.success(f"Switched to: {selected_account}")
        active_record = next(
            (item for item in account_data.get("accounts", []) if item.get("name") == selected_account),
            {},
        )
        st.sidebar.caption(
            f"Connected as: {active_record.get('email_address') or selected_account}"
        )
        st.sidebar.info(
            f"Active Gmail account: {active_record.get('email_address') or selected_account}"
        )
    else:
        st.sidebar.caption("No connected Gmail accounts yet. Click Connect Gmail account.")

    st.sidebar.header("Pipeline")
    thread_source_label = st.sidebar.selectbox(
        "Thread source",
        options=["Anywhere", "Sent", "Received"],
        key="pipeline_thread_source",
        help=(
            "Choose which messages seed the thread list. "
            "Once a thread is selected, V2 still loads the full conversation."
        ),
    )
    thread_source = thread_source_label.lower()
    if st.sidebar.button("Run app.py now"):
        active_record = next(
            (
                item
                for item in st.session_state["gmail_accounts_data"].get("accounts", [])
                if item.get("name") == st.session_state["gmail_accounts_data"].get("active_account")
            ),
            {},
        )
        token_path = active_record.get("token_path")
        process, message = _launch_backend_pipeline(
            token_path=token_path,
            thread_source=thread_source,
        )
        if process is not None:
            st.session_state["backend_process"] = process
            st.session_state["backend_process_started_at"] = datetime.now(timezone.utc).isoformat()
            st.session_state["last_pipeline_thread_source"] = thread_source_label
            st.sidebar.success(message)
            st.rerun()
        else:
            st.sidebar.error(message)

    if st.session_state.get("last_pipeline_thread_source"):
        st.sidebar.caption(
            f"Last backend run source: {st.session_state['last_pipeline_thread_source']}"
        )

    backend_process = st.session_state.get("backend_process")
    if backend_process is not None:
        process_state = backend_process.poll()
        if process_state is None:
            st.sidebar.info("Backend pipeline is running...")
        else:
            st.sidebar.success(f"Backend pipeline finished with code {process_state}.")
            st.session_state["backend_process"] = None
            st.session_state["last_backend_exit_code"] = process_state

    active_gmail_user_index = "0"
    active_gmail_email = "Unknown account"
    active_account_name = st.session_state["gmail_accounts_data"].get("active_account")
    for account in st.session_state["gmail_accounts_data"].get("accounts", []):
        if account.get("name") == active_account_name:
            active_gmail_user_index = str(account.get("gmail_user_index", "0"))
            active_gmail_email = str(account.get("email_address") or account.get("name") or "Unknown account")
            break

    run_data = load_pipeline_output(run_output_path)
    backend_process = st.session_state.get("backend_process")
    backend_running = backend_process is not None and backend_process.poll() is None

    if backend_running:
        st.subheader("Thread Review Queue")
        st.caption(
            "The list below is waiting for the new backend result. "
            "You do not need to refresh the browser manually."
        )
        render_loading_queue()
        return

    if "last_backend_exit_code" in st.session_state:
        st.success(
            f"Backend pipeline finished with code {st.session_state['last_backend_exit_code']}. "
            "The latest results are now loaded."
        )
        st.session_state.pop("last_backend_exit_code", None)

    if not run_data:
        st.warning(f"Could not load pipeline output from: {run_output_path}")
        render_skeleton_cards(3)
        return

    unified_records = build_unified_records(run_data)
    reviews_by_message_id: dict[str, dict[str, Any]] = st.session_state["review_results_data"]

    display_metrics(run_data, unified_records, reviews_by_message_id)
    st.divider()

    st.sidebar.header("Filters")
    review_state = st.sidebar.selectbox(
        "Review status",
        [
            "All threads",
            "Only reviewed",
            "Only not reviewed",
            "Only correct",
            "Only incorrect",
            "Only partially correct",
        ],
    )
    ai_filter_state = st.sidebar.selectbox(
        "Analysis coverage",
        [
            "All threads",
            "Only AI-covered",
            "Only not auto-analyzed",
            "Only cached",
            "Only fresh this run",
        ],
    )
    relevance_options = sorted(
        {
            record.get("relevance_bucket") or "Unknown"
            for record in unified_records
        }
    )
    change_options = sorted(
        {
            record.get("change_status") or "Unknown"
            for record in unified_records
        }
    )
    category_options = sorted(
        {
            record.get("predicted_category") or "Unknown"
            for record in unified_records
        }
    )
    urgency_options = sorted(
        {
            record.get("predicted_urgency") or "Unknown"
            for record in unified_records
        }
    )
    tag_options = sorted(
        set(IMPROVEMENT_TAG_OPTIONS)
        | {
            tag
            for review in reviews_by_message_id.values()
            for tag in (review.get("improvement_tags") or [])
        }
    )
    relevance_filter = st.sidebar.selectbox("Relevance bucket", ["All"] + relevance_options)
    change_filter = st.sidebar.selectbox("Change status", ["All"] + change_options)
    category_filter = st.sidebar.selectbox("Predicted category", ["All"] + category_options)
    urgency_filter = st.sidebar.selectbox("Predicted urgency", ["All"] + urgency_options)
    tag_filter = st.sidebar.selectbox("Improvement tag", ["All"] + tag_options)

    filtered_records = apply_record_filters(
        unified_records=unified_records,
        reviews_by_message_id=reviews_by_message_id,
        review_state=review_state,
        ai_filter_state=ai_filter_state,
        category_filter=category_filter,
        urgency_filter=urgency_filter,
        tag_filter=tag_filter,
        relevance_filter=relevance_filter,
        change_filter=change_filter,
    )
    if "review_page_size" not in st.session_state:
        st.session_state["review_page_size"] = 10
    st.sidebar.selectbox(
        "Threads per page",
        options=[5, 10, 20, 50],
        key="review_page_size",
        on_change=reset_review_page,
    )

    if st.sidebar.button("Save all reviews"):
        for record in unified_records:
            message_id = record["id"]
            upsert_review_result(
                reviews_by_message_id,
                message_id,
                gather_review_from_state(message_id),
            )
        save_review_results(reviews_by_message_id, review_output_path)
        st.sidebar.success("Saved all review changes.")

    tab_review, tab_analysis = st.tabs(["Review", "Error Analysis"])

    with tab_review:
        st.subheader("Thread Review Queue")
        st.caption("Review each Gmail thread and save judgments for quality analysis.")
        global_next_actions = run_data.get("summary", {}).get("next_actions", [])
        executive_summary = run_data.get("summary", {}).get("executive_summary")
        if executive_summary:
            st.info(executive_summary)
        if isinstance(global_next_actions, list) and global_next_actions:
            st.markdown("**Global Next Actions**")
            for action in global_next_actions:
                st.write(f"- {action}")
        page_size = int(st.session_state["review_page_size"])
        total_pages = max(1, (len(filtered_records) + page_size - 1) // page_size)

        if "review_page" not in st.session_state:
            st.session_state["review_page"] = 1
        if st.session_state["review_page"] > total_pages:
            st.session_state["review_page"] = total_pages
        if st.session_state["review_page"] < 1:
            st.session_state["review_page"] = 1

        start_index = (st.session_state["review_page"] - 1) * page_size
        end_index = start_index + page_size
        paginated_records = filtered_records[start_index:end_index]
        start_label = start_index + 1 if filtered_records else 0
        end_label = min(end_index, len(filtered_records)) if filtered_records else 0

        st.caption(f"Showing {start_label}-{end_label} of {len(filtered_records)} threads")

        for record in paginated_records:
            message_id = record["id"]
            existing_review = reviews_by_message_id.get(message_id, {})
            ai_result = existing_review.get("ai_result_correct")
            correct_category = existing_review.get("correct_category")
            correct_urgency = existing_review.get("correct_urgency")
            summary_useful = existing_review.get("summary_useful")
            next_action_useful = existing_review.get("next_action_useful")
            crm_useful = existing_review.get("crm_useful")
            should_have_been_filtered = existing_review.get("should_have_been_filtered", "N/A")
            notes_value = existing_review.get("notes", "")
            improvement_tags_value = existing_review.get("improvement_tags", [])

            title = f"{record.get('subject') or '(No subject)'}"
            with st.expander(title, expanded=False):
                header_left, header_mid, header_right = st.columns([4, 2, 2])

                with header_left:
                    st.markdown(f"**Participants:** {record.get('participants_display') or 'Unknown participants'}")
                    st.caption((record.get("latest_message_preview") or "-")[:180])
                    st.caption(format_record_badges(record))

                with header_mid:
                    st.markdown(f"**Messages:** {record.get('message_count') or 0}")
                    if len(record.get("source_thread_ids", [])) > 1:
                        st.markdown(
                            f"**Merged Gmail threads:** {len(record.get('source_thread_ids', []))}"
                        )
                    st.markdown(f"**Latest:** `{record.get('latest_message_date') or 'N/A'}`")
                    st.markdown(f"**Category:** `{record.get('predicted_category') or 'N/A'}`")
                    st.markdown(f"**Urgency:** `{record.get('predicted_urgency') or 'N/A'}`")

                with header_right:
                    st.markdown(f"**Relevance:** `{record.get('relevance_bucket') or 'N/A'}`")
                    st.markdown(f"**Change:** `{record.get('change_status') or 'N/A'}`")
                    st.markdown(f"**Analysis:** `{record.get('analysis_status') or 'N/A'}`")
                    if record.get("relevance_score") is not None:
                        st.markdown(f"**Score:** {record.get('relevance_score')}")
                    if record.get("last_analysis_at"):
                        st.caption(f"Last analysis: {record.get('last_analysis_at')}")
                    open_url, search_url = build_gmail_links(
                        {
                            "thread_id": record.get("thread_id"),
                            "sender": record.get("latest_message_sender"),
                            "participants": record.get("participants"),
                            "subject": record.get("subject"),
                        },
                        gmail_user_index=active_gmail_user_index,
                    )
                    link_col1, link_col2, link_col3 = st.columns([1, 1, 4])
                    with link_col1:
                        if open_url:
                            st.markdown(f"[Open in Gmail]({open_url})")
                    with link_col2:
                        st.markdown(f"[Search in Gmail]({search_url})")
                    with link_col3:
                        st.caption(record.get("selection_reason") or "")

                st.caption(
                    f"Thread-state signals: {format_selection_signals(record)}"
                )

                st.markdown("**Predicted Output**")
                st.markdown(f"- Category: `{record.get('predicted_category') or 'N/A'}`")
                st.markdown(f"- Urgency: `{record.get('predicted_urgency') or 'N/A'}`")
                st.markdown(f"- Summary: {record.get('predicted_summary') or 'N/A'}")
                st.markdown(f"- Current status: {record.get('predicted_status') or 'N/A'}")
                st.markdown(
                    f"- Needs action today: `{record.get('predicted_needs_action_today') if record.get('predicted_needs_action_today') is not None else 'N/A'}`"
                )
                st.markdown(
                    f"- Next action: {record.get('predicted_next_action') or 'N/A'}"
                )
                st.markdown(
                    "- CRM: "
                    f"contact=`{record.get('crm_contact_name') or 'N/A'}`, "
                    f"company=`{record.get('crm_company') or 'N/A'}`, "
                    f"opportunity=`{record.get('crm_opportunity_type') or 'N/A'}`, "
                    f"urgency=`{record.get('crm_urgency') or 'N/A'}`"
                )
                st.markdown("**Child Messages**")
                for child_index, child in enumerate(record.get("messages", []), start=1):
                    child_open_url, _ = build_gmail_links(
                        {
                            "thread_id": record.get("thread_id"),
                            "message_id": child.get("message_id"),
                            "prefer_message_link": True,
                            "sender": child.get("sender"),
                            "subject": child.get("subject"),
                        },
                        gmail_user_index=active_gmail_user_index,
                    )
                    st.markdown(
                        f"{child_index}. **{child.get('sender') or 'Unknown sender'}** | "
                        f"`{child.get('date') or 'Unknown date'}`"
                    )
                    st.markdown(f"   Subject: {child.get('subject') or '(No subject)'}")
                    st.markdown(f"   Snippet: {child.get('snippet') or 'N/A'}")
                    if child.get("cleaned_body"):
                        st.markdown(f"   Body: {(child.get('cleaned_body') or '')[:320]}")
                    if child_open_url:
                        st.markdown(f"   [Open message in Gmail]({child_open_url})")

                st.markdown("**Manual Review**")
                c1, c2, c3 = st.columns(3)
                with c1:
                    review_widget(
                        "AI result correct?",
                        REVIEW_OPTIONS,
                        f"{message_id}_ai_result_correct",
                        message_id,
                        REVIEW_OPTIONS.index(ai_result) if ai_result in REVIEW_OPTIONS else None,
                    )
                    review_widget(
                        "Correct category",
                        CATEGORY_OPTIONS,
                        f"{message_id}_correct_category",
                        message_id,
                        CATEGORY_OPTIONS.index(correct_category) if correct_category in CATEGORY_OPTIONS else None,
                    )
                with c2:
                    review_widget(
                        "Correct urgency",
                        URGENCY_OPTIONS,
                        f"{message_id}_correct_urgency",
                        message_id,
                        URGENCY_OPTIONS.index(correct_urgency) if correct_urgency in URGENCY_OPTIONS else None,
                    )
                    review_widget(
                        "Summary useful?",
                        REVIEW_OPTIONS,
                        f"{message_id}_summary_useful",
                        message_id,
                        REVIEW_OPTIONS.index(summary_useful) if summary_useful in REVIEW_OPTIONS else None,
                    )
                with c3:
                    review_widget(
                        "Next action useful?",
                        REVIEW_OPTIONS,
                        f"{message_id}_next_action_useful",
                        message_id,
                        REVIEW_OPTIONS.index(next_action_useful) if next_action_useful in REVIEW_OPTIONS else None,
                    )
                    review_widget(
                        "CRM extraction useful?",
                        CRM_OPTIONS,
                        f"{message_id}_crm_useful",
                        message_id,
                        CRM_OPTIONS.index(crm_useful) if crm_useful in CRM_OPTIONS else None,
                    )

                review_widget(
                    "Should this thread have been filtered out before AI?",
                    FILTER_NEEDED_OPTIONS,
                    f"{message_id}_should_have_been_filtered",
                    message_id,
                    FILTER_NEEDED_OPTIONS.index(should_have_been_filtered)
                    if should_have_been_filtered in FILTER_NEEDED_OPTIONS
                    else 0,
                )
                if record.get("analysis_status") in {"fresh", "cached"}:
                    st.caption(
                        "This thread already has machine-generated output. "
                        "Set Yes if it should not have been auto-analyzed."
                    )
                else:
                    st.caption(
                        "This thread stayed visible in review but was not auto-analyzed."
                    )

                review_multiselect(
                    "Improvement tags",
                    options=IMPROVEMENT_TAG_OPTIONS,
                    key=f"{message_id}_improvement_tags",
                    message_id=message_id,
                    default=improvement_tags_value if isinstance(improvement_tags_value, list) else [],
                )
                review_text_area(
                    "Notes",
                    key=f"{message_id}_notes",
                    message_id=message_id,
                    default=notes_value or "",
                    height=80,
                )

                # Comparison view with mismatch highlighting.
                human_category = st.session_state.get(f"{message_id}_correct_category")
                human_urgency = st.session_state.get(f"{message_id}_correct_urgency")
                predicted_category = record.get("predicted_category")
                predicted_urgency = record.get("predicted_urgency")
                notes = st.session_state.get(f"{message_id}_notes", "")
                summary_useful = st.session_state.get(f"{message_id}_summary_useful")

                if human_category:
                    if normalize_text(predicted_category) == normalize_text(human_category):
                        st.success(f"Category match: {predicted_category}")
                    else:
                        st.warning(
                            f"Category mismatch -> AI: {predicted_category or 'N/A'} | Human: {human_category}"
                        )
                if human_urgency:
                    if normalize_text(predicted_urgency) == normalize_text(human_urgency):
                        st.success(f"Urgency match: {predicted_urgency}")
                    else:
                        st.warning(
                            f"Urgency mismatch -> AI: {predicted_urgency or 'N/A'} | Human: {human_urgency}"
                        )
                if notes and summary_useful in {"No", "Partially"}:
                    st.info(
                        "Summary comparison cue: reviewer notes indicate the AI summary needs improvement."
                    )

        if total_pages > 1:
            render_review_pagination(
                current_page=st.session_state["review_page"],
                total_pages=total_pages,
                key_prefix="review_bottom",
            )

    with tab_analysis:
        st.subheader("Error Analysis")
        confusion_rows = category_confusion(unified_records, reviews_by_message_id)
        urgency_rows = urgency_mismatch_counts(unified_records, reviews_by_message_id)
        tag_rows = common_improvement_tags(reviews_by_message_id)
        needs_work_rows = records_needing_improvement(unified_records, reviews_by_message_id)
        recommendations = generate_recommendations(unified_records, reviews_by_message_id)

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Category confusion counts**")
            st.table(confusion_rows or [{"predicted": "-", "human": "-", "count": 0}])
            st.markdown("**Most common improvement tags**")
            st.table(tag_rows or [{"tag": "-", "count": 0}])
        with c2:
            st.markdown("**Urgency mismatch counts**")
            st.table(urgency_rows or [{"predicted": "-", "human": "-", "count": 0}])
            st.markdown("**Threads needing improvement most**")
            st.table(
                [
                    {
                        "thread_id": row.get("id"),
                        "subject": row.get("subject"),
                        "score": row.get("improvement_score"),
                    }
                    for row in needs_work_rows
                ]
                or [{"thread_id": "-", "subject": "-", "score": 0}]
            )

        st.markdown("**Recommendations**")
        for recommendation in recommendations:
            st.write(f"- {recommendation}")


if __name__ == "__main__":
    main()
