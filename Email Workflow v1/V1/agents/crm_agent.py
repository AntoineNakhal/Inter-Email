"""Agent wrapper for CRM field extraction."""

from __future__ import annotations

import json

from agents import load_openai_agents_sdk, run_with_retry
from prompts import CRM_INSTRUCTIONS
from schemas import AgentEmail, CrmBatch
from services.formatter import agent_emails_to_payload


class CrmAgentRunner:
    """Extracts CRM-ready records for future integrations."""

    def __init__(self, model: str) -> None:
        self.model = model

    def run(self, emails: list[AgentEmail]) -> CrmBatch:
        sdk = load_openai_agents_sdk()
        Agent = sdk.Agent
        Runner = sdk.Runner

        agent = Agent(
            name="CRM Extraction Agent",
            instructions=CRM_INSTRUCTIONS,
            model=self.model,
            output_type=CrmBatch,
        )

        payload = json.dumps(
            {"emails": agent_emails_to_payload(emails)},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        print(f"[crm] processing {len(emails)} emails")
        print(f"[crm] payload size: {len(payload.encode('utf-8'))} bytes")
        result = run_with_retry(
            lambda: Runner.run_sync(agent, payload),
            step_name="CRM extraction step",
        )
        return result.final_output
