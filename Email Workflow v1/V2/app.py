"""Entry point for the Gmail triage V2 app."""

from pathlib import Path

from dotenv import load_dotenv

from agents.manager_agent import TriageManager
from config import get_settings


def main() -> None:
    """Load settings, run the workflow, and save the final JSON output."""
    env_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(env_path if env_path.exists() else None)

    settings = get_settings()
    print(f"Using Gmail token file: {settings.gmail_token_file}")
    print(f"Resolved Gmail token path: {settings.token_path}")
    manager = TriageManager(settings)
    result = manager.run()

    output_path = settings.resolved_output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")

    print(f"Saved triage output to: {output_path}")


if __name__ == "__main__":
    main()
