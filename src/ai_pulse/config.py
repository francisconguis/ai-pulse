"""Application configuration loaded from environment variables and .env files."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    """Central runtime configuration for AI Pulse."""

    db_path: Path
    export_dir: Path
    gemini_api_key: str | None
    gemini_model: str
    openai_api_key: str | None
    openai_model: str
    max_items_per_source: int
    request_timeout: float
    schedule_minutes: int
    user_agent: str = "AIPulseBot/0.1 (+https://github.com/ai-pulse; educational portfolio project)"

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            db_path=Path(os.getenv("AI_PULSE_DB_PATH", "data/ai_pulse.db")),
            export_dir=Path(os.getenv("AI_PULSE_EXPORT_DIR", "exports")),
            gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
            openai_api_key=os.getenv("OPENAI_API_KEY") or None,
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            max_items_per_source=int(os.getenv("AI_PULSE_MAX_ITEMS_PER_SOURCE", "15")),
            request_timeout=float(os.getenv("AI_PULSE_REQUEST_TIMEOUT", "20")),
            schedule_minutes=int(os.getenv("AI_PULSE_SCHEDULE_MINUTES", "180")),
        )

    @property
    def active_llm_provider(self) -> str:
        """Returns the configured LLM provider or 'heuristic' if no API key is set."""
        if self.gemini_api_key:
            return "gemini"
        if self.openai_api_key:
            return "openai"
        return "heuristic"
