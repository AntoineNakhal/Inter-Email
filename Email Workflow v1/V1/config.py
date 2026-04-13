"""Configuration helpers for environment-driven settings."""

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, field_validator


STABLE_OPENAI_MODELS = {"gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini"}
PROCESSING_MODES = {"ai", "fallback"}


class Settings(BaseModel):
    """Small settings object that keeps environment variables in one place."""

    openai_api_key: str = Field(..., alias="OPENAI_API_KEY")
    openai_model: str = Field("gpt-4.1-mini", alias="OPENAI_MODEL")
    gmail_credentials_file: str = Field(..., alias="GMAIL_CREDENTIALS_FILE")
    gmail_token_file: str = Field(..., alias="GMAIL_TOKEN_FILE")
    gmail_max_results: int = Field(10, alias="GMAIL_MAX_RESULTS")
    ai_max_emails: int = Field(5, alias="AI_MAX_EMAILS")
    ai_relevance_threshold: int = Field(3, alias="AI_RELEVANCE_THRESHOLD")
    processing_mode: str = Field("ai", alias="PROCESSING_MODE")
    output_file: str = Field("data/outputs/latest_run.json", alias="OUTPUT_FILE")

    @field_validator("openai_model", mode="before")
    @classmethod
    def validate_openai_model(cls, value: str) -> str:
        normalized = (value or "").strip()
        if normalized in STABLE_OPENAI_MODELS:
            return normalized
        return "gpt-4.1-mini"

    @field_validator("ai_max_emails", mode="before")
    @classmethod
    def validate_ai_max_emails(cls, value: int | str) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 5
        return max(1, parsed)

    @field_validator("gmail_max_results", mode="before")
    @classmethod
    def validate_gmail_max_results(cls, value: int | str) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 10
        return max(1, parsed)

    @field_validator("ai_relevance_threshold", mode="before")
    @classmethod
    def validate_ai_relevance_threshold(cls, value: int | str) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 3
        return max(1, min(parsed, 5))

    @field_validator("processing_mode", mode="before")
    @classmethod
    def validate_processing_mode(cls, value: str) -> str:
        normalized = (value or "ai").strip().lower()
        if normalized in PROCESSING_MODES:
            return normalized
        return "ai"

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parent

    @property
    def credentials_path(self) -> Path:
        return self.project_root / self.gmail_credentials_file

    @property
    def token_path(self) -> Path:
        return self.project_root / self.gmail_token_file

    @property
    def resolved_output_path(self) -> Path:
        return self.project_root / self.output_file


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Build settings from environment variables.

    We use `BaseModel.model_validate` so we can keep the code lightweight
    without adding another configuration package for this V1.
    """

    import os

    raw_values = {
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
        "OPENAI_MODEL": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        "GMAIL_CREDENTIALS_FILE": os.getenv(
            "GMAIL_CREDENTIALS_FILE", "data/raw/google_credentials.json"
        ),
        "GMAIL_TOKEN_FILE": os.getenv(
            "GMAIL_TOKEN_FILE", "data/raw/google_token.json"
        ),
        "GMAIL_MAX_RESULTS": os.getenv("GMAIL_MAX_RESULTS", "10"),
        "AI_MAX_EMAILS": os.getenv("AI_MAX_EMAILS", "5"),
        "AI_RELEVANCE_THRESHOLD": os.getenv("AI_RELEVANCE_THRESHOLD", "3"),
        "PROCESSING_MODE": os.getenv("PROCESSING_MODE", "ai"),
        "OUTPUT_FILE": os.getenv("OUTPUT_FILE", "data/outputs/latest_run.json"),
    }
    return Settings.model_validate(raw_values)
