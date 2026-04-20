# V3 Architecture Recommendation

## Why V2 Needs A Product Refactor

The current V2 implementation proves the workflow, but it is still a prototype architecture:

- `review_app.py` and `end_user_app.py` import backend code directly instead of consuming an API.
- `TriageManager` owns too many concerns at once: Gmail fetch, grouping, AI orchestration, caching, fallbacks, and output writing.
- Gmail and OpenAI integrations are instantiated inside product logic instead of behind provider interfaces.
- Runtime state is stored as JSON under the app folder, which is fine for a prototype but not a clean deployment boundary.
- The UI and pipeline are coupled to local scripts instead of a reusable backend service.

V3 should keep the good parts of V2, especially the thread-centric workflow, but repackage them into a deployable product shape.

## A. Recommended Architecture

Use a modular monorepo with:

1. One frontend web app.
2. One backend API service.
3. Internal backend layers for application logic, domain logic, providers, and persistence.
4. One shared API contract.
5. One runtime data directory for local-first development and self-hosting.

The most practical shape for this project is:

- `frontend` is a separate React app.
- `api` is the HTTP boundary built with FastAPI.
- `backend` is an importable Python package used by `api` and later by background jobs.
- `shared/openapi` stores the API contract that the frontend can generate types from.
- `data` stores the runtime database, cache, and exports and can become a mounted volume later.

Important design decision:

Do not split `api` and `backend` into separate deployed network services yet.

For V3, `api` and `backend` should be separate code layers but one deployed backend service. That gives you clean architecture without early operational complexity.

## Recommended Stack

This stack fits your current Python codebase and your deployment goals:

- Frontend: React + TypeScript + Vite
- Client data fetching: TanStack Query
- Routing: React Router
- Backend API: FastAPI
- Validation: Pydantic
- Persistence: SQLAlchemy 2.x + Alembic
- Local database first: SQLite
- Production database later: Postgres
- AI provider integrations: your own provider interface plus OpenAI implementation first
- Deployment: Docker Compose first, container-friendly from day one

Why this is the right level:

- It keeps Python for the Gmail and AI-heavy backend work you already have.
- It gives you a real frontend instead of coupling UI to Python scripts.
- It keeps local setup simple.
- It gives you a straight migration path from SQLite to Postgres and from OpenAI to local AI.

## B. Recommended Folder Structure

```text
V3/
  README.md
  .env.example
  docs/
    architecture.md

  frontend/
    src/
      app/
        providers/
        router/
      routes/
        inbox/
        thread-detail/
        review/
        settings/
      components/
        ui/
        layout/
      features/
        inbox/
        threads/
        drafts/
        review/
        settings/
      hooks/
      lib/
      api/
        client/
        queries/
      types/

  api/
    app/
      main.py
      dependencies/
        auth.py
        db.py
        providers.py
      routers/
        health.py
        sync.py
        threads.py
        review.py
        drafts.py
        settings.py
      schemas/
        thread.py
        review.py
        draft.py
        sync.py
    tests/
      test_health.py
      test_threads.py

  backend/
    core/
      config.py
      logging.py
      security.py
    application/
      gmail_sync_service.py
      thread_analysis_service.py
      queue_service.py
      review_service.py
      draft_service.py
      crm_service.py
    domain/
      thread.py
      analysis.py
      review.py
      draft.py
      policies.py
    providers/
      ai/
        base.py
        registry.py
        router.py
        openai_provider.py
        ollama_provider.py
      gmail/
        client.py
        mapper.py
    persistence/
      models/
        thread.py
        analysis.py
        review.py
        sync_run.py
      repositories/
        thread_repository.py
        analysis_repository.py
        review_repository.py
        draft_repository.py
      migrations/
    jobs/
      sync_runner.py
      analysis_runner.py

  shared/
    openapi/
      openapi.json

  infra/
    docker/
      api.Dockerfile
      frontend.Dockerfile
    compose/
      docker-compose.local.yml
      docker-compose.selfhost.yml

  data/
    sqlite/
    cache/
    exports/
```

