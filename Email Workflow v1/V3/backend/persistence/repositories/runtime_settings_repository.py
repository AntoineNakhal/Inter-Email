"""Persistence access for runtime-configurable AI settings."""

from __future__ import annotations

from sqlalchemy import inspect, select, text
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
    ) -> RuntimeSettings:
        model = self._get_or_create()
        model.ai_mode = AIMode(ai_mode).value
        model.local_ai_force_all_threads = bool(
            local_ai_force_all_threads or AIMode(ai_mode) == AIMode.LOCAL
        )
        model.local_ai_model = str(local_ai_model or "").strip()
        model.local_ai_agent_prompt = str(local_ai_agent_prompt or "").strip()
        self.session.flush()
        return self._to_domain(model)

    def update_gmail_mailbox_email(self, gmail_mailbox_email: str) -> RuntimeSettings:
        model = self._get_or_create()
        model.gmail_mailbox_email = str(gmail_mailbox_email or "").strip().lower()
        self.session.flush()
        return self._to_domain(model)

    def _get_or_create(self) -> RuntimeSettingsModel:
        self._ensure_schema()
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

    def _ensure_schema(self) -> None:
        bind = self.session.get_bind()
        if bind is None:
            return

        inspector = inspect(bind)
        if not inspector.has_table(RuntimeSettingsModel.__tablename__):
            return

        column_names = {
            column["name"]
            for column in inspector.get_columns(RuntimeSettingsModel.__tablename__)
        }
        if "gmail_mailbox_email" not in column_names:
            self.session.execute(
                text(
                    "ALTER TABLE runtime_settings "
                    "ADD COLUMN gmail_mailbox_email VARCHAR(255) DEFAULT ''"
                )
            )
            self.session.flush()

    @staticmethod
    def _to_domain(model: RuntimeSettingsModel) -> RuntimeSettings:
        return RuntimeSettings(
            ai_mode=model.ai_mode,
            local_ai_force_all_threads=model.local_ai_force_all_threads,
            local_ai_model=model.local_ai_model,
            local_ai_agent_prompt=model.local_ai_agent_prompt,
            gmail_mailbox_email=model.gmail_mailbox_email,
            updated_at=model.updated_at,
        )
