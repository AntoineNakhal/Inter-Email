# V3 Product Architecture

V3 is the first product-oriented version of the Inter-Op email workflow app.

The goal is to keep the system small enough for a single team to build, while separating it enough that it can move from:

- local development with OpenAI
- to a stable internal product
- to self-hosted AI later
- to self-hosted or cloud deployment without a rewrite

## Core Shape

V3 should have two real runtime applications and several internal support layers:

- `frontend/`: the user-facing web app
- `api/`: the HTTP entrypoint and request/response boundary
- `backend/`: business logic, orchestration, provider adapters, and persistence code
- `shared/`: API contract artifacts such as OpenAPI
- `infra/`: deployment, Docker, and environment setup
- `data/`: local runtime storage and mounted volumes

`api/` and `backend/` are separate code layers, but they should ship together as one backend service for now. That keeps deployment simple while preserving clean boundaries.

## Recommended Tree

```text
V3/
  README.md
  .env.example
  docs/
    architecture.md
  frontend/
    README.md
    src/
      app/
      routes/
      components/
      features/
      hooks/
      lib/
      api/
      types/
  api/
    README.md
    app/
      dependencies/
      routers/
      schemas/
    tests/
  backend/
    README.md
    core/
    application/
    domain/
    providers/
      ai/
      gmail/
    persistence/
      models/
      repositories/
      migrations/
    jobs/
  shared/
    README.md
    openapi/
  infra/
    README.md
    docker/
    compose/
  data/
    README.md
    sqlite/
    cache/
    exports/
```

## Practical Recommendations

- Keep one frontend app, not separate review and end-user codebases.
- Keep one backend API service, not multiple networked microservices.
- Move all Gmail, AI, database, and cache access behind adapters or repositories.
- Use OpenAI first through a provider interface you own.
- Use SQLite first through repositories so Postgres later only changes config and infra.
- Use OpenAPI as the shared contract between frontend and backend.

More detail is in [docs/architecture.md](/C:/Users/antoi/OneDrive/Bureau/Inter-Email/Email%20Workflow%20v1/V3/docs/architecture.md).

## Docker And Local AI

By default, the Docker app stack only starts:

- `api`
- `frontend`

That keeps V3 compatible with:

- a host-installed Ollama process
- an Ollama server on another machine
- OpenAI-only mode

For normal local Docker development:

```powershell
docker compose -f infra/compose/docker-compose.local.yml up --build -d
```

Then point `.env` at your AI host. For a host-installed Ollama on Windows:

```env
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

If you want to try Ollama as an extra Docker service on a machine where that image works:

```powershell
docker compose -f infra/compose/docker-compose.local.yml -f infra/compose/docker-compose.ollama.yml up --build -d
```

After the stack is up, pull a model into the Ollama container:

```powershell
docker compose -f infra/compose/docker-compose.local.yml -f infra/compose/docker-compose.ollama.yml exec ollama ollama pull llama3.2:3b
```

Then switch V3 to `Local AI` in Settings.

Notes:

- The optional Ollama container stores models in the named Docker volume `ollama-data`.
- Your normal app data still stays in `V3/data`.
- If you want to use an external Ollama host later, keep `OLLAMA_BASE_URL` in `.env` pointed there and do not use the Ollama override file.
- On some Windows ARM / Snapdragon setups, the `ollama/ollama` container can fail even though host-installed Ollama works. In that case, prefer host Ollama or another Ollama machine on your network.
