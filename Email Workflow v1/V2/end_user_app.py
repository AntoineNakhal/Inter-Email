"""End-user Streamlit UI for the daily Gmail triage workflow."""

from __future__ import annotations

import html
import os
import subprocess
import sys
from datetime import date as calendar_date, datetime, timezone
from pathlib import Path
from typing import Any

import streamlit as st

from review_app import build_unified_records, load_pipeline_output
from schemas import DraftGenerationRequest
from services.draft_workflow import (
    draft_steps_for_record,
    generate_reply_draft_for_record,
)
from services.end_user_experience import (
    build_dashboard_sections,
    build_priority_sections,
    dashboard_snapshot,
    display_category,
    next_step_label,
    sort_latest_first,
    sort_for_end_user,
    trust_signal,
    user_friendly_summary,
    user_priority,
    why_it_matters,
)
from services.end_user_state import (
    DEFAULT_END_USER_STATE_PATH,
    clear_thread_seen,
    is_thread_seen,
    load_end_user_state,
    mark_thread_seen,
    save_end_user_state,
)
from services.metrics import build_gmail_links
from services.progress_state import (
    DEFAULT_PROGRESS_OUTPUT_PATH,
    WorkflowProgressTracker,
    load_progress_state,
    smooth_progress_for_display,
)
from services.review_store import (
    DEFAULT_ACCOUNT_OUTPUT_PATH,
    DEFAULT_REVIEW_OUTPUT_PATH,
    load_gmail_accounts,
    load_review_results,
    save_review_results,
    upsert_review_result,
)


PROJECT_ROOT = Path(__file__).resolve().parent
BACKEND_RUN_LOG = PROJECT_ROOT / "data" / "outputs" / "backend_run.log"
BACKEND_PROGRESS_PATH = PROJECT_ROOT / DEFAULT_PROGRESS_OUTPUT_PATH
QUEUE_BELONGS_OPTIONS = ["Yes", "No", "Not sure"]
MERGE_CHECK_OPTIONS = ["Yes", "No", "Not sure"]
HELPFUL_OPTIONS = ["Yes", "Partially", "No"]
VIEW_OPTIONS = ["Dashboard", "Priority View", "Thread Detail", "Review Mode"]
ORDER_OPTIONS = ["Recommended queue", "Latest message first"]
DRAFT_STEP_TITLES = {
    "date": "Date",
    "attachment": "Attachments",
    "instructions": "Guidance",
    "preview": "Preview",
}


