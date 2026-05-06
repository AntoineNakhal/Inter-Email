"""Persistence access for runtime-configurable AI settings."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.runtime_settings import AIMode, RuntimeSettings
from backend.persistence.models.runtime_settings import RuntimeSettingsModel


class RuntimeSettingsRepository:
    """Loads and updates the singleton runtime settings row."""

    SINGLETON_ID = 1

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self) -> RuntimeSettings:
        model = self._get_or_create()
        return self._to_domain(model)

    def update(
        self,
        *,
        ai_mode: str,
        local_ai_force_all_threads: bool,
        local_ai_model: str,
        local_ai_agent_prompt: str,
        local_ai_max_threads: int = 50,
    ) -> RuntimeSettings:
        model = self._get_or_create()
        model.ai_mode = AIMode(ai_mode).value
        model.local_ai_force_all_threads = bool(
            local_ai_force_all_threads or AIMode(ai_mode) == AIMode.LOCAL
        )
        model.local_ai_model = str(local_ai_model or "").strip()
        model.local_ai_agent_prompt = str(local_ai_agent_prompt or "").strip()
        model.local_ai_max_threads = max(0, int(local_ai_max_threads))
        self.session.flush()
        return self._to_domain(model)

    def update_gmail_mailbox_email(self, gmail_mailbox_email: str) -> RuntimeSettings:
        model = self._get_or_create()
        model.gmail_mailbox_email = str(gmail_mailbox_email or "").strip().lower()
        self.session.flush()
        return self._to_domain(model)

    def update_gmail_mailbox_name(self, gmail_mailbox_name: str) -> RuntimeSettings:
        model = self._get_or_create()
        model.gmail_mailbox_name = str(gmail_mailbox_name or "").strip()
        self.session.flush()
        return self._to_domain(model)

    def update_gmail_history_id(self, gmail_history_id: str) -> RuntimeSettings:
        model = self._get_or_create()
        model.gmail_history_id = str(gmail_history_id or "").strip()
        self.session.flush()
        return self._to_domain(model)

    def update_gmail_watch(
        self,
        resource_id: str,
        expiry: "datetime | None",
    ) -> RuntimeSettings:
        model = self._get_or_create()
        model.gmail_watch_resource_id = str(resource_id or "").strip()
        model.gmail_watch_expiry = expiry
        self.session.flush()
        return self._to_domain(model)

    def _get_or_create(self) -> RuntimeSettingsModel:
        model = self.session.scalar(
            select(RuntimeSettingsModel).where(
                RuntimeSettingsModel.id == self.SINGLETON_ID
            )
        )
        if model is None:
            model = RuntimeSettingsModel(id=self.SINGLETON_ID)
            self.session.add(model)
            self.session.flush()
        return model

    @staticmethod
    def _to_domain(model: RuntimeSettingsModel) -> RuntimeSettings:
        return RuntimeSettings(
            ai_mode=model.ai_mode,
            local_ai_force_all_threads=model.local_ai_force_all_threads,
            local_ai_model=model.local_ai_model,
            local_ai_agent_prompt=model.local_ai_agent_prompt,
            gmail_mailbox_email=model.gmail_mailbox_email,
            gmail_mailbox_name=model.gmail_mailbox_name,
            gmail_history_id=model.gmail_history_id,
            gmail_watch_resource_id=model.gmail_watch_resource_id,
            gmail_watch_expiry=model.gmail_watch_expiry,
            local_ai_max_threads=model.local_ai_max_threads,
            updated_at=model.updated_at,
        )
