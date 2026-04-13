"""Tiny direct OpenAI API test for debugging agent failures."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


def main() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(env_path if env_path.exists() else None)

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip() or "gpt-4.1-mini"
    models_to_try = [model, "gpt-4o-mini", "gpt-4.1-mini"]
    seen: set[str] = set()
    ordered_models: list[str] = []
    for item in models_to_try:
        if item not in seen:
            ordered_models.append(item)
            seen.add(item)

    if not api_key:
        raise ValueError("OPENAI_API_KEY is missing in .env")

    client = OpenAI(api_key=api_key)

    for current_model in ordered_models:
        print(f"Testing direct OpenAI call with model: {current_model}")
        try:
            response = client.responses.create(
                model=current_model,
                input="Reply with exactly this JSON: {\"ok\": true}",
            )
            print("Direct API call succeeded.")
            print(response.output_text)
            return
        except Exception as exc:
            print(f"Model failed: {current_model}")
            print(str(exc))

    raise RuntimeError("All test models failed.")


if __name__ == "__main__":
    main()
