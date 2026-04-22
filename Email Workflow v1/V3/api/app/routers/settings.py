"""Settings endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.app.dependencies.services import ServiceBundle, get_service_bundle
from api.app.schemas.settings import (
    RuntimeSettingsUpdateRequest,
    SettingsSummaryResponse,
)


router = APIRouter()


def _has_any_ollama_model_configured(settings, local_ai_model: str) -> bool:
    if str(local_ai_model or "").strip():
        return True
    return any(
        str(value or "").strip()
        for value in [
            settings.ollama_model_thread_analysis,
            settings.ollama_model_queue_summary,
            settings.ollama_model_draft,
            settings.ollama_model_crm,
        ]
    )


@router.get("/settings", response_model=SettingsSummaryResponse)
def get_settings_summary(
    services: ServiceBundle = Depends(get_service_bundle),
) -> SettingsSummaryResponse:
    settings = services.settings
    runtime_settings = services.runtime_settings_service.get()
    return SettingsSummaryResponse(
        environment=settings.app_env,
        database_url=settings.database_url,
        ai_default_provider=settings.ai_default_provider,
        thread_analysis_provider=settings.ai_thread_analysis_provider,
        queue_summary_provider=settings.ai_queue_summary_provider,
        draft_provider=settings.ai_draft_provider,
        crm_provider=settings.ai_crm_provider,
        ai_mode=runtime_settings.ai_mode.value,
        local_ai_force_all_threads=runtime_settings.local_ai_force_all_threads,
        local_ai_model=runtime_settings.local_ai_model,
        local_ai_agent_prompt=runtime_settings.local_ai_agent_prompt,
        ollama_base_url=settings.ollama_base_url,
        ollama_model_thread_analysis=settings.ollama_model_thread_analysis,
        runtime_settings_updated_at=runtime_settings.updated_at,
    )


@router.put("/settings", response_model=SettingsSummaryResponse)
def update_settings_summary(
    payload: RuntimeSettingsUpdateRequest,
    services: ServiceBundle = Depends(get_service_bundle),
) -> SettingsSummaryResponse:
    if payload.ai_mode.value == "local" and not _has_any_ollama_model_configured(
        services.settings,
        payload.local_ai_model,
    ):
        raise HTTPException(
            status_code=400,
            detail="Local AI mode needs an Ollama model name before it can be enabled.",
        )

    runtime_settings = services.runtime_settings_service.update(
        ai_mode=payload.ai_mode.value,
        local_ai_force_all_threads=payload.local_ai_force_all_threads,
        local_ai_model=payload.local_ai_model,
        local_ai_agent_prompt=payload.local_ai_agent_prompt,
    )
    services.session.commit()

    settings = services.settings
    return SettingsSummaryResponse(
        environment=settings.app_env,
        database_url=settings.database_url,
        ai_default_provider=settings.ai_default_provider,
        thread_analysis_provider=settings.ai_thread_analysis_provider,
        queue_summary_provider=settings.ai_queue_summary_provider,
        draft_provider=settings.ai_draft_provider,
        crm_provider=settings.ai_crm_provider,
        ai_mode=runtime_settings.ai_mode.value,
        local_ai_force_all_threads=runtime_settings.local_ai_force_all_threads,
        local_ai_model=runtime_settings.local_ai_model,
        local_ai_agent_prompt=runtime_settings.local_ai_agent_prompt,
        ollama_base_url=settings.ollama_base_url,
        ollama_model_thread_analysis=settings.ollama_model_thread_analysis,
        runtime_settings_updated_at=runtime_settings.updated_at,
    )
