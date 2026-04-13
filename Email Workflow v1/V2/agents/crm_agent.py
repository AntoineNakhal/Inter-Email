"""Agent wrapper for thread-level CRM field extraction."""

from __future__ import annotations

import json

from agents import load_openai_agents_sdk, run_with_retry
from prompts import CRM_INSTRUCTIONS
from schemas import AgentThread, ThreadCrmBatch
from services.formatter import agent_threads_to_payload


class CrmAgentRunner:
    """Extracts CRM-ready fields for each thread."""

    def __init__(self, model: str) -> None:
        self.model = model

    def run(self, threads: list[AgentThread]) -> ThreadCrmBatch:
        sdk = load_openai_agents_sdk()
        Agent = sdk.Agent
        Runner = sdk.Runner

        agent = Agent(
            name="Thread CRM Extraction Agent",
            instructions=CRM_INSTRUCTIONS,
            model=self.model,
            output_type=ThreadCrmBatch,
        )

        payload = json.dumps(
            {"threads": agent_threads_to_payload(threads)},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        print(f"[crm] processing {len(threads)} threads")
        print(f"[crm] payload size: {len(payload.encode('utf-8'))} bytes")
        result = run_with_retry(
            lambda: Runner.run_sync(agent, payload),
            step_name="CRM extraction step",
        )
        return result.final_output
