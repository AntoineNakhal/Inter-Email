"""Persistence model exports.

Every model must be imported here so that Base.metadata registers all tables.
This matters for both init_database() (create_all) and Alembic autogenerate.
"""

from backend.persistence.models.base import Base
from backend.persistence.models.contact import ContactModel, ContactThreadModel
from backend.persistence.models.email_account import EmailAccountModel
from backend.persistence.models.draft import DraftModel
from backend.persistence.models.eta_progress import EtaProgressModel
from backend.persistence.models.override import ThreadOverrideModel
from backend.persistence.models.review import ReviewDecisionModel
from backend.persistence.models.runtime_settings import RuntimeSettingsModel
from backend.persistence.models.sync_run import SyncRunModel
from backend.persistence.models.thread import (
    EmailThreadModel,
    ThreadAnalysisModel,
    ThreadMessageModel,
    ThreadStateModel,
)
from backend.persistence.models.user import UserModel, UserSessionModel

__all__ = [
    "Base",
    "ContactModel",
    "EmailAccountModel",
    "ContactThreadModel",
    "DraftModel",
    "EmailThreadModel",
    "EtaProgressModel",
    "ReviewDecisionModel",
    "RuntimeSettingsModel",
    "SyncRunModel",
    "ThreadAnalysisModel",
    "ThreadMessageModel",
    "ThreadOverrideModel",
    "ThreadStateModel",
    "UserModel",
    "UserSessionModel",
]
