"""Runtime configuration, read from environment variables and an optional .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SAMPLES_DIR = ROOT / "data" / "samples"
AUDIT_PATH = Path(os.getenv("ECOMETRIC_AUDIT_PATH", str(ROOT / "data" / "audit_log.jsonl")))
FRONTEND_DIR = ROOT / "frontend"


def _load_dotenv() -> None:
    """Load KEY=VALUE pairs from ROOT/.env without overriding real environment variables."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


@dataclass(frozen=True)
class Settings:
    provider: str
    gemini_api_key: str
    gemini_model: str
    ollama_url: str
    ollama_model: str
    llm_timeout: float
    narrate: bool
    max_upload_mb: float
    max_rows: int
    max_columns: int
    max_datasets: int


def get_settings() -> Settings:
    """Build settings from the current environment (read on every call so tests can override)."""
    return Settings(
        provider=os.getenv("ECOMETRIC_PROVIDER", "auto").strip().lower(),
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        gemini_model=os.getenv("GEMINI_MODEL", "gemma-4-26b-a4b-it").strip(),
        ollama_url=os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/"),
        ollama_model=os.getenv("OLLAMA_MODEL", "gemma4:e2b").strip(),
        llm_timeout=float(os.getenv("LLM_TIMEOUT", "60")),
        narrate=os.getenv("ECOMETRIC_NARRATE", "1").strip() == "1",
        max_upload_mb=float(os.getenv("MAX_UPLOAD_MB", "5")),
        max_rows=int(os.getenv("MAX_ROWS", "100000")),
        max_columns=int(os.getenv("MAX_COLUMNS", "60")),
        max_datasets=int(os.getenv("MAX_DATASETS", "20")),
    )