## C. Responsibilities Per Layer

### Frontend

Frontend should own:

- pages, routes, navigation
- reusable UI components
- feature-specific UI modules
- client state and server-state queries
- forms and local interaction logic
- API client calls
- route-level permissions and display logic

Frontend should not own:

- Gmail access
- AI calls
- business rules for queueing, review, drafting, or thread grouping
- direct file reads or writes

Practical recommendation:

Build one frontend app with route sections for the internal review UI and the end-user queue UI. Do not build two separate frontends unless the product truly splits later.

### API

The API layer should own:

- HTTP routes
- request parsing
- response serialization
- auth/session boundary
- input validation at the transport layer
- dependency injection
- error mapping into HTTP responses

The API should not contain business logic. Its job is to translate HTTP requests into calls to backend application services.

### Backend Application Layer

This is your use-case and orchestration layer.

It should own:

- sync workflows
- thread refresh orchestration
- review queue logic
- draft generation workflow
- permission and safety checks
- task coordination across repositories and providers

This is the place where "what the product does" lives.

Examples:

- `GmailSyncService`
- `ThreadAnalysisService`
- `DraftService`
- `ReviewService`
- `QueueService`

### Domain Layer

The domain layer should own the business language of the app:

- thread
- message
- review decision
- draft request
- analysis result
- relevance rules
- review policies
- classification and ranking policies

This layer should be mostly pure logic and data structures. It should not know about FastAPI, Gmail SDKs, OpenAI SDKs, or SQLAlchemy.

### Persistence Layer

The persistence layer should own:

- database models
- repository implementations
- database sessions
- migrations
- cache storage
- export writers

The important rule is:

application services talk to repositories, not directly to SQLite, JSON, or SQLAlchemy queries.

This gives you the path:

- SQLite now
- Postgres later
- optional caching later
- optional object storage later

without rewriting the business layer.

### AI Provider Layer

This layer should isolate vendor-specific behavior.

It should own:

- provider SDK calls
- provider authentication
- model selection
- provider-specific structured output parsing
- retries and timeouts at the provider boundary

The rest of the backend should depend on an interface you own, not on the OpenAI SDK.

### Shared Contract Layer

Because your frontend and backend are in different languages, do not try to share raw source types across both.

Instead:

- make the backend API schema the source of truth
- expose OpenAPI from FastAPI
- generate frontend types or client helpers from that schema

That is the cleanest cross-language "shared types" strategy for this project.

## D. Deployment-Friendly Design Choices

### 1. Environment-Based Configuration

All environment-dependent behavior should come from env vars:

- API host and port
- frontend API base URL
- database URL
- Gmail credential locations
- AI provider selection
- provider-specific model names
- storage paths

This keeps local, self-hosted, and cloud deployments aligned.

### 2. One Backend Service, Not Microservices

For V3, keep deployment simple:

- one frontend app
- one backend service
- one database

Later, if sync or analysis becomes slow, you can add a worker process that imports the same `backend` package. That is much safer than starting with multiple services now.

### 3. API-First UI

The frontend should only talk to the API. It should never import backend files, read JSON output files, or call vendor SDKs directly.

This single decision removes most future deployment pain.

### 4. Runtime Data Outside Source Code Logic

In V2, runtime JSON lives under the app code. In V3, runtime data should live under `V3/data` in local mode and be mounted as a volume in containers.

Recommended runtime shape:

- `data/sqlite/app.db`
- `data/cache/`
- `data/exports/`

### 5. SQLite First, Postgres Later

Start with:

- `DATABASE_URL=sqlite:///./data/sqlite/app.db`

Later switch to:

- `DATABASE_URL=postgresql+psycopg://...`

The application and domain code should not change if repositories are respected.

### 6. Container-Friendly From Day One

