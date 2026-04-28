from datetime import datetime, timezone

from backend.core.config import AppSettings
from backend.domain.analysis import DraftReplyRequest
from backend.domain.runtime_settings import RuntimeSettings
from backend.domain.thread import EmailThread, ThreadAnalysis, ThreadMessage
from backend.providers.ai.agents.ollama import (
    LocalCRMAgent,
    LocalDraftAgent,
    LocalInboxAgent,
    LocalQueueAgent,
    LocalVerificationAgent,
)
from backend.providers.ai.ollama_provider import OllamaProvider


def test_ollama_provider_exposes_five_task_specific_agents() -> None:
    provider = OllamaProvider(
        AppSettings.model_validate({}),
        RuntimeSettings(local_ai_agent_prompt="Be strict."),
    )

    assert isinstance(provider.inbox_agent, LocalInboxAgent)
    assert isinstance(provider.queue_agent, LocalQueueAgent)
    assert isinstance(provider.draft_agent, LocalDraftAgent)
    assert isinstance(provider.crm_agent, LocalCRMAgent)
    assert isinstance(provider.verification_agent, LocalVerificationAgent)


def test_local_inbox_agent_prompt_mentions_always_analyze_behavior() -> None:
    agent = LocalInboxAgent(RuntimeSettings(local_ai_agent_prompt="Be strict."))

    prompt = agent.compose_prompt({"thread": {"subject": "Status update"}})

    assert "every fetched email thread passes through you" in prompt
    assert "Be strict." in prompt
    assert '"subject": "Status update"' in prompt


def test_local_verification_agent_prompt_mentions_accuracy_review() -> None:
    agent = LocalVerificationAgent(RuntimeSettings(local_ai_agent_prompt="Double-check.")) 

    prompt = agent.compose_prompt({"analysis": {"summary": "Needs reply"}})

    assert "verify whether the proposed email-thread analysis is accurate" in prompt
    assert "accuracy_percent" in prompt
    assert "Double-check." in prompt


def test_local_draft_agent_prompt_prioritizes_user_instructions() -> None:
    agent = LocalDraftAgent(RuntimeSettings(local_ai_agent_prompt="Be concise."))

    prompt = agent.compose_prompt(
        {
            "draft_context": {
                "user_instructions": "Say I received it and keep it very short.",
            }
        }
    )

    assert "highest-priority drafting requirements" in prompt
    assert "Say I received it and keep it very short." in prompt


def test_ollama_provider_builds_draft_payload_with_user_context() -> None:
    provider = OllamaProvider(
        AppSettings.model_validate({}),
        RuntimeSettings(local_ai_model="llama3.1:8b"),
    )
    payload = provider._build_draft_payload(
        DraftReplyRequest(
            thread=EmailThread(
                external_thread_id="thread-1",
                subject="Receipt check",
                participants=['"El-Ayoubi, Mohammad" <m.elayoubi@inter-op.ca>'],
                messages=[
                    ThreadMessage(
                        external_message_id="msg-1",
                        sender='"El-Ayoubi, Mohammad" <m.elayoubi@inter-op.ca>',
                        subject="Receipt check",
                        sent_at=datetime(2026, 4, 24, 10, 0, tzinfo=timezone.utc),
                        snippet="Did you receive this?",
                        cleaned_body="Did you receive this?",
                    )
                ],
                analysis=ThreadAnalysis(
                    summary="Mohammad is asking for confirmation that the message was received.",
                    current_status="Waiting on Inter-Op to confirm receipt to Mohammad.",
                    next_action="Reply to Mohammad confirming you received this.",
                    should_draft_reply=True,
                ),
            ),
            user_instructions="Say clearly that I received it.",
            selected_date=None,
            attachment_names=[],
        )
    )

    assert payload["draft_context"]["user_instructions"] == "Say clearly that I received it."
    assert payload["thread"]["analysis"]["next_action"] == (
        "Reply to Mohammad confirming you received this."
    )


def test_ollama_provider_tries_host_docker_internal_from_localhost() -> None:
    provider = OllamaProvider(
        AppSettings.model_validate(
            {
                "OLLAMA_BASE_URL": "http://localhost:11434",
            }
        ),
        RuntimeSettings(local_ai_model="llama3.1:8b"),
    )

    assert provider._generate_endpoint_candidates() == [
        "http://localhost:11434/api/generate",
        "http://host.docker.internal:11434/api/generate",
    ]


def test_ollama_provider_tries_localhost_from_host_docker_internal() -> None:
    provider = OllamaProvider(
        AppSettings.model_validate(
            {
                "OLLAMA_BASE_URL": "http://host.docker.internal:11434",
            }
        ),
        RuntimeSettings(local_ai_model="llama3.1:8b"),
    )

    assert provider._generate_endpoint_candidates() == [
        "http://host.docker.internal:11434/api/generate",
        "http://localhost:11434/api/generate",
    ]
