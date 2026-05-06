"""FastAPI entrypoint for V3."""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.app.routers import contacts, drafts, gmail, health, push, review, settings as settings_router, sync, threads
from api.app.dependencies.services import build_service_bundle
from backend.core.config import get_settings
from backend.core.database import get_session_factory, init_database


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    settings.ensure_runtime_directories()
    init_database(settings)

    # On startup, mark any sync_runs rows that are still "running" from a
    # previous process as "interrupted". This prevents the UI from showing a
    # perpetual "syncing…" state after a server restart.
    from backend.persistence.repositories.sync_repository import SyncRepository
    with get_session_factory()() as session:
        repo = SyncRepository(session)
        repo.interrupt_stale_runs()
        session.commit()

        # Ensure a Gmail Pub/Sub watch is registered so new emails trigger
        # push notifications and background sync runs.
        try:
            services = build_service_bundle(session)
            topic = services.settings.gmail_pubsub_topic
            if topic:
                services.sync_service.ensure_watch(topic)
        except Exception:
            logger.warning("Failed to register Gmail watch on startup", exc_info=True)

    yield


def create_app() -> FastAPI:
    app_settings = get_settings()
    init_database(app_settings)
    app = FastAPI(
        title="Inter-Email V3 API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            f"http://localhost:{app_settings.frontend_port}",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router, prefix="/api/v1", tags=["health"])
    app.include_router(sync.router, prefix="/api/v1", tags=["sync"])
    app.include_router(threads.router, prefix="/api/v1", tags=["threads"])
    app.include_router(review.router, prefix="/api/v1", tags=["review"])
    app.include_router(drafts.router, prefix="/api/v1", tags=["drafts"])
    app.include_router(gmail.router, prefix="/api/v1", tags=["gmail"])
    app.include_router(settings_router.router, prefix="/api/v1", tags=["settings"])
    app.include_router(contacts.router, prefix="/api/v1", tags=["contacts"])
    app.include_router(push.router, prefix="/api/v1", tags=["push"])
    return app


app = create_app()