def apply_end_user_styles() -> None:
    """Add a calmer, more guided visual layer for non-technical users."""

    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500&display=swap');

        .stApp {
            background:
                radial-gradient(circle at top right, rgba(255, 212, 153, 0.28), transparent 30%),
                radial-gradient(circle at top left, rgba(173, 216, 230, 0.20), transparent 25%),
                linear-gradient(180deg, #fffaf2 0%, #f4f0e7 100%);
            color: #1f2933;
        }

        html, body, [class*="css"] {
            font-family: "Manrope", "Segoe UI", sans-serif;
        }

        code, pre, .mono {
            font-family: "IBM Plex Mono", monospace !important;
        }

        .hero-shell {
            border: 1px solid rgba(31, 41, 51, 0.08);
            border-radius: 24px;
            padding: 1.4rem 1.5rem;
            background: rgba(255, 255, 255, 0.82);
            box-shadow: 0 18px 45px rgba(31, 41, 51, 0.08);
            margin-bottom: 1rem;
        }

        .hero-kicker {
            font-size: 0.78rem;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            color: #8a6d3b;
            font-weight: 800;
            margin-bottom: 0.5rem;
        }

        .metric-tile {
            border: 1px solid rgba(31, 41, 51, 0.08);
            border-radius: 20px;
            padding: 1rem 1.1rem;
            background: rgba(255, 255, 255, 0.76);
            min-height: 132px;
            box-shadow: 0 10px 24px rgba(31, 41, 51, 0.06);
        }

        .metric-label {
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: #66788a;
            font-weight: 800;
        }

        .metric-value {
            font-size: 2rem;
            line-height: 1.1;
            font-weight: 800;
            color: #14202b;
            margin: 0.35rem 0;
        }

        .metric-caption {
            color: #506273;
            font-size: 0.92rem;
        }

        .tone-pill {
            display: inline-block;
            border-radius: 999px;
            padding: 0.35rem 0.7rem;
            font-size: 0.82rem;
            font-weight: 800;
            margin-right: 0.35rem;
            margin-bottom: 0.35rem;
        }

        .tone-urgent { background: #ffe4de; color: #9f2f1c; }
        .tone-important { background: #fff2d8; color: #8a5a00; }
        .tone-watch { background: #e7f1ff; color: #285ea8; }
        .tone-neutral { background: #edf2f7; color: #405261; }
        .tone-positive { background: #e5f6ea; color: #1f6c41; }
        .tone-caution { background: #fff3d2; color: #956300; }
        .tone-warning { background: #ffe6d9; color: #a34816; }
        .tone-blocked { background: #f6dde8; color: #8c1d4d; }
        .tone-manual { background: #ece4ff; color: #5d3cb3; }
        .tone-calm { background: #ebf5ef; color: #35624a; }

        .thread-title {
            font-size: 1.15rem;
            font-weight: 800;
            color: #182632;
            margin: 0;
        }

        .detail-hero {
            border: 1px solid rgba(31, 41, 51, 0.10);
            border-radius: 20px;
            padding: 1rem 1.1rem;
            background: rgba(255, 255, 255, 0.84);
            margin-bottom: 1.15rem;
            box-shadow: 0 10px 24px rgba(31, 41, 51, 0.05);
        }

        .detail-subject {
            margin: 0;
            font-size: 1.25rem;
            line-height: 1.35;
            color: #162737;
            font-weight: 800;
        }

        .detail-meta {
            margin-top: 0.42rem;
            color: #4f6476;
            font-size: 0.92rem;
        }

        .detail-pill-wrap {
            display: flex;
            flex-wrap: wrap;
            gap: 0.35rem;
            margin-top: 0.62rem;
        }

        .detail-grid {
            display: grid;
            grid-template-columns: minmax(0, 1.35fr) minmax(0, 1fr);
            gap: 0.85rem;
            margin-top: 0.45rem;
            margin-bottom: 0.9rem;
        }

        .detail-grid-card {
            border: 1px solid rgba(31, 41, 51, 0.10);
            border-radius: 18px;
            padding: 1.05rem 1.1rem;
            background: rgba(255, 255, 255, 0.82);
            box-shadow: 0 8px 20px rgba(31, 41, 51, 0.04);
            margin-bottom: 0.55rem;
        }

        @media (max-width: 980px) {
            .detail-grid {
                grid-template-columns: minmax(0, 1fr);
            }
        }

        .thread-meta {
            color: #566b7b;
            font-size: 0.89rem;
            margin: 0;
        }

        .thread-category {
            color: #355066;
            font-size: 0.84rem;
            font-weight: 700;
            letter-spacing: 0.01em;
            margin: 0;
        }

        .thread-summary {
            color: #233544;
            font-size: 0.98rem;
            line-height: 1.42;
            margin: 0;
        }

        .thread-card-copy {
            display: flex;
            flex-direction: column;
            gap: 0.42rem;
        }

        .thread-header-row {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 0.8rem;
        }

        .thread-pill-row {
            display: flex;
            flex-wrap: wrap;
            justify-content: flex-end;
            gap: 0.25rem;
        }

        .thread-next-shell {
            margin-top: 0.22rem;
            border: 1px solid rgba(210, 167, 75, 0.28);
            border-left: 4px solid #d2a74b;
            border-radius: 14px;
            padding: 0.7rem 0.85rem 0.72rem 0.85rem;
            background: rgba(255, 248, 231, 0.82);
        }

        .thread-next-label {
            color: #8b6b22;
            font-size: 0.74rem;
            font-weight: 800;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            margin-bottom: 0.28rem;
        }

        .thread-next-text {
            color: #142533;
            font-size: 1.04rem;
            font-weight: 700;
            line-height: 1.42;
        }

        .thread-why {
            color: #627586;
            font-size: 0.86rem;
            line-height: 1;
            margin-bottom: 0.5rem;
        }

        .thread-note {
            color: #7c5d1c;
            font-size: 0.84rem;
            line-height: 1.35;
        }

            .thread-actions-spacer {
                height: 0.85rem;
        }

            .thread-actions-spacer + div [data-testid="stHorizontalBlock"] {
                row-gap: 0.05rem;
        }

        .card-link-row {
            display: flex;
            justify-content: flex-end;
            align-items: center;
            gap: 0.38rem;
            white-space: nowrap;
            margin-top: 0.08rem;
            font-size: 0.89rem;
        }

        .card-link-row a {
            color: #285ea8;
            text-decoration: none;
            font-weight: 700;
        }

        .card-link-row a:hover {
            text-decoration: underline;
        }

        .card-link-sep {
            color: #8aa0b2;
        }

        .timeline-card {
            border: 1px solid rgba(31, 41, 51, 0.08);
            border-radius: 18px;
            padding: 0.95rem 1rem;
            background: rgba(255, 255, 255, 0.8);
            margin-bottom: 0.75rem;
        }

        .timeline-latest {
            border-color: rgba(210, 167, 75, 0.55);
            box-shadow: inset 0 0 0 1px rgba(210, 167, 75, 0.18);
        }

        .helper-copy {
            color: #5d6f7d;
            font-size: 0.94rem;
        }

        .draft-context-chip {
            display: inline-block;
            border-radius: 999px;
            padding: 0.32rem 0.7rem;
            background: rgba(40, 94, 168, 0.10);
            color: #285ea8;
            font-size: 0.83rem;
            font-weight: 700;
            margin-right: 0.4rem;
            margin-bottom: 0.4rem;
        }

        .draft-helper-box {
            border: 1px solid rgba(31, 41, 51, 0.08);
            border-radius: 16px;
            padding: 0.9rem 1rem;
            background: rgba(255, 255, 255, 0.78);
            margin-bottom: 0.8rem;
        }

        .skeleton-card {
            border: 1px solid rgba(49, 51, 63, 0.10);
            border-radius: 18px;
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

        .loading-action-shell {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 0.65rem;
            width: 100%;
            border-radius: 14px;
            padding: 0.7rem 0.9rem;
            margin-top: 0.15rem;
            background: rgba(20, 32, 43, 0.08);
            border: 1px solid rgba(20, 32, 43, 0.10);
            color: #4c6170;
            font-size: 0.95rem;
            font-weight: 700;
            box-sizing: border-box;
        }

        .loading-action-spinner {
            width: 0.95rem;
            height: 0.95rem;
            border-radius: 999px;
            border: 2px solid rgba(40, 94, 168, 0.18);
            border-top-color: #285ea8;
            animation: end-user-spin 0.8s linear infinite;
            flex: 0 0 auto;
        }

        @keyframes shimmer {
            0% { background-position: 100% 0; }
            100% { background-position: 0 0; }
        }

        @keyframes end-user-spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _launch_backend_pipeline(token_path: str | None = None) -> tuple[subprocess.Popen[str] | None, str]:
    """Start the backend app in the background for a fresh refresh."""

    project_app = PROJECT_ROOT / "app.py"
    if not project_app.exists():
        return None, f"Could not find backend app: {project_app}"

    env = os.environ.copy()
    if token_path:
        env["GMAIL_TOKEN_FILE"] = token_path

    WorkflowProgressTracker(BACKEND_PROGRESS_PATH).update(
        "queued",
        1,
        "Preparing refresh...",
    )
    BACKEND_RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(BACKEND_RUN_LOG, "a", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [sys.executable, str(project_app)],
            cwd=str(PROJECT_ROOT),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=env,
        )
    return process, f"Started inbox refresh (pid={process.pid})."


def render_skeleton_cards(count: int = 3) -> None:
    """Render calm loading placeholders while the backend refreshes."""

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


def render_loading_button(label: str = "Refreshing inbox...") -> None:
    """Render a disabled-looking sidebar action with a spinner."""

    st.sidebar.markdown(
        (
            "<div class='loading-action-shell'>"
            "<span class='loading-action-spinner'></span>"
            f"<span>{html.escape(label)}</span>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def current_end_user_progress_state() -> dict[str, Any]:
    """Return a smoother visual progress state for the main end-user loading area."""

    raw_progress = load_progress_state(BACKEND_PROGRESS_PATH)
    return smooth_progress_for_display(
        raw_progress,
        st.session_state,
        "end_user_backend",
    )


@st.fragment(run_every="200ms")
def render_loading_queue() -> None:
    """Keep the page live while the backend is still running."""

    backend_process = st.session_state.get("end_user_backend_process")
    if backend_process is None:
        return

    process_state = backend_process.poll()
    if process_state is None:
        progress_state = current_end_user_progress_state()
        progress_value = max(1, int(progress_state.get("progress", 1) or 1))
        progress_detail = str(
            progress_state.get("detail") or "Refreshing Gmail threads..."
        )
        st.progress(progress_value)
        st.caption(f"{progress_detail} ({progress_value}%)")
        render_skeleton_cards(4)
        return

    st.session_state["end_user_backend_process"] = None
    st.session_state["end_user_last_backend_exit_code"] = process_state
    st.rerun()


def tone_pill(label: str, tone: str) -> str:
    safe_label = html.escape(label)
    safe_tone = html.escape(tone or "neutral")
    return f"<span class='tone-pill tone-{safe_tone}'>{safe_label}</span>"


def render_metric_tile(label: str, value: int, caption: str) -> None:
    st.markdown(
        (
            "<div class='metric-tile'>"
            f"<div class='metric-label'>{html.escape(label)}</div>"
            f"<div class='metric-value'>{value}</div>"
            f"<div class='metric-caption'>{html.escape(caption)}</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _record_matches_focus(record: dict[str, Any], focus_filter: str) -> bool:
    label = str(user_priority(record)["label"])
    if focus_filter == "All conversations":
        return True
    if focus_filter == "Needs attention today":
        return label == "Today"
    if focus_filter == "Review soon":
        return label == "Soon"
    if focus_filter == "Watch list":
        return label == "Watch"
    if focus_filter == "Manual only":
        return label == "Manual only"
    if focus_filter == "FYI / done":
        return label in {"FYI", "Done"}
    return True


def _record_matches_search(record: dict[str, Any], search_text: str) -> bool:
    normalized_search = search_text.strip().lower()
    if not normalized_search:
        return True

    haystacks = [
        str(record.get("subject") or ""),
        str(record.get("participants_full") or ""),
        str(record.get("predicted_summary") or ""),
        str(record.get("predicted_next_action") or ""),
    ]
    combined_text = " ".join(haystacks).lower()
    return normalized_search in combined_text


def _record_matches_category(record: dict[str, Any], category_filter: str) -> bool:
    if category_filter == "All categories":
        return True
    return display_category(record) == category_filter


def filter_end_user_records(
    records: list[dict[str, Any]],
    focus_filter: str,
    search_text: str,
    category_filter: str,
) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if _record_matches_focus(record, focus_filter)
        and _record_matches_search(record, search_text)
        and _record_matches_category(record, category_filter)
    ]


def find_thread_by_id(records: list[dict[str, Any]], thread_id: str) -> dict[str, Any] | None:
    for record in records:
        if record.get("id") == thread_id:
            return record
    return None


def set_selected_thread(thread_id: str) -> None:
    st.session_state["selected_thread_id"] = thread_id


def set_active_view(view_name: str) -> None:
    """Queue a view change for the next rerun."""

    if view_name in VIEW_OPTIONS:
        st.session_state["end_user_requested_view"] = view_name


def open_thread_details(thread_id: str) -> None:
    """Focus one thread and move the user into the detail screen."""

    set_selected_thread(thread_id)
    set_active_view("Thread Detail")


def end_user_scope(active_record: dict[str, Any]) -> str:
    """Return a stable per-account scope for seen-state tracking."""

    return str(
        active_record.get("email_address")
        or active_record.get("name")
        or active_record.get("gmail_user_index")
        or "default"
    ).strip() or "default"


def persist_seen_state(state_payload: dict[str, Any], state_path: str) -> None:
    """Save seen-state and keep session state in sync."""

    save_end_user_state(state_payload, state_path)
    st.session_state["end_user_state"] = state_payload


def build_dashboard_records(
    records: list[dict[str, Any]],
    state_payload: dict[str, Any],
    seen_scope: str,
) -> list[dict[str, Any]]:
    """Keep only unseen or changed threads on the dashboard."""

    return [
        record
        for record in records
        if not is_thread_seen(state_payload, record, seen_scope)
    ]


def build_seen_records(
    records: list[dict[str, Any]],
    state_payload: dict[str, Any],
    seen_scope: str,
) -> list[dict[str, Any]]:
    """Return records that are already seen at their current version."""

    return [
        record
        for record in records
        if is_thread_seen(state_payload, record, seen_scope)
    ]


def open_draft_wizard(record: dict[str, Any]) -> None:
    """Initialize a clean draft wizard session for one thread."""

    nonce = int(datetime.now(timezone.utc).timestamp() * 1000)
    st.session_state["draft_wizard_state"] = {
        "is_open": True,
        "thread_id": str(record.get("id") or record.get("thread_id") or ""),
        "steps": draft_steps_for_record(record),
        "step_index": 0,
        "nonce": nonce,
        "selected_date": None,
        "skipped_date": False,
        "attachment_names": [],
        "skipped_attachments": False,
        "user_instructions": "",
        "generated_subject": "",
        "generated_body": "",
        "generation_error": None,
    }


def close_draft_wizard() -> None:
    """Close the draft wizard and discard the in-memory state."""

    st.session_state.pop("draft_wizard_state", None)


def active_draft_wizard_for_record(record: dict[str, Any]) -> dict[str, Any] | None:
    """Return the active wizard state when it belongs to this thread."""

    wizard_state = st.session_state.get("draft_wizard_state")
    if not isinstance(wizard_state, dict):
        return None
    if not wizard_state.get("is_open"):
        return None
    if str(wizard_state.get("thread_id") or "") != str(
        record.get("id") or record.get("thread_id") or ""
    ):
        return None
    return wizard_state


def wizard_step_title(step_id: str) -> str:
    """Return a user-friendly title for one wizard step."""

    return DRAFT_STEP_TITLES.get(step_id, "Draft")


def render_draft_context_summary(wizard_state: dict[str, Any]) -> None:
    """Show the chosen wizard context in a compact way on preview."""

    chips: list[str] = []
    if wizard_state.get("selected_date"):
        chips.append(
            f"<span class='draft-context-chip'>Date: {html.escape(str(wizard_state['selected_date']))}</span>"
        )
    elif wizard_state.get("skipped_date"):
        chips.append("<span class='draft-context-chip'>Date skipped</span>")

    attachment_names = [
        str(name) for name in wizard_state.get("attachment_names", []) if str(name).strip()
    ]
    if attachment_names:
        chips.append(
            f"<span class='draft-context-chip'>Attachments: {html.escape(', '.join(attachment_names))}</span>"
        )
    elif wizard_state.get("skipped_attachments"):
        chips.append("<span class='draft-context-chip'>Attachments skipped</span>")

    if wizard_state.get("user_instructions"):
        chips.append("<span class='draft-context-chip'>Custom guidance added</span>")

    if chips:
        st.markdown("".join(chips), unsafe_allow_html=True)


@st.dialog("Create Draft")
def render_draft_wizard_modal(record: dict[str, Any]) -> None:
    """Render the end-user multi-step draft wizard."""

    wizard_state = active_draft_wizard_for_record(record)
    if wizard_state is None:
        return

    steps = wizard_state.get("steps", ["instructions", "preview"])
    step_index = max(0, min(int(wizard_state.get("step_index", 0)), len(steps) - 1))
    current_step = str(steps[step_index])
    nonce = str(wizard_state.get("nonce") or "0")
    thread_id = str(record.get("id") or record.get("thread_id") or "")
    date_key = f"draft_wizard_date_{thread_id}_{nonce}"
    attachment_key = f"draft_wizard_attachments_{thread_id}_{nonce}"
    instructions_key = f"draft_wizard_instructions_{thread_id}_{nonce}"
    subject_key = f"draft_wizard_subject_{thread_id}_{nonce}"
    body_key = f"draft_wizard_body_{thread_id}_{nonce}"

    step_percent = int(((step_index + 1) / max(len(steps), 1)) * 100)
    st.progress(step_percent)
    st.caption(
        f"Step {step_index + 1} of {len(steps)} · {wizard_step_title(current_step)}"
    )

    st.markdown(
        (
            "<div class='draft-helper-box'>"
            "<strong>Create a reply only when you need it.</strong><br/>"
            "This wizard only asks for the extra inputs that matter for this conversation."
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    def go_to_next_step() -> None:
        wizard_state["step_index"] = min(step_index + 1, len(steps) - 1)
        wizard_state["generation_error"] = None
        st.session_state["draft_wizard_state"] = wizard_state
        st.rerun()

    def go_to_previous_step() -> None:
        wizard_state["step_index"] = max(step_index - 1, 0)
        wizard_state["generation_error"] = None
        st.session_state["draft_wizard_state"] = wizard_state
        st.rerun()

    if current_step == "date":
        st.markdown("**Date context**")
        st.caption(
            record.get("draft_date_reason")
            or "This reply will likely read better if you add a date."
        )
        selected_date = st.date_input(
            "Date to mention in the reply",
            value=None,
            key=date_key,
            help="Leave it empty if you are not ready to commit to a date yet.",
        )
        action_left, action_right = st.columns(2)
        with action_left:
            if st.button("Skip", use_container_width=True, key=f"date_skip_{nonce}"):
                wizard_state["selected_date"] = None
                wizard_state["skipped_date"] = True
                go_to_next_step()
        with action_right:
            if st.button(
                "Continue",
                use_container_width=True,
                key=f"date_continue_{nonce}",
            ):
                if isinstance(selected_date, calendar_date):
                    wizard_state["selected_date"] = selected_date.isoformat()
                    wizard_state["skipped_date"] = False
                    go_to_next_step()
                else:
                    st.warning("Choose a date or use Skip.")
        return

    if current_step == "attachment":
        st.markdown("**Attachment context**")
        st.caption(
            record.get("draft_attachment_reason")
            or "This reply may need files or documents."
        )
        st.caption(
            "Attachments are not sent automatically here. We only use them to shape the draft."
        )
        uploaded_files = st.file_uploader(
            "Optional files to mention in the draft",
            accept_multiple_files=True,
            key=attachment_key,
        )
        selected_attachment_names = [file.name for file in uploaded_files] if uploaded_files else []
        if selected_attachment_names:
            st.caption(f"Selected: {', '.join(selected_attachment_names)}")
        action_left, action_right = st.columns(2)
        with action_left:
            if st.button(
                "Skip for now",
                use_container_width=True,
                key=f"attachment_skip_{nonce}",
            ):
                wizard_state["attachment_names"] = []
                wizard_state["skipped_attachments"] = True
                go_to_next_step()
        with action_right:
            if st.button(
                "Continue",
                use_container_width=True,
                key=f"attachment_continue_{nonce}",
            ):
                wizard_state["attachment_names"] = selected_attachment_names
                wizard_state["skipped_attachments"] = not bool(selected_attachment_names)
                go_to_next_step()
        return

    if current_step == "instructions":
        st.markdown("**AI guidance**")
        st.caption(
            "Add a few keywords or short instructions to shape the tone or content."
        )
        st.text_area(
            "What should the draft include?",
            key=instructions_key,
            height=140,
            placeholder="Be polite but brief. Mention delivery delay. Say we are available next Tuesday.",
        )
        nav_left, nav_right = st.columns(2)
        with nav_left:
            if step_index > 0 and st.button(
                "Back",
                use_container_width=True,
                key=f"instructions_back_{nonce}",
            ):
                wizard_state["user_instructions"] = str(
                    st.session_state.get(instructions_key) or ""
                ).strip()
                go_to_previous_step()
        with nav_right:
            if st.button(
                "Generate draft",
                use_container_width=True,
                key=f"instructions_generate_{nonce}",
                type="primary",
            ):
                wizard_state["user_instructions"] = str(
                    st.session_state.get(instructions_key) or ""
                ).strip()
                draft_request = DraftGenerationRequest(
                    thread_id=str(record.get("thread_id") or record.get("id") or ""),
                    selected_date=wizard_state.get("selected_date"),
                    skipped_date=bool(wizard_state.get("skipped_date", False)),
                    attachment_names=[
                        str(name)
                        for name in wizard_state.get("attachment_names", [])
                        if str(name).strip()
                    ],
                    skipped_attachments=bool(
                        wizard_state.get("skipped_attachments", False)
                    ),
                    user_instructions=wizard_state.get("user_instructions", ""),
                )
                try:
                    with st.spinner("Generating your draft..."):
                        draft = generate_reply_draft_for_record(record, draft_request)
                except Exception as exc:
                    wizard_state["generation_error"] = str(exc)
                    st.session_state["draft_wizard_state"] = wizard_state
                    st.rerun()

                wizard_state["generated_subject"] = draft.subject
                wizard_state["generated_body"] = draft.body
                wizard_state["generation_error"] = None
                wizard_state["step_index"] = min(step_index + 1, len(steps) - 1)
                st.session_state["draft_wizard_state"] = wizard_state
                st.session_state[subject_key] = draft.subject
                st.session_state[body_key] = draft.body
                st.rerun()
        if wizard_state.get("generation_error"):
            st.error(str(wizard_state["generation_error"]))
        return

    st.markdown("**Draft preview**")
    render_draft_context_summary(wizard_state)
    if wizard_state.get("selected_date"):
        st.caption(f"Date used: {wizard_state['selected_date']}")
    elif wizard_state.get("skipped_date"):
        st.caption("Date step was skipped.")
    if wizard_state.get("generation_error"):
        st.error(str(wizard_state["generation_error"]))

    st.text_input(
        "Subject",
        value=wizard_state.get("generated_subject") or "",
        key=subject_key,
    )
    st.text_area(
        "Draft body",
        value=wizard_state.get("generated_body") or "",
        key=body_key,
        height=260,
    )
    if wizard_state.get("user_instructions"):
        st.caption(f"Your guidance: {wizard_state['user_instructions']}")

    preview_left, preview_mid, preview_right = st.columns(3)
    with preview_left:
        if step_index > 0 and st.button(
            "Back",
            use_container_width=True,
            key=f"preview_back_{nonce}",
        ):
            wizard_state["generated_subject"] = str(
                st.session_state.get(subject_key) or wizard_state.get("generated_subject") or ""
            )
            wizard_state["generated_body"] = str(
                st.session_state.get(body_key) or wizard_state.get("generated_body") or ""
            )
            go_to_previous_step()
    with preview_mid:
        if st.button(
            "Create another version",
            use_container_width=True,
            key=f"preview_regenerate_{nonce}",
        ):
            wizard_state["generated_subject"] = ""
            wizard_state["generated_body"] = ""
            wizard_state["generation_error"] = None
            wizard_state["step_index"] = max(len(steps) - 2, 0)
            st.session_state["draft_wizard_state"] = wizard_state
            st.rerun()
    with preview_right:
        if st.button(
            "Done",
            use_container_width=True,
            key=f"preview_done_{nonce}",
            type="primary",
        ):
            close_draft_wizard()
            st.rerun()

def render_queue_card(
    record: dict[str, Any],
    gmail_user_index: str,
    button_key_prefix: str,
    state_path: str,
    seen_scope: str,
) -> None:
    """Render a plain-language queue card."""

    priority = user_priority(record)
    trust = trust_signal(record)
    summary = user_friendly_summary(record)
    next_step = next_step_label(record)
    reasons = why_it_matters(record)
    category_label = display_category(record)
    seen_now = is_thread_seen(st.session_state["end_user_state"], record, seen_scope)
    open_url, search_url = build_gmail_links(
        {
            "thread_id": record.get("thread_id"),
            "sender": record.get("latest_message_sender"),
            "participants": record.get("participants"),
            "subject": record.get("subject"),
        },
        gmail_user_index=gmail_user_index,
    )

    with st.container(border=True):
        reason_text = " | ".join(html.escape(reason) for reason in reasons)
        seen_note = ""
        if seen_now:
            seen_note = (
                "<div class='thread-note'>Seen already. This card returns to the dashboard only if the conversation changes.</div>"
            )

        st.markdown(
            (
                "<div class='thread-card-copy'>"
                "<div class='thread-header-row'>"
                f"<div class='thread-title'>{html.escape(record.get('subject') or '(No subject)')}</div>"
                "<div class='thread-pill-row'>"
                f"{tone_pill(str(priority['label']), str(priority['tone']))}"
                f"{tone_pill(str(trust['label']), str(trust['tone']))}"
                "</div>"
                "</div>"
                f"<div class='thread-meta'>{html.escape(record.get('participants_display') or 'Unknown participants')} | {html.escape(record.get('latest_message_date') or 'Unknown date')} | {int(record.get('message_count') or 0)} message(s)</div>"
                f"<div class='thread-category'>Category: {html.escape(category_label)}</div>"
                f"<div class='thread-summary'>{html.escape(summary)}</div>"
                "<div class='thread-next-shell'>"
                "<div class='thread-next-label'>Next Step</div>"
                f"<div class='thread-next-text'>{html.escape(next_step)}</div>"
                "</div>"
                f"<div class='thread-why'>Why this is visible: {reason_text}</div>"
                f"{seen_note}"
                "</div>"
            ),
            unsafe_allow_html=True,
        )

        st.markdown("<div class='thread-actions-spacer'></div>", unsafe_allow_html=True)
        action_col1, action_col2, action_col3 = st.columns([0.78, 0.78, 2.1])
        with action_col1:
            if st.button(
                "Open thread details",
                key=f"{button_key_prefix}_{record['id']}_open",
                use_container_width=False,
            ):
                open_thread_details(str(record["id"]))
                st.rerun()
        with action_col2:
            seen_label = "Show again" if seen_now else "I've seen this"
            if st.button(
                seen_label,
                key=f"{button_key_prefix}_{record['id']}_seen",
                use_container_width=False,
            ):
                state_payload = st.session_state["end_user_state"]
                if seen_now:
                    clear_thread_seen(state_payload, str(record["id"]), seen_scope)
                else:
                    mark_thread_seen(state_payload, record, seen_scope)
                persist_seen_state(state_payload, state_path)
                st.rerun()
        with action_col3:
            link_parts: list[str] = []
            if open_url:
                link_parts.append(
                    f"<a href='{html.escape(open_url, quote=True)}' target='_blank'>Open in Gmail</a>"
                )
            if search_url:
                link_parts.append(
                    f"<a href='{html.escape(search_url, quote=True)}' target='_blank'>Search in Gmail</a>"
                )
            if link_parts:
                st.markdown(
                    f"<div class='card-link-row'>{'<span class=\"card-link-sep\">&middot;</span>'.join(link_parts)}</div>",
                    unsafe_allow_html=True,
                )


def render_dashboard(
    run_data: dict[str, Any],
    records: list[dict[str, Any]],
    seen_records: list[dict[str, Any]],
    gmail_user_index: str,
    state_path: str,
    seen_scope: str,
    hidden_seen_count: int,
) -> None:
    """Show the at-a-glance starting point for a non-technical user."""

    counts = dashboard_snapshot(records, seen_records)
    executive_summary = str(run_data.get("summary", {}).get("executive_summary") or "").strip()
    if not executive_summary:
        executive_summary = "The queue is ready. Start with the conversations that need attention today."

    st.markdown(
        (
            "<div class='hero-shell'>"
            "<div class='hero-kicker'>Today at a glance</div>"
            "<div style='font-size:1.4rem;font-weight:800;color:#152533;'>"
            "Open the app, review the short queue, then jump into Gmail only when needed."
            "</div>"
            f"<div class='helper-copy' style='margin-top:0.65rem;'>{html.escape(executive_summary)}</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    if hidden_seen_count > 0:
        st.caption(
            f"{hidden_seen_count} conversation(s) you already saw are hidden here until something new arrives."
        )

    metric_cols = st.columns(5)
    with metric_cols[0]:
        render_metric_tile("Today", counts["today"], "Likely needs action today")
    with metric_cols[1]:
        render_metric_tile("New", counts["new"], "Surfaced since the last run")
    with metric_cols[2]:
        render_metric_tile("Changed", counts["changed"], "Updated since the last run")
    with metric_cols[3]:
        render_metric_tile("Manual Only", counts["manual_only"], "Sensitive or blocked from AI")
    with metric_cols[4]:
        render_metric_tile("Seen", counts["seen"], "Already reviewed at this version")

    st.markdown("**Today’s queue**")
    sections = build_dashboard_sections(records)
    if not records:
        st.success("You are caught up. Seen conversations stay hidden here until the thread changes.")
        sections = []
    for section in sections:
        if not section["items"] and section["title"] in {"Review soon", "FYI / done"}:
            continue
        st.markdown(f"**{section['title']}**")
        if not section["items"]:
            st.caption(section["empty"])
            continue
        for record in section["items"][:3]:
            render_queue_card(record, gmail_user_index, "dashboard", state_path, seen_scope)

    if seen_records:
        with st.expander(f"Seen already ({len(seen_records)})", expanded=False):
            st.caption("These conversations are hidden from the active dashboard until the thread changes.")
            for record in seen_records[:10]:
                render_queue_card(record, gmail_user_index, "dashboard_seen", state_path, seen_scope)

def render_priority_view(
    records: list[dict[str, Any]],
    gmail_user_index: str,
    state_path: str,
    seen_scope: str,
    hidden_seen_count: int,
    order_mode: str,
) -> None:
    """Show the full queue, grouped into plain-language sections."""

    if hidden_seen_count > 0:
        st.caption(
            f"{hidden_seen_count} seen conversation(s) are hidden. Turn on the sidebar option if you want to review them again."
        )

    if order_mode == "Latest message first":
        ordered_records = sort_latest_first(records)
        st.markdown(f"**All fetched conversations ({len(ordered_records)})**")
        if not ordered_records:
            st.caption("No conversations match the current filters.")
            return
        st.caption("Sorted by the newest latest message first.")
        for record in ordered_records:
            render_queue_card(
                record,
                gmail_user_index,
                "latest_first",
                state_path,
                seen_scope,
            )
        return

    sections = build_priority_sections(records)
    for section in sections:
        st.markdown(f"**{section['title']} ({len(section['items'])})**")
        if not section["items"]:
            st.caption(section["empty"])
            continue
        for record in section["items"]:
            render_queue_card(
                record,
                gmail_user_index,
                section["title"].replace(" ", "_"),
                state_path,
                seen_scope,
            )


def render_thread_detail(
    records: list[dict[str, Any]],
    gmail_user_index: str,
    state_path: str,
    seen_scope: str,
) -> None:
    """Show one selected conversation in a way that makes the next step obvious."""

    if not records:
        st.info("No conversations match the current filters.")
        return

    selected_thread_id = st.session_state.get("selected_thread_id")
    selected_record = find_thread_by_id(records, str(selected_thread_id or "")) or records[0]
    selected_index = next(
        (
            index
            for index, record in enumerate(records)
            if record.get("id") == selected_record.get("id")
        ),
        0,
    )
    selected_label = f"{selected_record.get('subject') or '(No subject)'}"

    thread_labels = [
        f"{record.get('subject') or '(No subject)'}"
        for record in records
    ]
    chosen_label = st.selectbox(
        "Conversation",
        options=thread_labels,
        index=selected_index,
    )
    if chosen_label != selected_label:
        selected_record = records[thread_labels.index(chosen_label)]
        st.session_state["selected_thread_id"] = selected_record.get("id")

    priority = user_priority(selected_record)
    trust = trust_signal(selected_record)
    summary = user_friendly_summary(selected_record)
    next_step = next_step_label(selected_record)
    category_label = display_category(selected_record)
    reasons = why_it_matters(selected_record)
    seen_now = is_thread_seen(st.session_state["end_user_state"], selected_record, seen_scope)
    open_url, search_url = build_gmail_links(
        {
            "thread_id": selected_record.get("thread_id"),
            "sender": selected_record.get("latest_message_sender"),
            "participants": selected_record.get("participants"),
            "subject": selected_record.get("subject"),
        },
        gmail_user_index=gmail_user_index,
    )

    st.markdown(
        (
            "<div class='detail-hero'>"
            f"<h3 class='detail-subject'>{html.escape(selected_record.get('subject') or '(No subject)')}</h3>"
            f"<div class='detail-meta'>{html.escape(selected_record.get('participants_display') or 'Unknown participants')} | {html.escape(selected_record.get('latest_message_date') or 'Unknown date')} | Category: {html.escape(category_label)}</div>"
            "<div class='detail-pill-wrap'>"
            f"{tone_pill(str(priority['label']), str(priority['tone']))}"
            f"{tone_pill(str(trust['label']), str(trust['tone']))}"
            "</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    header_left, header_right = st.columns([1.35, 1], gap="large")
    with header_left:
        st.markdown("<div class='detail-grid-card'>", unsafe_allow_html=True)
        st.markdown("**Summary**")
        st.write(summary)
        st.markdown("**What matters now**")
        st.write(selected_record.get("predicted_status") or next_step)
        st.markdown("**Why this is in your queue**")
        for reason in reasons:
            st.write(f"- {reason}")
        st.markdown("</div>", unsafe_allow_html=True)
    with header_right:
        st.markdown("<div class='detail-grid-card'>", unsafe_allow_html=True)
        st.markdown("**Recommended next step**")
        st.write(next_step)
        st.caption(trust["caption"])
        st.markdown(f"**Category**: {category_label}")
        if seen_now:
            st.caption("You already marked this version as seen. It will come back if the conversation changes.")
        st.markdown(
            f"**People involved**: {selected_record.get('participants_full') or 'Unknown participants'}"
        )
        st.markdown(
            f"**Latest update**: `{selected_record.get('latest_message_date') or 'Unknown date'}`"
        )
        seen_label = "Show again on dashboard" if seen_now else "I've seen this"
        if st.button(
            seen_label,
            key=f"detail_seen_{selected_record['id']}",
            use_container_width=True,
        ):
            state_payload = st.session_state["end_user_state"]
            if seen_now:
                clear_thread_seen(state_payload, str(selected_record["id"]), seen_scope)
            else:
                mark_thread_seen(state_payload, selected_record, seen_scope)
            persist_seen_state(state_payload, state_path)
            if not seen_now:
                set_active_view("Dashboard")
            st.rerun()
        if open_url:
            st.markdown(f"[Open this thread in Gmail]({open_url})")
        st.markdown(f"[Search this conversation in Gmail]({search_url})")
        st.divider()
        st.markdown("**Reply draft**")
        if selected_record.get("security_status") == "classified":
            st.caption(
                "Draft creation is disabled for sensitive or classified threads."
            )
        else:
            if selected_record.get("should_draft_reply"):
                st.caption(
                    "Generate a ready-to-edit reply when you are ready."
                )
                if selected_record.get("draft_needs_date"):
                    st.caption(
                        selected_record.get("draft_date_reason")
                        or "This draft likely needs a date."
                    )
                if selected_record.get("draft_needs_attachment"):
                    st.caption(
                        selected_record.get("draft_attachment_reason")
                        or "This draft may need attachment context."
                    )
            else:
                st.caption(
                    "AI does not think email is the main next step, but you can still create a draft."
                )
            if st.button(
                "Create Draft",
                key=f"detail_create_draft_{selected_record['id']}",
                use_container_width=True,
            ):
                open_draft_wizard(selected_record)
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("**Conversation timeline**")
    messages = list(selected_record.get("messages", []))
    for index, message in enumerate(messages):
        is_latest = index == len(messages) - 1
        container_class = "timeline-card timeline-latest" if is_latest else "timeline-card"
        st.markdown(f"<div class='{container_class}'>", unsafe_allow_html=True)
        st.markdown(
            f"**{message.get('sender') or 'Unknown sender'}**  \n"
            f"`{message.get('date') or 'Unknown date'}`"
        )
        st.markdown(f"**Subject:** {message.get('subject') or '(No subject)'}")
        if message.get("snippet"):
            st.markdown(f"**Snippet:** {message.get('snippet')}")
        if message.get("cleaned_body"):
            st.markdown(f"**Body:** {(message.get('cleaned_body') or '')[:700]}")
        st.markdown("</div>", unsafe_allow_html=True)

    if active_draft_wizard_for_record(selected_record) is not None:
        render_draft_wizard_modal(selected_record)


def render_review_mode(records: list[dict[str, Any]], review_output_path: str) -> None:
    """Offer a simpler correction view for business users."""

    if not records:
        st.info("No conversations are available for feedback with the current filters.")
        return

    reviews_by_thread: dict[str, dict[str, Any]] = st.session_state["end_user_review_results"]
    selected_thread_id = st.session_state.get("selected_thread_id") or records[0].get("id")
    selected_record = find_thread_by_id(records, str(selected_thread_id)) or records[0]
    existing_review = reviews_by_thread.get(str(selected_record["id"]), {})

    helpful_default = existing_review.get("ai_result_correct")
    summary_default = existing_review.get("summary_useful")
    action_default = existing_review.get("next_action_useful")
    reply_default = existing_review.get("reply_draft_useful")
    notes_default = existing_review.get("notes", "")
    merge_default = existing_review.get("merge_correct", "N/A")
    belongs_default = {
        "Yes": "No",
        "No": "Yes",
        "N/A": "Not sure",
    }.get(existing_review.get("should_have_been_filtered", "N/A"), "Not sure")

    st.markdown("**Light review mode**")
    st.caption(
        "This is a business-friendly feedback screen. Use it to tell the system whether the thread was useful, clear, and worth surfacing."
    )

    thread_labels = [record.get("subject") or "(No subject)" for record in records]
    current_index = next(
        (
            index
            for index, record in enumerate(records)
            if record.get("id") == selected_record.get("id")
        ),
        0,
    )
    chosen_label = st.selectbox(
        "Conversation to review",
        options=thread_labels,
        index=current_index,
        key="end_user_review_thread",
    )
    if chosen_label != (selected_record.get("subject") or "(No subject)"):
        selected_record = records[thread_labels.index(chosen_label)]
        existing_review = reviews_by_thread.get(str(selected_record["id"]), {})
        helpful_default = existing_review.get("ai_result_correct")
        summary_default = existing_review.get("summary_useful")
        action_default = existing_review.get("next_action_useful")
        reply_default = existing_review.get("reply_draft_useful")
        notes_default = existing_review.get("notes", "")
        merge_default = existing_review.get("merge_correct", "N/A")
        belongs_default = {
            "Yes": "No",
            "No": "Yes",
            "N/A": "Not sure",
        }.get(existing_review.get("should_have_been_filtered", "N/A"), "Not sure")
        st.session_state["selected_thread_id"] = selected_record.get("id")

    with st.form(f"review_form_{selected_record['id']}"):
        helpful = st.selectbox(
            "Was this card helpful overall?",
            options=["Not sure"] + HELPFUL_OPTIONS,
            index=(["Not sure"] + HELPFUL_OPTIONS).index(helpful_default)
            if helpful_default in HELPFUL_OPTIONS
            else 0,
        )
        summary_helpful = st.selectbox(
            "Was the summary easy to understand?",
            options=["Not sure"] + HELPFUL_OPTIONS,
            index=(["Not sure"] + HELPFUL_OPTIONS).index(summary_default)
            if summary_default in HELPFUL_OPTIONS
            else 0,
        )
        next_action_helpful = st.selectbox(
            "Was the recommended next step useful?",
            options=["Not sure"] + HELPFUL_OPTIONS,
            index=(["Not sure"] + HELPFUL_OPTIONS).index(action_default)
            if action_default in HELPFUL_OPTIONS
            else 0,
        )
        queue_belongs = st.selectbox(
            "Did this conversation belong in the queue?",
            options=QUEUE_BELONGS_OPTIONS,
            index=QUEUE_BELONGS_OPTIONS.index(belongs_default)
            if belongs_default in QUEUE_BELONGS_OPTIONS
            else 2,
        )
        merge_check = "Not sure"
        if len(selected_record.get("source_thread_ids", [])) > 1:
            merge_check = st.selectbox(
                "Were the grouped emails combined correctly?",
                options=MERGE_CHECK_OPTIONS,
                index=MERGE_CHECK_OPTIONS.index(
                    "Yes" if merge_default == "Yes" else "No" if merge_default == "No" else "Not sure"
                ),
            )
        reply_helpful = "Not sure"
        if selected_record.get("should_draft_reply"):
            reply_helpful = st.selectbox(
                "Was the draft suggestion helpful?",
                options=["Not sure"] + HELPFUL_OPTIONS,
                index=(["Not sure"] + HELPFUL_OPTIONS).index(reply_default)
                if reply_default in HELPFUL_OPTIONS
                else 0,
            )

        notes = st.text_area(
            "Anything we should improve?",
            value=notes_default,
            height=120,
        )
        submitted = st.form_submit_button("Save feedback", use_container_width=True)

    if submitted:
        should_have_been_filtered = {
            "Yes": "No",
            "No": "Yes",
            "Not sure": "N/A",
        }[queue_belongs]
        merge_correct = {
            "Yes": "Yes",
            "No": "No",
            "Not sure": "N/A",
        }[merge_check]
        improvement_tags: list[str] = []
        if queue_belongs == "No":
            improvement_tags.append("email should have been filtered out")
            improvement_tags.append("AI should not have covered this")
        if queue_belongs == "Yes" and str(selected_record.get("analysis_status") or "").strip().lower() in {"not_requested", "skipped"}:
            improvement_tags.append("email should not have been filtered out")
            improvement_tags.append("AI should have covered this")
        if merge_check == "No":
            improvement_tags.append("merge incorrect")

        upsert_review_result(
            reviews_by_thread,
            str(selected_record["id"]),
            {
                "ai_result_correct": helpful if helpful in HELPFUL_OPTIONS else None,
                "merge_correct": merge_correct,
                "summary_useful": summary_helpful if summary_helpful in HELPFUL_OPTIONS else None,
                "next_action_useful": next_action_helpful if next_action_helpful in HELPFUL_OPTIONS else None,
                "reply_draft_useful": reply_helpful if reply_helpful in HELPFUL_OPTIONS else None,
                "should_have_been_filtered": should_have_been_filtered,
                "notes": notes,
                "improvement_tags": improvement_tags,
            },
        )
        save_review_results(reviews_by_thread, review_output_path)
        st.session_state["end_user_review_results"] = reviews_by_thread
        st.success("Feedback saved. It will also be visible in the technical review app.")


def main() -> None:
    st.set_page_config(page_title="Daily Email Assistant", layout="wide")
    apply_end_user_styles()

    review_output_path = DEFAULT_REVIEW_OUTPUT_PATH
    account_output_path = DEFAULT_ACCOUNT_OUTPUT_PATH
    state_output_path = DEFAULT_END_USER_STATE_PATH

    if (
        "end_user_review_results_path" not in st.session_state
        or st.session_state["end_user_review_results_path"] != review_output_path
    ):
        st.session_state["end_user_review_results_path"] = review_output_path
        st.session_state["end_user_review_results"] = load_review_results(review_output_path)

    if (
        "end_user_gmail_accounts_path" not in st.session_state
        or st.session_state["end_user_gmail_accounts_path"] != account_output_path
    ):
        st.session_state["end_user_gmail_accounts_path"] = account_output_path
        st.session_state["end_user_gmail_accounts"] = load_gmail_accounts(account_output_path)

    if (
        "end_user_state_path" not in st.session_state
        or st.session_state["end_user_state_path"] != state_output_path
    ):
        st.session_state["end_user_state_path"] = state_output_path
        st.session_state["end_user_state"] = load_end_user_state(state_output_path)

    if "end_user_active_view" not in st.session_state:
        st.session_state["end_user_active_view"] = "Dashboard"

    if "end_user_view_selector" not in st.session_state:
        st.session_state["end_user_view_selector"] = st.session_state["end_user_active_view"]

    requested_view = st.session_state.pop("end_user_requested_view", None)
    if requested_view in VIEW_OPTIONS:
        st.session_state["end_user_active_view"] = requested_view
        st.session_state["end_user_view_selector"] = requested_view

    st.title("Daily Email Assistant")
    st.caption("Start with what needs attention, understand the situation quickly, then open Gmail only when you need to act.")

    st.sidebar.header("Inbox")
    account_data = st.session_state["end_user_gmail_accounts"]
    account_names = [item.get("name") for item in account_data.get("accounts", []) if item.get("name")]
    active_account = account_data.get("active_account")
    active_record: dict[str, Any] = {}
    if account_names:
        selected_account = st.sidebar.selectbox(
            "Gmail account",
            options=account_names,
            index=account_names.index(active_account) if active_account in account_names else 0,
        )
        if selected_account != active_account:
            account_data["active_account"] = selected_account
            st.session_state["end_user_gmail_accounts"] = account_data
        active_record = next(
            (item for item in account_data.get("accounts", []) if item.get("name") == selected_account),
            {},
        )
        st.sidebar.caption(
            f"Connected as: {active_record.get('email_address') or selected_account}"
        )
    else:
        st.sidebar.caption("No saved Gmail account profile was found. The app will use the default token file.")

    backend_process = st.session_state.get("end_user_backend_process")
    backend_running = backend_process is not None and backend_process.poll() is None

    if backend_running:
        render_loading_button()
    elif st.sidebar.button("Refresh inbox", use_container_width=True):
        token_path = active_record.get("token_path")
        process, message = _launch_backend_pipeline(token_path=token_path)
        if process is not None:
            st.session_state["end_user_backend_process"] = process
            st.session_state["end_user_backend_started_at"] = datetime.now(timezone.utc).isoformat()
            st.sidebar.success(message)
            st.rerun()
        st.sidebar.error(message)

    if not backend_running and "end_user_last_backend_exit_code" in st.session_state:
        st.sidebar.success(
            f"Last refresh finished with code {st.session_state['end_user_last_backend_exit_code']}."
        )

    focus_filter = st.sidebar.radio(
        "Show",
        options=[
            "All conversations",
            "Needs attention today",
            "Review soon",
            "Watch list",
            "Manual only",
            "FYI / done",
        ],
    )
    search_text = st.sidebar.text_input(
        "Search conversations",
        placeholder="Subject, people, summary, next step...",
    )
    order_mode = st.sidebar.selectbox(
        "Order",
        options=ORDER_OPTIONS,
        index=0,
    )
    show_seen_conversations = st.sidebar.checkbox(
        "Show conversations I've already seen",
        value=False,
        help="Dashboard always hides seen conversations until the thread changes.",
    )

    active_gmail_user_index = str(active_record.get("gmail_user_index", "0")) if active_record else "0"
    seen_scope = end_user_scope(active_record)
    run_data = load_pipeline_output("data/outputs/latest_run.json")

    if backend_running:
        render_loading_queue()
        return

    if "end_user_last_backend_exit_code" in st.session_state:
        st.success("Inbox refreshed. The latest results are now loaded.")
        st.session_state.pop("end_user_last_backend_exit_code", None)

    if not run_data:
        st.warning("No queue data is available yet. Refresh the inbox to build the first thread list.")
        render_skeleton_cards(3)
        return

    records = build_unified_records(run_data)
    category_options = ["All categories"] + sorted(
        {display_category(record) for record in records}
    )
    category_filter = st.sidebar.selectbox(
        "Category",
        options=category_options,
        index=0,
    )
    all_filtered_records = filter_end_user_records(
        records,
        focus_filter,
        search_text,
        category_filter,
    )
    ordered_filtered_records = (
        sort_latest_first(all_filtered_records)
        if order_mode == "Latest message first"
        else sort_for_end_user(all_filtered_records)
    )
    seen_records = build_seen_records(
        ordered_filtered_records,
        st.session_state["end_user_state"],
        seen_scope,
    )
    dashboard_records = build_dashboard_records(
        ordered_filtered_records,
        st.session_state["end_user_state"],
        seen_scope,
    )
    hidden_seen_count = len(seen_records)
    visible_priority_records = (
        ordered_filtered_records if show_seen_conversations else dashboard_records
    )

    st.radio(
        "View",
        options=VIEW_OPTIONS,
        horizontal=True,
        key="end_user_view_selector",
        label_visibility="collapsed",
    )

    active_view = st.session_state["end_user_view_selector"]
    st.session_state["end_user_active_view"] = active_view

    if active_view == "Dashboard":
        render_dashboard(
            run_data,
            dashboard_records,
            seen_records,
            active_gmail_user_index,
            state_output_path,
            seen_scope,
            hidden_seen_count,
        )
    elif active_view == "Priority View":
        st.subheader("Priority queue")
        st.caption("Work from top to bottom. The highest-confidence action items are shown first.")
        render_priority_view(
            visible_priority_records,
            active_gmail_user_index,
            state_output_path,
            seen_scope,
            hidden_seen_count if not show_seen_conversations else 0,
            order_mode,
        )
    elif active_view == "Thread Detail":
        st.subheader("Conversation detail")
        st.caption("Use this view when you want the full context before opening Gmail.")
        render_thread_detail(
            ordered_filtered_records,
            active_gmail_user_index,
            state_output_path,
            seen_scope,
        )
    else:
        st.subheader("Review mode")
        render_review_mode(ordered_filtered_records, review_output_path)


if __name__ == "__main__":
    main()
