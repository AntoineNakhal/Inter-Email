"""Persistence helpers for stored ETA progress snapshots."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.sync import SyncStage, SyncStatus
from backend.persistence.models.eta_progress import EtaProgressModel


class EtaProgressRepository:
    def __init__(self, session: Session, user_id: int) -> None:
        self.session = session
        self.user_id = user_id

    def update_sync_phase(
        self,
        *,
        run_id: int,
        stage: SyncStage,
        status: SyncStatus,
        eta_seconds: int | None,
        progress_current: int,
        progress_total: int,
        status_message: str,
    ) -> None:
        model = self._get_or_create(
            sync_run_id=run_id,
            phase_key=stage.value,
            scope="sync",
            external_thread_id=None,
        )
        model.status = status.value
        model.eta_seconds = eta_seconds
        model.progress_current = progress_current
        model.progress_total = progress_total
        model.details_json = json.dumps(
            {"status_message": status_message},
            ensure_ascii=False,
        )
        self.session.flush()

    def update_thread_analysis(
        self,
        *,
        run_id: int,
        external_thread_id: str,
        eta_seconds: int | None,
        progress_current: int,
        progress_total: int,
        status: str,
    ) -> None:
        model = self._get_or_create(
            sync_run_id=run_id,
            phase_key="thread_analysis",
            scope="thread",
            external_thread_id=external_thread_id,
        )
        model.status = status
        model.eta_seconds = eta_seconds
        model.progress_current = progress_current
        model.progress_total = progress_total
        model.details_json = json.dumps({}, ensure_ascii=False)
        self.session.flush()

    def clear_for_run(self, run_id: int) -> None:
        models = self.session.scalars(
            select(EtaProgressModel).where(
                EtaProgressModel.user_id == self.user_id,
                EtaProgressModel.sync_run_id == run_id,
            )
        ).all()
        for model in models:
            self.session.delete(model)
        self.session.flush()

    def _get_or_create(
        self,
        *,
        sync_run_id: int,
        phase_key: str,
        scope: str,
        external_thread_id: str | None,
    ) -> EtaProgressModel:
        query = select(EtaProgressModel).where(
            EtaProgressModel.user_id == self.user_id,
            EtaProgressModel.sync_run_id == sync_run_id,
            EtaProgressModel.phase_key == phase_key,
            EtaProgressModel.scope == scope,
        )
        if external_thread_id is None:
            query = query.where(EtaProgressModel.external_thread_id.is_(None))
        else:
            query = query.where(EtaProgressModel.external_thread_id == external_thread_id)

        model = self.session.scalar(query)
        if model is None:
            model = EtaProgressModel(
                user_id=self.user_id,
                sync_run_id=sync_run_id,
                phase_key=phase_key,
                scope=scope,
                external_thread_id=external_thread_id,
            )
            self.session.add(model)
            self.session.flush()
        return model
