"""Settings endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.app.dependencies.services import ServiceBundle, get_service_bundle
from api.app.schemas.settings import SettingsSummaryResponse


router = APIRouter()


@router.get("/settings", response_model=SettingsSummaryResponse)
def get_settings_summary(
    services: ServiceBundle = Depends(get_service_bundle),
) -> SettingsSummaryResponse:
    settings = services.settings
    return SettingsSummaryResponse(
        environment=settings.app_env,
        database_url=settings.database_url,
        ai_default_provider=settings.ai_default_provider,
        thread_analysis_provider=settings.ai_thread_analysis_provider,
        queue_summary_provider=settings.ai_queue_summary_provider,
        draft_provider=settings.ai_draft_provider,
        crm_provider=settings.ai_crm_provider,
    )
