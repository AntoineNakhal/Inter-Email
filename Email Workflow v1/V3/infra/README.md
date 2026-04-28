# Infrastructure

This folder should contain deployment assets, not business logic.

Recommended contents:

- Dockerfiles
- Docker Compose files
- reverse proxy config if needed
- deployment notes for local, self-hosted, and cloud environments

Keep all runtime configuration environment-driven so the same codebase can run:

- locally on a laptop
- on one self-hosted machine
- on a VPS or cloud container platform

## Ollama Service

The base Compose stacks do not require an internal Ollama service.

That is intentional so the backend can point to:

- host-installed Ollama
- an Ollama server on another machine
- another local inference endpoint later

If you want an extra Ollama container, use the override file:

```powershell
docker compose -f infra/compose/docker-compose.local.yml -f infra/compose/docker-compose.ollama.yml up --build -d
```

In that override mode:

- `api` talks to Ollama over the internal Docker network at `http://ollama:11434`
- Ollama model files are stored in the named Docker volume `ollama-data`
- the backend and local AI stay separated cleanly

Useful command after startup:

```powershell
docker compose -f infra/compose/docker-compose.local.yml -f infra/compose/docker-compose.ollama.yml exec ollama ollama pull llama3.2:3b
```
