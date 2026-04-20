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