Even before full deployment, structure the code so it is easy to containerize:

- frontend has its own build context
- backend API has its own build context
- data paths are mountable
- config comes from env vars

### 7. Provider-Agnostic AI Routing

The system should decide which provider handles each AI task via config, not hard-coded imports.

Examples:

- thread analysis uses OpenAI first
- reply drafting uses OpenAI first
- CRM extraction uses OpenAI first
- later, one or more of those can be switched to Ollama or another local model

## E. Concrete Refactor Plan

### Phase 1: Freeze V2 As The Working Reference

Do not keep reshaping V2 forever. Treat it as the reference workflow you are extracting from.

### Phase 2: Scaffold V3

Create the V3 folder layout and config baseline first:

- frontend
- api
- backend
- shared
- infra
- data

This phase is mostly structure, not feature work.

### Phase 3: Extract Core Domain Models

Split the giant `V2/schemas.py` into:

- backend domain models
- API request and response schemas
- persistence models

Keep the concepts, but stop using one giant schema file for every layer.

### Phase 4: Move Gmail Logic Behind A Provider

Refactor:

- `V2/gmail_client.py`
- part of `V2/services/email_service.py`

into:

- `backend/providers/gmail/client.py`
- `backend/application/gmail_sync_service.py`
- `backend/domain/thread.py`

The Gmail provider fetches raw data.
The application service coordinates sync.
The domain layer defines what a thread means.

### Phase 5: Replace JSON Output Files With Repositories

Current JSON-backed files:

- `review_results.json`
- `gmail_accounts.json`
- `thread_cache.json`
- `end_user_state.json`
- `backend_progress.json`

should become repository-backed state.

Recommended minimum persistence tables:

- `gmail_accounts`
- `gmail_messages`
- `email_threads`
- `thread_analyses`
- `review_decisions`
- `drafts`
- `sync_runs`

You can keep JSON export support for debugging and offline snapshots, but not as the primary app state.

### Phase 6: Introduce The AI Provider Interface

Refactor:

- `V2/agents/*.py`
- OpenAI-specific orchestration in `TriageManager`

into:

- `backend/providers/ai/base.py`
- `backend/providers/ai/openai_provider.py`
- `backend/application/thread_analysis_service.py`
- `backend/application/draft_service.py`
- `backend/application/crm_service.py`

Important recommendation:

Do not carry the V2 "agent per task file" pattern directly into V3.

Instead, model AI around product tasks:

- analyze thread
- summarize queue
- draft reply
- extract CRM fields

This makes provider switching much easier than tying the system to one SDK's agent concept.

### Phase 7: Build The API

Replace script entrypoints with routes:

- `POST /sync`
- `GET /threads`
- `GET /threads/{id}`
- `POST /threads/{id}/review`
- `POST /threads/{id}/draft`
- `GET /queue`

The API becomes the stable boundary for the frontend and later deployments.

### Phase 8: Build The Frontend

Replace `review_app.py` and `end_user_app.py` with one frontend app:

- `/inbox`
- `/threads/:threadId`
- `/review`
- `/drafts`

The frontend should consume the API contract only.

### Phase 9: Add Background Execution Without Overengineering

At first, sync and analysis can run:

- synchronously for local development
- or as backend jobs triggered by API endpoints

Later, if needed, move job runners into a separate worker process that imports the same `backend` package. No business-logic rewrite should be required.

### Phase 10: Add Local AI Later

Once you are ready for self-hosted AI:

- add `OllamaProvider` or another local provider
- map selected tasks to that provider through config
- keep application services unchanged

## F. AI Provider Strategy

This is the most important architectural boundary for your next version.

### Principle

Core backend logic should never call `OpenAI()` directly.

Instead:

- application services depend on an `AIProvider` interface
- provider implementations handle vendor details
- provider routing is configuration-driven

### Recommended Interface

Use task-oriented methods, not vendor-oriented methods.

