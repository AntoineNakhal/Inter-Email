"""Local agent package plus a helper for loading the OpenAI Agents SDK.

This project intentionally has a local `agents/` folder because it keeps the
workflow easy to navigate. The OpenAI Agents SDK also uses the module name
`agents`, so we load the external SDK carefully to avoid a naming collision.
"""

from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any, Callable


def load_openai_agents_sdk() -> ModuleType:
    """Load the external OpenAI Agents SDK despite the local package name.

    We temporarily remove this project path from `sys.path`, import the SDK's
    `agents` module, then restore the local package. This keeps the V1 folder
    structure simple while still using the real SDK.
    """

    project_path = str(Path(__file__).resolve().parents[1])
    local_agents_module = sys.modules.get("agents")
    original_sys_path = list(sys.path)

    try:
        sys.modules.pop("agents", None)
        sys.path = [path for path in sys.path if Path(path).resolve() != Path(project_path)]
        sdk_module = importlib.import_module("agents")
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "OpenAI Agents SDK is not installed. Run: pip install -r requirements.txt"
        ) from exc
    finally:
        sys.path = original_sys_path
        if local_agents_module is not None:
            sys.modules["agents"] = local_agents_module

    return sdk_module


def run_with_retry(operation: Callable[[], Any], step_name: str, attempts: int = 3) -> Any:
    """Retry only 500-level server failures with exponential backoff."""

    last_error: Exception | None = None
    retry_delays = (2, 5, 10)

    for attempt in range(1, len(retry_delays) + 2):
        try:
            return operation()
        except Exception as exc:
            last_error = exc
            status_code = getattr(exc, "status_code", None)
            message = str(exc).lower()
            is_retryable = status_code == 500 or (
                "500" in message and "internal server error" in message
            )

            if not is_retryable or attempt > len(retry_delays):
                raise RuntimeError(
                    f"{step_name} failed after {attempt} attempt(s): {exc}"
                ) from exc

            wait_seconds = retry_delays[attempt - 1]
            print(
                f"[retry] {step_name} failed with a server error on attempt {attempt}. "
                f"Retrying in {wait_seconds} seconds."
            )
            time.sleep(wait_seconds)

    if last_error is not None:
        raise last_error
