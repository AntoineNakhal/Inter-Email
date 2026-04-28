from backend.core.config import AppSettings
from backend.domain.analysis import ThreadAnalysisRequest
from backend.domain.thread import EmailThread, ThreadMessage, TriageCategory, UrgencyLevel
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


def test_openai_provider_keeps_summary_short_for_tiny_email(monkeypatch) -> None:
    provider = OpenAIProvider(AppSettings.model_validate({}))

    def fake_chat_json(*args, **kwargs):
        return {
            "category": "Events / Logistics",
            "urgency": "low",
            "summary": (
                "Candidate sent the Google Meet link. "
                "The message mainly repeats the link and includes no other substantive "
                "workflow details beyond the meeting access itself."
            ),
            "current_status": "Meeting link received.",
            "next_action": "Open the link when the meeting starts.",
            "needs_action_today": False,
            "should_draft_reply": False,
            "draft_needs_date": False,
            "draft_needs_attachment": False,
        }

    monkeypatch.setattr(provider, "_chat_json", fake_chat_json)

    result = provider.analyze_thread(
        ThreadAnalysisRequest(
            thread=EmailThread(
                external_thread_id="thread-2",
                subject="Link",
                messages=[
                    ThreadMessage(
                        external_message_id="msg-1",
                        sender="Kelly-Anne",
                        subject="Link",
                        snippet="Google Meet link for the interview.",
                        cleaned_body="https://meet.google.com/nbe-gukw-siz",
                    )
                ],
            )
        )
    )

    assert result.summary == "Candidate sent the Google Meet link."


def test_openai_provider_makes_generic_next_action_specific(monkeypatch) -> None:
    provider = OpenAIProvider(AppSettings.model_validate({}))

    def fake_chat_json(*args, **kwargs):
        return {
            "category": "FYI / Low Priority",
            "urgency": "high",
            "summary": "Hi Antoine, did you receive this?",
            "current_status": "Waiting for Antoine to reply.",
            "next_action": "Prepare and send a reply today.",
            "needs_action_today": True,
            "should_draft_reply": True,
            "draft_needs_date": False,
            "draft_needs_attachment": False,
        }

    monkeypatch.setattr(provider, "_chat_json", fake_chat_json)

    result = provider.analyze_thread(
        ThreadAnalysisRequest(
            thread=EmailThread(
                external_thread_id="thread-3",
                subject="Receipt check",
                waiting_on_us=True,
                messages=[
                    ThreadMessage(
                        external_message_id="msg-2",
                        sender='"El-Ayoubi, Mohammad" <m.elayoubi@inter-op.ca>',
                        subject="Receipt check",
                        snippet="Hi Antoine, did you receive this?",
                        cleaned_body="Hi Antoine, did you receive this?",
                    )
                ],
            )
        )
    )

    assert (
        result.summary
        == "Mohammad is asking for confirmation that the message was received."
    )
    assert result.current_status == "Waiting on Inter-Op to confirm receipt to Mohammad."
    assert result.next_action == "Reply to Mohammad confirming you received this."
