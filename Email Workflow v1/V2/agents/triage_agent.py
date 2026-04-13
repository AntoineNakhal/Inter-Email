"""Agent wrapper for thread triage classification."""

from __future__ import annotations

import json

from agents import load_openai_agents_sdk, run_with_retry
from prompts import TRIAGE_INSTRUCTIONS
from schemas import AgentThread, ThreadTriageBatch
from services.formatter import agent_threads_to_payload


class TriageAgentRunner:
    """Runs the triage step through the OpenAI Agents SDK."""

    def __init__(self, model: str) -> None:
        self.model = model

    def run(self, threads: list[AgentThread]) -> ThreadTriageBatch:
        sdk = load_openai_agents_sdk()
        Agent = sdk.Agent
        Runner = sdk.Runner

        agent = Agent(
            name="Thread Triage Agent",
            instructions=TRIAGE_INSTRUCTIONS,
            model=self.model,
            output_type=ThreadTriageBatch,
        )

        payload = json.dumps(
            {"threads": agent_threads_to_payload(threads)},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        print(f"[triage] processing {len(threads)} threads")
        print(f"[triage] payload size: {len(payload.encode('utf-8'))} bytes")
        result = run_with_retry(
            lambda: Runner.run_sync(agent, payload),
            step_name="Triage step",
        )
        return result.final_output
