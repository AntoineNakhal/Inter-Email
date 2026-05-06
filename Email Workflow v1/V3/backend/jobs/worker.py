"""Arq worker entry point.

Run with:
    arq backend.jobs.worker.WorkerSettings

The worker imports the same `backend` package as the API. No business logic
lives here — only the Arq wiring (which tasks to register, which Redis to use).
"""

from __future__ import annotations

from arq import cron
from arq.connections import RedisSettings

from backend.core.config import get_settings
from backend.jobs.tasks import run_sync


def get_redis_settings() -> RedisSettings:
    url = get_settings().redis_url or "redis://localhost:6379"
    return RedisSettings.from_dsn(url)


class WorkerSettings:
    """Arq worker configuration."""

    functions = [run_sync]
    redis_settings = get_redis_settings()

    # Retry failed jobs once after 30 s.
    max_tries = 2
    retry_jobs = True

    # Keep completed job results for 1 hour (useful for debugging).
    keep_result = 3600

    on_startup = None
    on_shutdown = None
