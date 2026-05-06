"""Gmail Pub/Sub push notification webhook.

Google Cloud Pub/Sub calls this endpoint when a Gmail watch detects changes
for the connected account. The handler validates the request, decodes the
notification, and fires an incremental sync in the background.

Push endpoint URL (configure in Pub/Sub subscription):
    https://<your-api>/api/v1/gmail/push?token=<GMAIL_PUBSUB_VERIFICATION_TOKEN>

Pub/Sub acknowledges delivery on any 2xx response. We return 204 immediately
and do the actual sync in a BackgroundTask so we never time out Google's
acknowledgement window.

Security model:
    A shared secret token (GMAIL_PUBSUB_VERIFICATION_TOKEN) is appended to
    the push URL. We validate it with a constant-time comparison. This is the
    standard lightweight approach for Pub/Sub push authentication when you
    don't need the full OAuth JWT verification path.
"""

from __future__ import annotations

import base64
import json
import logging
import secrets

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status

from api.app.dependencies.services import ServiceBundle, build_service_bundle, get_service_bundle
from api.app.schemas.push import GmailPushData, PubSubPushPayload
from backend.core.config import get_settings
from backend.core.database import get_session_factory


async def _enqueue_push_sync_job(run_id: int, source: str, max_results: int) -> None:
    """Enqueue a push-triggered sync via Arq when Redis is configured."""
    import arq
    from backend.jobs.worker import get_redis_settings
    redis = await arq.create_pool(get_redis_settings())
    await redis.enqueue_job("run_sync", run_id, source, max_results, 7)
    await redis.close()


router = APIRouter()
logger = logging.getLogger(__name__)


def _run_push_sync_job(run_id: int, source: str, max_results: int) -> None:
    """Background function: mirrors _run_sync_job in sync.py but for push-triggered runs.

    Opens its own DB session (the request-scoped session will already be
    closed by the time this runs) and calls sync_recent_threads with the
    default lookback window as a fallback for the bootstrap path.
    """
    session_factory = get_session_factory()
    session = session_factory()
    try:
        services = build_service_bundle(session)
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


@router.post(
    "/gmail/push",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Gmail Pub/Sub push notification",
    description=(
        "Receives push notifications from Google Cloud Pub/Sub when Gmail "
        "detects changes for the connected account. Triggers an incremental sync."
    ),
)
async def gmail_push_notification(
    payload: PubSubPushPayload,
    background_tasks: BackgroundTasks,
    token: str = Query(default="", description="Shared verification token"),
    services: ServiceBundle = Depends(get_service_bundle),
) -> None:
    settings = get_settings()

    # -----------------------------------------------------------------
    # Guard: push not configured
    # -----------------------------------------------------------------
    expected_token = settings.gmail_pubsub_verification_token.strip()
    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Push notifications are not configured on this server.",
        )

    # -----------------------------------------------------------------
    # Validate the shared secret (constant-time to prevent timing attacks)
    # -----------------------------------------------------------------
    if not secrets.compare_digest(token, expected_token):
        logger.warning("Gmail push webhook received invalid token.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid verification token.",
        )

    # -----------------------------------------------------------------
    # Decode and parse the Pub/Sub message payload
    # -----------------------------------------------------------------
    try:
        # Google base64url-encodes the JSON; add padding before decoding.
        data_bytes = base64.urlsafe_b64decode(
            payload.message.data + "==" * (4 - len(payload.message.data) % 4)
        )
        notification = GmailPushData.model_validate(json.loads(data_bytes))
    except Exception as exc:
        # Acknowledge malformed payloads to prevent Pub/Sub retry storms.
        logger.warning(
            "Gmail push: failed to decode Pub/Sub message data: %s", exc
        )
        return

    logger.info(
        "Gmail push notification received email=%r historyId=%r",
        notification.emailAddress,
        notification.historyId,
    )

    # -----------------------------------------------------------------
    # Verify the notification is for our connected mailbox
    # -----------------------------------------------------------------
    connected_mailbox = services.settings.gmail_thread_source  # proxy for "configured"
    # We check the actual stored mailbox from runtime_settings via the service bundle.
    stored_mailbox = (
        services.runtime_settings_service.get().gmail_mailbox_email.strip().lower()
    )
    if (
        notification.emailAddress
        and stored_mailbox
        and notification.emailAddress.strip().lower() != stored_mailbox
    ):
        logger.warning(
            "Push notification for %r but connected mailbox is %r — ignoring.",
            notification.emailAddress,
            stored_mailbox,
        )
        return  # acknowledge to Pub/Sub, no sync needed

    # -----------------------------------------------------------------
    # Coalesce: skip if a sync is already in flight
    # -----------------------------------------------------------------
    running = services.sync_service.get_running_run()
    if running is not None:
        logger.info(
            "Push notification coalesced — sync run %s already in progress.",
            running.run_id,
        )
        return

    # -----------------------------------------------------------------
    # Create a new run and fire the sync in the background
    # -----------------------------------------------------------------
    source = settings.gmail_thread_source
    max_results = settings.gmail_max_results

    try:
        run = services.sync_service.create_run(source)
    except RuntimeError as exc:
        # Per-account lock: another run was just created between our check and now.
        logger.info("Push-triggered sync skipped: %s", exc)
        return

    if get_settings().redis_url:
        await _enqueue_push_sync_job(run.run_id, source, max_results)
        logger.info(
            "Push notification accepted — enqueued sync run %s via Arq for %r.",
            run.run_id,
            notification.emailAddress,
        )
    else:
        background_tasks.add_task(
            _run_push_sync_job,
            run.run_id,
            source,
            max_results,
        )
        logger.info(
            "Push notification accepted — started sync run %s via BackgroundTasks for %r.",
            run.run_id,
            notification.emailAddress,
        )
