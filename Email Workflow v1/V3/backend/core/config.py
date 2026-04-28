"""Environment-driven configuration for V3."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class AppSettings(BaseModel):
    """Small settings object for local, self-hosted, and cloud runs."""

    app_env: str = Field("local", alias="APP_ENV")
    api_host: str = Field("0.0.0.0", alias="API_HOST")
    api_port: int = Field(8000, alias="API_PORT")
    frontend_port: int = Field(5173, alias="FRONTEND_PORT")
    frontend_app_url: str = Field(
        "http://localhost:5173",
        alias="FRONTEND_APP_URL",
    )
    frontend_api_base_url: str = Field(
        "http://localhost:8000",
        alias="VITE_API_BASE_URL",
    )
    database_url: str = Field(
        "sqlite:///./data/sqlite/app.db",
        alias="DATABASE_URL",
    )
    cache_dir: str = Field("./data/cache", alias="CACHE_DIR")
    export_dir: str = Field("./data/exports", alias="EXPORT_DIR")
    gmail_credentials_path: str = Field(
        "./data/raw/google_credentials.json",
        alias="GMAIL_CREDENTIALS_PATH",
    )
    gmail_token_dir: str = Field(
        "./data/raw/gmail_tokens",
        alias="GMAIL_TOKEN_DIR",
    )
    gmail_token_file: str | None = Field(
        None,
        alias="GMAIL_TOKEN_FILE",
    )
    gmail_max_results: int = Field(50, alias="GMAIL_MAX_RESULTS")
    gmail_thread_source: str = Field("anywhere", alias="GMAIL_THREAD_SOURCE")
    ai_default_provider: str = Field("openai", alias="AI_DEFAULT_PROVIDER")
    ai_thread_analysis_provider: str = Field(
        "openai",
        alias="AI_THREAD_ANALYSIS_PROVIDER",
    )
    ai_queue_summary_provider: str = Field(
        "openai",
        alias="AI_QUEUE_SUMMARY_PROVIDER",
    )
    ai_draft_provider: str = Field("openai", alias="AI_DRAFT_PROVIDER")
    ai_crm_provider: str = Field("openai", alias="AI_CRM_PROVIDER")
    openai_api_key: str = Field("", alias="OPENAI_API_KEY")
    openai_model_thread_analysis: str = Field(
        "gpt-4.1-mini",
        alias="OPENAI_MODEL_THREAD_ANALYSIS",
    )
    openai_model_queue_summary: str = Field(
        "gpt-4.1-mini",
        alias="OPENAI_MODEL_QUEUE_SUMMARY",
    )
    openai_model_draft: str = Field("gpt-4.1", alias="OPENAI_MODEL_DRAFT")
    openai_model_crm: str = Field("gpt-4.1-mini", alias="OPENAI_MODEL_CRM")
    ollama_base_url: str = Field(
        "http://localhost:11434",
        alias="OLLAMA_BASE_URL",
    )
    ollama_model_thread_analysis: str = Field(
        "",
        alias="OLLAMA_MODEL_THREAD_ANALYSIS",
    )
    ollama_model_queue_summary: str = Field(
        "",
        alias="OLLAMA_MODEL_QUEUE_SUMMARY",
    )
    ollama_model_draft: str = Field("", alias="OLLAMA_MODEL_DRAFT")
    ollama_model_crm: str = Field("", alias="OLLAMA_MODEL_CRM")
    # Anthropic / Claude. Matches the SDK env var convention.
    anthropic_api_key: str = Field("", alias="ANTHROPIC_API_KEY")
    anthropic_model_thread_analysis: str = Field(
        "claude-haiku-4-5-20251001",
        alias="ANTHROPIC_MODEL_THREAD_ANALYSIS",
    )
    anthropic_model_queue_summary: str = Field(
        "claude-haiku-4-5-20251001",
        alias="ANTHROPIC_MODEL_QUEUE_SUMMARY",
    )
    anthropic_model_draft: str = Field(
        "claude-haiku-4-5-20251001",
        alias="ANTHROPIC_MODEL_DRAFT",
    )
    anthropic_model_crm: str = Field(
        "claude-haiku-4-5-20251001",
        alias="ANTHROPIC_MODEL_CRM",
    )
    app_root: Path = Field(default_factory=lambda: Path(__file__).resolve().parents[2])

    @field_validator("gmail_max_results", mode="before")
    @classmethod
    def validate_gmail_max_results(cls, value: int | str) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 50
        return max(1, parsed)

    @field_validator("api_port", "frontend_port", mode="before")
    @classmethod
    def validate_port(cls, value: int | str) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 8000
        return max(1, parsed)

    @property
    def resolved_cache_dir(self) -> Path:
        return (self.app_root / self.cache_dir).resolve()

    @property
    def resolved_export_dir(self) -> Path:
        return (self.app_root / self.export_dir).resolve()

    @property
    def resolved_gmail_credentials_path(self) -> Path:
        return (self.app_root / self.gmail_credentials_path).resolve()

    @property
    def resolved_gmail_token_path(self) -> Path:
        if self.gmail_token_file:
            return (self.app_root / self.gmail_token_file).resolve()
        token_dir = (self.app_root / self.gmail_token_dir).resolve()
        return token_dir / "google_token.json"

    @property
    def resolved_gmail_token_candidate_paths(self) -> list[Path]:
        candidates = [
            self.resolved_gmail_token_path,
            (self.app_root / "./data/raw/gmail_tokens/google_token.json").resolve(),
            (self.app_root / "./data/raw/gmail_tokens/default.json").resolve(),
            (self.app_root / "./data/raw/google_token.json").resolve(),
        ]
        deduped: list[Path] = []
        seen: set[str] = set()
        for candidate in candidates:
            normalized = str(candidate)
            if normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(candidate)
        return deduped

    def provider_for_task(self, task: str) -> str:
        normalized = str(task or "").strip().lower()
        mapping = {
            "thread_analysis": self.ai_thread_analysis_provider,
            "thread_verification": self.ai_thread_analysis_provider,
            "queue_summary": self.ai_queue_summary_provider,
            "draft_reply": self.ai_draft_provider,
            "crm_extraction": self.ai_crm_provider,
        }
        return mapping.get(normalized, self.ai_default_provider).strip().lower()

    def model_for_provider_task(self, provider_name: str, task: str) -> str:
        provider = str(provider_name or "").strip().lower()
        normalized = str(task or "").strip().lower()
        if provider == "openai":
            mapping = {
                "thread_analysis": self.openai_model_thread_analysis,
                "thread_verification": self.openai_model_thread_analysis,
                "queue_summary": self.openai_model_queue_summary,
                "draft_reply": self.openai_model_draft,
                "crm_extraction": self.openai_model_crm,
            }
            return mapping.get(normalized, self.openai_model_thread_analysis)
        if provider == "ollama":
            mapping = {
                "thread_analysis": self.ollama_model_thread_analysis,
                "thread_verification": self.ollama_model_thread_analysis,
                "queue_summary": self.ollama_model_queue_summary,
                "draft_reply": self.ollama_model_draft,
                "crm_extraction": self.ollama_model_crm,
            }
            return mapping.get(normalized, "")
        if provider == "anthropic":
            mapping = {
                "thread_analysis": self.anthropic_model_thread_analysis,
                "thread_verification": self.anthropic_model_thread_analysis,
                "queue_summary": self.anthropic_model_queue_summary,
                "draft_reply": self.anthropic_model_draft,
                "crm_extraction": self.anthropic_model_crm,
            }
            return mapping.get(normalized, self.anthropic_model_thread_analysis)
        return "deterministic-fallback"

    def ensure_runtime_directories(self) -> None:
        self.resolved_cache_dir.mkdir(parents=True, exist_ok=True)
        self.resolved_export_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Build settings from environment variables once per process."""

    raw_values = {
        "APP_ENV": os.getenv("APP_ENV", "local"),
        "API_HOST": os.getenv("API_HOST", "0.0.0.0"),
        "API_PORT": os.getenv("API_PORT", "8000"),
        "FRONTEND_PORT": os.getenv("FRONTEND_PORT", "5173"),
        "FRONTEND_APP_URL": os.getenv("FRONTEND_APP_URL", "http://localhost:5173"),
        "VITE_API_BASE_URL": os.getenv("VITE_API_BASE_URL", "http://localhost:8000"),
        "DATABASE_URL": os.getenv("DATABASE_URL", "sqlite:///./data/sqlite/app.db"),
        "CACHE_DIR": os.getenv("CACHE_DIR", "./data/cache"),
        "EXPORT_DIR": os.getenv("EXPORT_DIR", "./data/exports"),
        "GMAIL_CREDENTIALS_PATH": os.getenv(
            "GMAIL_CREDENTIALS_PATH",
            os.getenv(
                "GMAIL_CREDENTIALS_FILE",
                "./data/raw/google_credentials.json",
            ),
        ),
        "GMAIL_TOKEN_DIR": os.getenv("GMAIL_TOKEN_DIR", "./data/raw/gmail_tokens"),
        "GMAIL_TOKEN_FILE": os.getenv("GMAIL_TOKEN_FILE"),
        "GMAIL_MAX_RESULTS": os.getenv("GMAIL_MAX_RESULTS", "50"),
        "GMAIL_THREAD_SOURCE": os.getenv("GMAIL_THREAD_SOURCE", "anywhere"),
        "AI_DEFAULT_PROVIDER": os.getenv("AI_DEFAULT_PROVIDER", "openai"),
        "AI_THREAD_ANALYSIS_PROVIDER": os.getenv(
            "AI_THREAD_ANALYSIS_PROVIDER",
            "openai",
        ),
        "AI_QUEUE_SUMMARY_PROVIDER": os.getenv(
            "AI_QUEUE_SUMMARY_PROVIDER",
            "openai",
        ),
        "AI_DRAFT_PROVIDER": os.getenv("AI_DRAFT_PROVIDER", "openai"),
        "AI_CRM_PROVIDER": os.getenv("AI_CRM_PROVIDER", "openai"),
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
        "OPENAI_MODEL_THREAD_ANALYSIS": os.getenv(
            "OPENAI_MODEL_THREAD_ANALYSIS",
            "gpt-4.1-mini",
        ),
        "OPENAI_MODEL_QUEUE_SUMMARY": os.getenv(
            "OPENAI_MODEL_QUEUE_SUMMARY",
            "gpt-4.1-mini",
        ),
        "OPENAI_MODEL_DRAFT": os.getenv("OPENAI_MODEL_DRAFT", "gpt-4.1"),
        "OPENAI_MODEL_CRM": os.getenv("OPENAI_MODEL_CRM", "gpt-4.1-mini"),
        "OLLAMA_BASE_URL": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        "OLLAMA_MODEL_THREAD_ANALYSIS": os.getenv("OLLAMA_MODEL_THREAD_ANALYSIS", ""),
        "OLLAMA_MODEL_QUEUE_SUMMARY": os.getenv("OLLAMA_MODEL_QUEUE_SUMMARY", ""),
        "OLLAMA_MODEL_DRAFT": os.getenv("OLLAMA_MODEL_DRAFT", ""),
        "OLLAMA_MODEL_CRM": os.getenv("OLLAMA_MODEL_CRM", ""),
        "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY", ""),
        "ANTHROPIC_MODEL_THREAD_ANALYSIS": os.getenv(
            "ANTHROPIC_MODEL_THREAD_ANALYSIS",
            "claude-haiku-4-5-20251001",
        ),
        "ANTHROPIC_MODEL_QUEUE_SUMMARY": os.getenv(
            "ANTHROPIC_MODEL_QUEUE_SUMMARY",
            "claude-haiku-4-5-20251001",
        ),
        "ANTHROPIC_MODEL_DRAFT": os.getenv(
            "ANTHROPIC_MODEL_DRAFT",
            "claude-haiku-4-5-20251001",
        ),
        "ANTHROPIC_MODEL_CRM": os.getenv(
            "ANTHROPIC_MODEL_CRM",
            "claude-haiku-4-5-20251001",
        ),
    }
    return AppSettings.model_validate(raw_values)
