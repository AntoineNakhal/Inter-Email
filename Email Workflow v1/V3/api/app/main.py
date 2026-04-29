"""FastAPI entrypoint for V3."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.app.routers import contacts, drafts, gmail, health, review, settings as settings_router, sync, threads
from backend.core.config import get_settings
from backend.core.database import init_database


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    settings.ensure_runtime_directories()
    init_database(settings)
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
    return app


app = create_app()