Example:

```python
from typing import Protocol

class AIProvider(Protocol):
    name: str

    async def analyze_thread(self, request: ThreadAnalysisRequest) -> ThreadAnalysisResult:
        ...

    async def summarize_queue(self, request: QueueSummaryRequest) -> QueueSummaryResult:
        ...

    async def draft_reply(self, request: DraftReplyRequest) -> DraftReplyResult:
        ...

    async def extract_crm(self, request: CRMExtractionRequest) -> CRMExtractionResult:
        ...
```

Why this is better than a raw `generate(prompt)` wrapper:

- your business layer stays explicit
- each task can have its own schema
- each task can move to a different provider later
- tests are easier because you can mock task-level behavior

### Provider Implementations

Start with:

- `OpenAIProvider`

Prepare for:

- `OllamaProvider`
- `LocalAIProvider`
- `RemoteInferenceProvider`

Each provider implementation should translate your internal task request into whatever that provider needs.

### Provider Registry And Task Routing

Use a small registry and a router:

- registry resolves provider instances
- router decides which provider handles each task

For example:

- `thread_analysis -> openai`
- `queue_summary -> openai`
- `draft_reply -> openai`
- `crm_extraction -> openai`

Later:

- `thread_analysis -> ollama`
- `draft_reply -> openai`

That lets you move the cheap or local-safe tasks first without forcing a big-bang migration.

### Configuration Model

Use env vars such as:

```text
AI_DEFAULT_PROVIDER=openai
AI_THREAD_ANALYSIS_PROVIDER=openai
AI_QUEUE_SUMMARY_PROVIDER=openai
AI_DRAFT_PROVIDER=openai
AI_CRM_PROVIDER=openai

OPENAI_API_KEY=...
OPENAI_MODEL_THREAD_ANALYSIS=gpt-4.1-mini
OPENAI_MODEL_QUEUE_SUMMARY=gpt-4.1-mini
OPENAI_MODEL_DRAFT=gpt-4.1
OPENAI_MODEL_CRM=gpt-4.1-mini

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL_THREAD_ANALYSIS=llama3.1:8b
```

This is simple, explicit, and deployment-friendly.

### Fallback Behavior

Fallback should be defined per task, not as one global rule.

Recommended fallback policy:

- thread analysis: use deterministic heuristics or mark for manual review
- queue summary: build a deterministic summary from existing ranked threads
- draft generation: use a safe template-based fallback
- CRM extraction: return partial/empty structured output instead of blocking the app

Also persist metadata for each AI result:

- provider name
- model name
- prompt or policy version
- generated at timestamp
- success or fallback status

This gives you traceability when you compare OpenAI and local models later.

## Suggested V2 To V3 File Mapping

```text
V2/app.py
  -> V3/api/app/main.py
  -> V3/backend/jobs/sync_runner.py

V2/review_app.py
V2/end_user_app.py
  -> V3/frontend/src/routes/*

V2/gmail_client.py
  -> V3/backend/providers/gmail/client.py

V2/services/email_service.py
  -> V3/backend/application/gmail_sync_service.py
  -> V3/backend/domain/thread.py

V2/services/draft_workflow.py
  -> V3/backend/application/draft_service.py

V2/services/review_store.py
V2/services/end_user_state.py
V2/services/thread_cache.py
V2/services/progress_state.py
  -> V3/backend/persistence/repositories/*

V2/agents/*.py
  -> V3/backend/providers/ai/*
  -> V3/backend/application/*_service.py
```

## Bottom-Line Recommendation

The best V3 architecture for this project is:

- one React frontend
- one FastAPI backend service
- one importable Python backend core
- one repository-based persistence layer
- one provider-agnostic AI abstraction
- one local-first runtime data volume

That is the right balance between:

- not overengineering
- being production-oriented
- being deployable
- being ready for self-hosted AI later

without forcing a rewrite when you grow.
