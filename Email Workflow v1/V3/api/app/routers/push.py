"""Gmail Pub/Sub push notification webhook."""

from __future__ import annotations

import base64
import json
import logging
import secrets

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api.app.dependencies.db import get_db_session
from api.app.dependencies.services import build_service_bundle_for_user_id
from api.app.schemas.push import GmailPushData, PubSubPushPayload
from backend.core.config import get_settings
from backend.core.database import get_session_factory
from backend.persistence.repositories.sync_repository import SyncRepository
from backend.persistence.repositories.user_repository import UserRepository


async def _enqueue_push_sync_job(run_id: int, source: str, max_results: int) -> None:
    import arq
    from backend.jobs.worker import get_redis_settings

    redis = await arq.create_pool(get_redis_settings())
    await redis.enqueue_job("run_sync", run_id, source, max_results, 7)
    await redis.close()


router = APIRouter()
logger = logging.getLogger(__name__)


def _run_push_sync_job(run_id: int, source: str, max_results: int) -> None:
    session_factory = get_session_factory()
    session = session_factory()
    try:
        run_model = SyncRepository(session).get_run_model(run_id)
        if run_model is None:
            raise ValueError(f"Sync run `{run_id}` was not found.")
        services = build_service_bundle_for_user_id(session, run_model.user_id)
        services.sync_service.sync_recent_threads(
            run_id=run_id,
            source=source,
            max_results=max_results,
            lookback_days=7,
        )
        topic = services.settings.gmail_pubsub_topic
        if topic:
            services.sync_service.ensure_watch(topic)
    except Exception:
        logger.exception("Push-triggered Gmail sync failed (run_id=%s)", run_id)
    finally:
        session.close()


@router.post("/gmail/push", status_code=status.HTTP_204_NO_CONTENT)
async def gmail_push_notification(
    payload: PubSubPushPayload,
    background_tasks: BackgroundTasks,
    token: str = Query(default="", description="Shared verification token"),
    session: Session = Depends(get_db_session),
) -> None:
    settings = get_settings()
    expected_token = settings.gmail_pubsub_verification_token.strip()
    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Push notifications are not configured on this server.",
        )
    if not secrets.compare_digest(token, expected_token):
        logger.warning("Gmail push webhook received invalid token.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid verification token.",
        )

    try:
        data_bytes = base64.urlsafe_b64decode(
            payload.message.data + "==" * (4 - len(payload.message.data) % 4)
        )
        notification = GmailPushData.model_validate(json.loads(data_bytes))
    except Exception as exc:
        logger.warning("Gmail push: failed to decode Pub/Sub message data: %s", exc)
        return

    logger.info(
        "Gmail push notification received email=%r historyId=%r",
        notification.emailAddress,
        notification.historyId,
    )

    user_model = UserRepository(session).get_model_by_email(notification.emailAddress)
    if user_model is None:
        logger.warning(
            "Push notification for %r but no matching authenticated user exists.",
            notification.emailAddress,
        )
        return

    services = build_service_bundle_for_user_id(session, user_model.id)
    running = services.sync_service.get_running_run()
    if running is not None:
        logger.info(
            "Push notification coalesced - sync run %s already in progress.",
            running.run_id,
        )
        return

    source = settings.gmail_thread_source
    max_results = settings.gmail_max_results
    try:
        run = services.sync_service.create_run(source)
    except RuntimeError as exc:
        logger.info("Push-triggered sync skipped: %s", exc)
        return

    if settings.redis_url:
        await _enqueue_push_sync_job(run.run_id, source, max_results)
        logger.info(
            "Push notification accepted - enqueued sync run %s via Arq for %r.",
            run.run_id,
            notification.emailAddress,
        )
    else:
        background_tasks.add_task(_run_push_sync_job, run.run_id, source, max_results)
        logger.info(
            "Push notification accepted - started sync run %s via BackgroundTasks for %r.",
            run.run_id,
            notification.emailAddress,
        )
