"""Agent wrapper for the executive summary step."""

from __future__ import annotations

import json

from agents import load_openai_agents_sdk, run_with_retry
from prompts import SUMMARY_INSTRUCTIONS
from schemas import AgentEmail, SummaryOutput, TriageItem
from services.formatter import agent_emails_to_payload, triage_items_to_payload


class SummaryAgentRunner:
    """Generates top priorities and a concise executive summary."""

    def __init__(self, model: str) -> None:
        self.model = model

    def run(
        self, emails: list[AgentEmail], triage_items: list[TriageItem]
    ) -> SummaryOutput:
        sdk = load_openai_agents_sdk()
        Agent = sdk.Agent
        Runner = sdk.Runner

        agent = Agent(
            name="Executive Summary Agent",
            instructions=SUMMARY_INSTRUCTIONS,
            model=self.model,
            output_type=SummaryOutput,
        )

        payload = json.dumps(
            {
                "emails": agent_emails_to_payload(emails),
                "triage": triage_items_to_payload(triage_items),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        print(f"[summary] processing {len(emails)} emails")
        print(f"[summary] payload size: {len(payload.encode('utf-8'))} bytes")
        result = run_with_retry(
            lambda: Runner.run_sync(agent, payload),
            step_name="Summary step",
        )
        return result.final_output
