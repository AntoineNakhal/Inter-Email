from backend.core.config import AppSettings
from backend.domain.analysis import ThreadAnalysisRequest
from backend.domain.thread import EmailThread, TriageCategory, UrgencyLevel
from backend.providers.ai.openai_provider import OpenAIProvider


def test_openai_provider_normalizes_unknown_thread_category(monkeypatch) -> None:
    provider = OpenAIProvider(AppSettings.model_validate({}))

    def fake_chat_json(*args, **kwargs):
        return {
            "category": "Website Monitoring",
            "urgency": "medium",
            "summary": "Website health alert notification.",
            "current_status": "Monitoring the issue.",
            "next_action": "Review the alert and decide whether escalation is needed.",
            "needs_action_today": False,
            "should_draft_reply": False,
            "draft_needs_date": False,
            "draft_needs_attachment": False,
        }

    monkeypatch.setattr(provider, "_chat_json", fake_chat_json)

    result = provider.analyze_thread(
        ThreadAnalysisRequest(
            thread=EmailThread(
                external_thread_id="thread-1",
                subject="Website Monitoring Alert",
            )
        )
    )

    assert result.category == TriageCategory.FYI_LOW_PRIORITY
    assert result.urgency == UrgencyLevel.MEDIUM
