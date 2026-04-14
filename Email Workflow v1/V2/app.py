"""Entry point for the Gmail triage V2 app."""

from pathlib import Path

from dotenv import load_dotenv

from agents.manager_agent import TriageManager
from config import get_settings
from services.progress_state import WorkflowProgressTracker


def main() -> None:
    """Load settings, run the workflow, and save the final JSON output."""

    progress_tracker = WorkflowProgressTracker()
    progress_tracker.update("startup", 2, "Preparing refresh...")
    env_path = Path(__file__).resolve().parent / ".env"
    try:
        load_dotenv(env_path if env_path.exists() else None)

        settings = get_settings()
        print(f"Using Gmail token file: {settings.gmail_token_file}")
        print(f"Resolved Gmail token path: {settings.token_path}")
        manager = TriageManager(settings, progress_tracker=progress_tracker)
        result = manager.run()

        progress_tracker.update("writing_output", 96, "Saving refreshed output...")
        output_path = settings.resolved_output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")

        print(f"Saved triage output to: {output_path}")
        progress_tracker.mark_complete("Refresh complete.")
    except Exception as exc:
        progress_tracker.mark_error(f"Refresh failed: {exc}")
        raise


if __name__ == "__main__":
    main()
