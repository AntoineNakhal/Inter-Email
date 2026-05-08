"""Arq worker entry point.

Run with:
    arq backend.jobs.worker.WorkerSettings

The worker imports the same `backend` package as the API. No business logic
lives here — only the Arq wiring (which tasks to register, which Redis to use).
"""

from __future__ import annotations

from arq import cron, func
from arq.connections import RedisSettings

from backend.core.config import get_settings
from backend.jobs.tasks import ingest_kb_document, run_sync


def get_redis_settings() -> RedisSettings:
    url = get_settings().redis_url or "redis://localhost:6379"
    return RedisSettings.from_dsn(url)


class WorkerSettings:
    """Arq worker configuration."""

    # `arq.func(...)` lets us set per-job overrides without changing the
    # globals. KB ingestion of a 150+ page PDF can take a couple of
    # minutes (extract + chunk + embed + metadata); 15 min is safe rope.
    # Gmail sync keeps the default 5 min (its longest stage is bounded
    # by the Gmail API itself).
    functions = [
        run_sync,
        func(ingest_kb_document, name="ingest_kb_document", timeout=900),
    ]
    redis_settings = get_redis_settings()

    # Retry failed jobs once after 30 s.
    max_tries = 2
    retry_jobs = True

    # Keep completed job results for 1 hour (useful for debugging).
    keep_result = 3600

    on_startup = None
    on_shutdown = None
