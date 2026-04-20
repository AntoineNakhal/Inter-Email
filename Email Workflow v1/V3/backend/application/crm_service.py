"""CRM extraction service."""

from __future__ import annotations

from backend.domain.analysis import CRMExtractionRequest, CRMExtractionResult
from backend.domain.thread import EmailThread
from backend.providers.ai.base import AIProviderError
from backend.providers.ai.router import AIProviderRouter


class CRMService:
    """Coordinates CRM extraction through the provider router."""

    def __init__(self, provider_router: AIProviderRouter) -> None:
        self.provider_router = provider_router

    def extract(
        self,
        thread: EmailThread,
        *,
        prefer_primary: bool = True,
    ) -> CRMExtractionResult:
        request = CRMExtractionRequest(thread=thread)
        provider = (
            self.provider_router.provider_for_task("crm_extraction")
            if prefer_primary
            else self.provider_router.fallback_provider()
        )
        try:
            return provider.extract_crm(request)
        except AIProviderError:
            return self.provider_router.fallback_provider().extract_crm(request)
