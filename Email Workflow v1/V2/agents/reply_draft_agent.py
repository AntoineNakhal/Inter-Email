"""Agent wrapper for thread-level reply drafting."""

from __future__ import annotations

import json

from agents import load_openai_agents_sdk, run_with_retry
from prompts import (
    REPLY_DRAFT_GENERATION_INSTRUCTIONS,
    REPLY_DRAFT_INSTRUCTIONS,
)
from schemas import (
    DraftGenerationRequest,
    EmailThread,
    GeneratedReplyDraft,
    ThreadReplyDraftBatch,
)
from services.formatter import (
    draft_request_to_payload,
    reply_draft_thread_to_payload,
    reply_draft_threads_to_payload,
)


class ReplyDraftAgentRunner:
    """Plans reply-draft needs and generates drafts on demand."""

    def __init__(self, model: str) -> None:
        self.model = model

    def run(self, threads: list[EmailThread]) -> ThreadReplyDraftBatch:
        sdk = load_openai_agents_sdk()
        Agent = sdk.Agent
        Runner = sdk.Runner

        agent = Agent(
            name="Thread Reply Draft Agent",
            instructions=REPLY_DRAFT_INSTRUCTIONS,
            model=self.model,
            output_type=ThreadReplyDraftBatch,
        )

        payload = json.dumps(
            {"threads": reply_draft_threads_to_payload(threads)},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        print(f"[reply_draft] processing {len(threads)} threads")
        print(f"[reply_draft] payload size: {len(payload.encode('utf-8'))} bytes")
        result = run_with_retry(
            lambda: Runner.run_sync(agent, payload),
            step_name="Reply drafting step",
        )
        return result.final_output

    def generate_draft(
        self,
        thread: EmailThread,
        draft_request: DraftGenerationRequest,
    ) -> GeneratedReplyDraft:
        """Generate one final reply draft after the user completes the wizard."""

        sdk = load_openai_agents_sdk()
        Agent = sdk.Agent
        Runner = sdk.Runner

        agent = Agent(
            name="On-Demand Reply Draft Agent",
            instructions=REPLY_DRAFT_GENERATION_INSTRUCTIONS,
            model=self.model,
            output_type=GeneratedReplyDraft,
        )

        payload = json.dumps(
            {
                "thread": reply_draft_thread_to_payload(thread),
                "draft_request": draft_request_to_payload(draft_request),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        print(f"[reply_draft] generating final draft for {thread.thread_id}")
        print(f"[reply_draft] draft payload size: {len(payload.encode('utf-8'))} bytes")
        result = run_with_retry(
            lambda: Runner.run_sync(agent, payload),
            step_name="Reply draft generation step",
        )
        return result.final_output
