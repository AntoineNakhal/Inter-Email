from backend.application.draft_service import DraftService
from backend.domain.analysis import DraftReplyRequest
from backend.domain.runtime_settings import RuntimeSettings
from backend.domain.thread import DraftDocument, EmailThread
from backend.providers.ai.base import AIProviderError


class _Provider:
    def __init__(self, draft: DraftDocument) -> None:
        self.draft = draft
        self.calls = 0

    def draft_reply(self, _request: DraftReplyRequest) -> DraftDocument:
        self.calls += 1
        return self.draft


class _Router:
    def __init__(self, primary: _Provider, fallback: _Provider) -> None:
        self.primary = primary
        self.fallback = fallback

    def provider_for_task(self, _task: str) -> _Provider:
        return self.primary

    def fallback_provider(self) -> _Provider:
        return self.fallback


class _ThreadRepository:
    def __init__(self, thread: EmailThread) -> None:
        self.thread = thread

    def get_thread(self, _external_thread_id: str) -> EmailThread | None:
        return self.thread


class _DraftRepository:
    def __init__(self) -> None:
        self.saved: DraftDocument | None = None

    def save(self, _external_thread_id: str, draft: DraftDocument) -> DraftDocument:
        self.saved = draft
        return draft


def test_generate_draft_falls_back_when_primary_returns_empty() -> None:
    thread = EmailThread(external_thread_id="thread-1", subject="Need reply")
    primary = _Provider(
        DraftDocument(subject="", body="", provider_name="ollama", model_name="gemma4:e4b")
    )
    fallback = _Provider(
        DraftDocument(
            subject="Re: Need reply",
            body="Hi,\n\nThanks for the update.\n\nBest,\nInter-Op Team",
            provider_name="heuristic",
            model_name="deterministic-fallback",
            used_fallback=True,
        )
    )
    repo = _DraftRepository()
    service = DraftService(
        provider_router=_Router(primary, fallback),
        thread_repository=_ThreadRepository(thread),
        draft_repository=repo,
        runtime_settings=RuntimeSettings(),
    )

    draft = service.generate_draft("thread-1", None, [], "")

    assert primary.calls == 1
    assert fallback.calls == 1
    assert repo.saved is not None
    assert draft.provider_name == "heuristic"
    assert draft.body.strip()


def test_generate_draft_raises_when_primary_and_fallback_are_empty() -> None:
    thread = EmailThread(external_thread_id="thread-1", subject="Need reply")
    empty_draft = DraftDocument(subject="", body="")
    service = DraftService(
        provider_router=_Router(_Provider(empty_draft), _Provider(empty_draft)),
        thread_repository=_ThreadRepository(thread),
        draft_repository=_DraftRepository(),
        runtime_settings=RuntimeSettings(),
    )

    try:
        service.generate_draft("thread-1", None, [], "")
        assert False, "Expected AIProviderError"
    except AIProviderError as exc:
        assert "empty" in str(exc).lower()
