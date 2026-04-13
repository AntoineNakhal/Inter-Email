# AI-Assisted Gmail Triage V1

This project is a minimal but real Python V1 for reading recent Gmail messages in read-only mode, classifying them with the OpenAI Agents SDK, generating an executive summary, extracting CRM-ready fields, and saving the final result to JSON.

The goal is to keep the code simple, local-first, and easy for an intern to understand and extend.

## Folder Structure

```text
v1/
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
    manager_agent.py
  services/
    __init__.py
    email_service.py
    formatter.py
  data/raw/
  data/outputs/
  tests/
    __init__.py
    test_smoke.py
```

## Project Purpose

This V1 does four things:

1. Reads a small batch of recent Gmail messages using the Gmail API with read-only access.
2. Uses the OpenAI Agents SDK to classify emails into five business categories.
3. Produces an executive summary and top priorities.
4. Extracts CRM-ready structured fields for future HubSpot integration.

The final output is written to:

```text
v1/data/outputs/latest_run.json
```

## Setup Steps

1. Create and activate a virtual environment.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

2. Install dependencies.

```powershell
pip install -r v1\requirements.txt
```

3. Copy the example environment file.

```powershell
Copy-Item v1\.env.example v1\.env
```

4. Fill in the values in `v1/.env`.

At minimum you will need:

- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `GMAIL_CREDENTIALS_FILE`
- `GMAIL_TOKEN_FILE`

## How To Add Gmail OAuth Credentials

This project uses the Gmail API in **read-only** mode.

1. Go to the Google Cloud Console.
2. Create or select a project.
3. Enable the Gmail API.
4. Configure the OAuth consent screen.
5. Create **Desktop app** OAuth credentials.
6. Download the OAuth client JSON file.
7. Place that file somewhere local, for example:

```text
v1/data/raw/google_credentials.json
```

8. Set `GMAIL_CREDENTIALS_FILE` in `v1/.env` to that path.

The first time you run the app, Google will open the browser-based OAuth flow. After consent, a token file will be created at the path from `GMAIL_TOKEN_FILE`.

Important:

- Do not commit your credentials file.
- Do not commit your token file.
- This V1 does not perform any Gmail write actions.

## How To Run The App

From the repository root:

```powershell
python v1\app.py
```

## What Output To Expect

The app saves a JSON file to `v1/data/outputs/latest_run.json`.

That file includes:

- metadata about the run
- the recent emails that were fetched
- triage results for each email
- an executive summary
- CRM-ready extracted records for future HubSpot work

## Notes About Placeholders

This is a real scaffold, but a few pieces still depend on your local setup:

- You must provide your own Google OAuth client credentials.
- You must provide your own OpenAI API key.
- The first Gmail OAuth login is interactive.
- The quality of classification depends on the model you choose and the emails in your mailbox.

## Review UI (Streamlit)

This repository now includes a local evaluation interface to review AI output quality.

### Purpose

The review UI helps you:

- inspect each processed email
- compare AI predictions vs human judgment
- save manual evaluations
- track accuracy and common error patterns over time

### Files Added For Review Layer

- `review_app.py`
- `services/review_store.py`
- `services/metrics.py`

### Where Review Results Are Stored

Manual review data is persisted to:

```text
data/outputs/review_results.json
```

The app autosaves changes and also includes a **Save all reviews** action.

Gmail account profiles used by review deep links are stored at:

```text
data/outputs/gmail_accounts.json
```

Use the sidebar to add account profiles and switch the active account (`u/0`, `u/1`, etc.).

### Gmail Deep Linking

Each email card includes:

- **Open in Gmail** (best direct deep link)
- **Search in Gmail** (fallback)

Link logic:

1. use `thread_id` if available
2. otherwise use `id`
3. always provide a search link using sender + subject

### Metrics In The UI

The top section displays:

- total fetched / filtered / sent to AI / fallback used
- reviewed / correct / incorrect
- category accuracy %
- urgency accuracy %
- summary usefulness %

`Partially` is treated as `0.5` for usefulness percentages.

The review form also includes `Should this email have been filtered out before AI?`
so you can audit filtering quality for emails that were not filtered.

### Run Command

From the project root:

```powershell
streamlit run review_app.py
```
