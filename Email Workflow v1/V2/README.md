# AI-Assisted Gmail Triage V2

This V2 keeps the same local-first Python structure as V1, but the main unit is now a Gmail thread instead of a single email.

One review card now equals one conversation thread.
One summary now equals one thread summary.
One category and urgency decision now apply to the thread as a whole.

V1 remains untouched in its own folder and acts as the baseline.

## What V2 Achieves Today

Today, V2 provides a repeatable Gmail thread triage workflow that:

1. classifies Gmail threads
2. summarizes priorities at the thread and executive level
3. identifies the current status of each conversation
4. surfaces the latest useful next action
5. drafts reply suggestions for threads that need a response
6. tracks follow-ups in the daily review flow

## What Changed In V2

V2 still:

1. Reads recent Gmail data in read-only mode.
2. Uses the OpenAI Agents SDK when AI mode is enabled.
3. Produces an executive summary.
4. Saves results to JSON.
5. Includes the Streamlit review UI.

The main difference is that V2:

1. fetches Gmail messages
2. groups them by `thread_id`
3. builds one thread record per conversation
4. summarizes and classifies the full thread
5. keeps child messages nested inside the thread

## Thread Record Shape

Each main thread record includes:

- `thread_id`
- `subject`
- `participants`
- `message_count`
- `latest_message_date`
- `messages`
- `combined_thread_text`
- `predicted_category`
- `predicted_urgency`
- `predicted_summary`
- `predicted_status`
- `predicted_next_action`
- `should_draft_reply`
- `predicted_reply_subject`
- `predicted_reply_body`
- CRM fields when relevant
- filtering and relevance fields used by the review UI

Each child message includes:

- `message_id`
- `sender`
- `subject`
- `date`
- `snippet`
- `cleaned_body`

## Folder Structure

```text
V2/
  README.md
  requirements.txt
  .env.example
  .gitignore
  app.py
  config.py
  gmail_client.py
  schemas.py
  prompts.py
  agents/
    __init__.py
    triage_agent.py
    summary_agent.py
    crm_agent.py
    reply_draft_agent.py
    manager_agent.py
  services/
    __init__.py
    email_service.py
    formatter.py
    metrics.py
    review_store.py
  data/raw/
  data/outputs/
  tests/
    __init__.py
    test_smoke.py
    test_email_service.py
    test_metrics.py
    test_review_store.py
```

## Output

The backend writes the final V2 JSON to:

```text
V2/data/outputs/latest_run.json
```

The top-level output is now thread-based:

- `thread_count`
- `message_count`
- `ai_thread_count`
- `filtered_thread_count`
- `threads`
- `summary`
- `errors`

## Gmail Review UI

The review UI now shows:

- one expandable card per thread
- subject, participants, message count, and latest message date
- predicted category, urgency, summary, status, and next action
- optional reply draft suggestion when a thread likely needs a response
- nested child messages in order
- thread-level manual review controls
- Gmail links for the thread
- best-effort links for child messages

Main Gmail actions:

- `Open in Gmail` opens the thread using `thread_id`
- `Search in Gmail` falls back to a Gmail search query

## Setup

From the repository root:

1. Create and activate a virtual environment if needed.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

2. Install dependencies.

```powershell
pip install -r V2\requirements.txt
```

3. Copy the environment file if needed.

```powershell
Copy-Item V2\.env.example V2\.env
```

4. Fill in the Gmail and OpenAI settings in `V2\.env`.

Notes:

- `GMAIL_THREAD_SOURCE` controls which messages seed the thread list:
  - `anywhere`
  - `sent`
  - `received`
- `GMAIL_MAX_RESULTS` still controls how many Gmail messages are fetched before grouping.
- `AI_MAX_EMAILS` is still the environment variable name for simplicity, but in V2 it now limits how many threads are sent to AI.
- When `GMAIL_THREAD_SOURCE` is `sent` or `received`, V2 still expands each selected result into the full Gmail thread so child sent and received messages remain visible together.

## Run The Backend

From the repository root:

```powershell
python V2\app.py
```

## Run The Review UI

From the repository root:

```powershell
streamlit run V2\review_app.py
```

In the review sidebar, use the `Thread source` toggle to switch between:

- `Anywhere`
- `Sent`
- `Received`

## Run The End-User UI

For the non-technical day-to-day queue:

```powershell
streamlit run V2\end_user_app.py
```

This view is designed for a PO / operations user and focuses on:

- what needs attention today
- what should be reviewed soon
- what can stay as FYI
- the recommended next step for each thread
