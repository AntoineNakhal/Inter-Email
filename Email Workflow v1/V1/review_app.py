"""Local Streamlit review UI for Gmail triage output quality checks."""

from __future__ import annotations

import json
import os
import subprocess
import sys
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


def _launch_backend_pipeline(token_path: str | None = None) -> tuple[subprocess.Popen[str] | None, str]:
    """Start the local backend app.py in the background."""

    project_app = PROJECT_ROOT / "app.py"
    if not project_app.exists():
        return None, f"Could not find backend app: {project_app}"

    env = os.environ.copy()
    if token_path:
        env["GMAIL_TOKEN_FILE"] = token_path

    BACKEND_RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(BACKEND_RUN_LOG, "a", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [sys.executable, str(project_app)],
            cwd=str(PROJECT_ROOT),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=env,
        )
    return process, f"Started backend pipeline process (pid={process.pid})."


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


def build_unified_records(run_data: dict[str, Any]) -> list[dict[str, Any]]:
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

    unified = []
    for email in run_data.get("emails", []):
        message_id = email.get("id", "")
        triage = triage_map.get(message_id, {})
        crm = crm_map.get(message_id, {})
        selection = selection_map.get(message_id, {})

        unified.append(
            {
                "id": message_id,
                "thread_id": email.get("thread_id", ""),
                "sender": email.get("from_address", ""),
                "subject": email.get("subject", ""),
                "snippet": email.get("snippet", ""),
                "body_preview": (email.get("body_text", "") or "")[:350],
                "included_in_ai": bool(selection.get("included_in_ai", False)),
                "selection_reason": selection.get("reason", "No selection info available."),
                "relevance_score": selection.get("relevance_score"),
                "predicted_category": triage.get("category"),
                "predicted_urgency": triage.get("urgency"),
                "predicted_summary": triage.get("summary"),
                "predicted_next_action": crm.get("next_action"),
                "global_next_actions": global_next_actions,
                "crm_contact_name": crm.get("contact_name"),
                "crm_company": crm.get("company"),
                "crm_opportunity_type": crm.get("opportunity_type"),
                "crm_urgency": crm.get("urgency"),
            }
        )
    return unified


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
    row1 = st.columns(4)
    row1[0].metric("Total fetched", metrics.total_fetched)
    row1[1].metric("Total filtered out", metrics.total_filtered)
    row1[2].metric("Total sent to AI", metrics.total_sent_to_ai)
    row1[3].metric("Total fallback used", metrics.total_fallback_used)

    row2 = st.columns(4)
    row2[0].metric("Total reviewed", metrics.total_reviewed)
    row2[1].metric("Total correct", metrics.total_correct)
    row2[2].metric("Total incorrect", metrics.total_incorrect)
    row2[3].metric("Total partially correct", metrics.total_partial)

    row3 = st.columns(3)
    row3[0].metric("Category accuracy %", metrics.category_accuracy_pct)
    row3[1].metric("Urgency accuracy %", metrics.urgency_accuracy_pct)
    row3[2].metric("Summary usefulness %", metrics.summary_usefulness_pct)


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
        process, message = _launch_backend_pipeline(token_path=token_path)  
        if process is not None:
            st.session_state["backend_process"] = process
            st.session_state["backend_process_started_at"] = datetime.now(timezone.utc).isoformat()
            st.sidebar.success(message)
            st.rerun()
        else:
            st.sidebar.error(message)

    backend_process = st.session_state.get("backend_process")
    if backend_process is not None:
        process_state = backend_process.poll()
        if process_state is None:
            st.sidebar.info("Backend pipeline is running...")
        else:
            st.sidebar.success(f"Backend pipeline finished with code {process_state}.")
            st.session_state["backend_process"] = None

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
        st.info("Backend pipeline is running. Refreshing the page will show the latest output once it is ready.")

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
            "All emails",
            "Only reviewed",
            "Only not reviewed",
            "Only correct",
            "Only incorrect",
            "Only partially correct",
        ],
    )
    ai_filter_state = st.sidebar.selectbox(
        "AI filter state",
        ["All emails", "Only AI filtered", "Only not AI filtered"],
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
    )
    if "review_page_size" not in st.session_state:
        st.session_state["review_page_size"] = 10
    st.sidebar.selectbox(
        "Emails per page",
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
        st.subheader("Email Review Queue")
        st.caption("Review each email and save judgments for quality analysis.")
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

        st.caption(f"Showing {start_label}-{end_label} of {len(filtered_records)} emails")

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
                    st.markdown(f"**{record.get('sender') or 'Unknown sender'}**")
                    st.caption((record.get("snippet") or record.get("body_preview") or "-")[:180])

                with header_mid:
                    st.markdown(f"**Category:** `{record.get('predicted_category') or 'N/A'}`")
                    st.markdown(f"**Urgency:** `{record.get('predicted_urgency') or 'N/A'}`")

                with header_right:
                    st.markdown(f"**AI included:** {'Yes' if record.get('included_in_ai') else 'No'}")
                    if record.get("relevance_score") is not None:
                        st.markdown(f"**Score:** {record.get('relevance_score')}")
                    open_url, search_url = build_gmail_links(
                        {
                            "id": record.get("id"),
                            "thread_id": record.get("thread_id"),
                            "from_address": record.get("sender"),
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


                st.markdown("**Predicted Output**")
                st.markdown(f"- Category: `{record.get('predicted_category') or 'N/A'}`")
                st.markdown(f"- Urgency: `{record.get('predicted_urgency') or 'N/A'}`")
                st.markdown(f"- Summary: {record.get('predicted_summary') or 'N/A'}")
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
                st.markdown(
                    f"- Global next actions note: {', '.join(record.get('global_next_actions', [])) or 'N/A'}"
                )

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
                    "Should this email have been filtered out before AI?",
                    FILTER_NEEDED_OPTIONS,
                    f"{message_id}_should_have_been_filtered",
                    message_id,
                    FILTER_NEEDED_OPTIONS.index(should_have_been_filtered)
                    if should_have_been_filtered in FILTER_NEEDED_OPTIONS
                    else 0,
                )
                if record.get("included_in_ai"):
                    st.caption("For non-filtered emails, set Yes if it should have been filtered out.")
                else:
                    st.caption("This email was already filtered by AI pre-processing.")

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
            st.markdown("**Emails needing improvement most**")
            st.table(
                [
                    {
                        "message_id": row.get("id"),
                        "subject": row.get("subject"),
                        "score": row.get("improvement_score"),
                    }
                    for row in needs_work_rows
                ]
                or [{"message_id": "-", "subject": "-", "score": 0}]
            )

        st.markdown("**Recommendations**")
        for recommendation in recommendations:
            st.write(f"- {recommendation}")


if __name__ == "__main__":
    main()
