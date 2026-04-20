"""Provider-agnostic AI abstractions."""

from __future__ import annotations

from abc import ABC, abstractmethod

from backend.domain.analysis import (
    CRMExtractionRequest,
    CRMExtractionResult,
    DraftReplyRequest,
    QueueSummaryRequest,
    QueueSummaryResult,
    ThreadAnalysisRequest,
)
from backend.domain.thread import DraftDocument, ThreadAnalysis


class AIProviderError(RuntimeError):
    """Raised when a provider call fails."""


class AIProvider(ABC):
    """Stable interface that product logic depends on."""

    name: str

    @abstractmethod
    def analyze_thread(self, request: ThreadAnalysisRequest) -> ThreadAnalysis:
        raise NotImplementedError

    @abstractmethod
    def summarize_queue(self, request: QueueSummaryRequest) -> QueueSummaryResult:
        raise NotImplementedError

    @abstractmethod
    def draft_reply(self, request: DraftReplyRequest) -> DraftDocument:
        raise NotImplementedError

    @abstractmethod
    def extract_crm(self, request: CRMExtractionRequest) -> CRMExtractionResult:
        raise NotImplementedError
