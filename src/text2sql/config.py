"""Application settings loaded from environment variables / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env", override=True)


@dataclass(frozen=True, slots=True)
class Settings:
    # Ollama local LLM
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    # Database & app
    default_dialect: str = os.getenv("DEFAULT_SQL_DIALECT", "sqlite")
    database_url: str = os.getenv("DATABASE_URL", "")
    retrieval_top_k: int = int(os.getenv("RETRIEVAL_TOP_K", "6"))
    max_rows: int = int(os.getenv("MAX_RESULT_ROWS", "200"))
    query_timeout_seconds: int = int(os.getenv("QUERY_TIMEOUT_SECONDS", "15"))
    max_repair_attempts: int = int(os.getenv("MAX_REPAIR_ATTEMPTS", "1"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()
