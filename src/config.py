"""Application configuration.

Loads environment variables once at import time. Centralising config here
keeps secrets out of code and makes it easy to point the same code at
local DuckDB, Postgres, or Synapse by changing `WAREHOUSE_PATH` / `DB_URL`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load .env (no-op if not present, e.g. in production)
load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent  # src/config.py -> project root


def _env(key: str, default: Optional[str] = None) -> Optional[str]:
    val = os.getenv(key, default)
    return val if val not in (None, "") else default


# Not frozen: the warehouse/data paths are overridable at runtime (e.g. tests
# point them at a tmp dir, deployments point them at Postgres/Synapse).
@dataclass
class Settings:
    # ---- paths ----
    project_root: Path = PROJECT_ROOT
    bronze_path: Path = Path(_env("BRONZE_PATH", str(PROJECT_ROOT / "data" / "raw")))
    silver_path: Path = Path(_env("SILVER_PATH", str(PROJECT_ROOT / "data" / "processed")))
    gold_path: Path = Path(_env("GOLD_PATH", str(PROJECT_ROOT / "data" / "gold")))
    warehouse_path: Path = Path(
        _env("WAREHOUSE_PATH", str(PROJECT_ROOT / "data" / "gold" / "warehouse.duckdb"))
    )

    # ---- LLM ----
    # Default provider is Anthropic (Claude). Set LLM_PROVIDER=openrouter|openai|azure|ollama to switch.
    llm_provider: str = _env("LLM_PROVIDER", "anthropic")
    anthropic_api_key: Optional[str] = _env("ANTHROPIC_API_KEY")
    anthropic_model: str = _env("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    openai_api_key: Optional[str] = _env("OPENAI_API_KEY")
    openai_model: str = _env("OPENAI_MODEL", "gpt-4o-mini")
    # OpenRouter (OpenAI-compatible gateway to many models)
    openrouter_api_key: Optional[str] = _env("OPENROUTER_API_KEY")
    openrouter_model: str = _env("OPENROUTER_MODEL", "anthropic/claude-sonnet-4.6")
    openrouter_base_url: str = _env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    azure_openai_endpoint: Optional[str] = _env("AZURE_OPENAI_ENDPOINT")
    azure_openai_deployment: Optional[str] = _env("AZURE_OPENAI_DEPLOYMENT")
    azure_openai_api_key: Optional[str] = _env("AZURE_OPENAI_API_KEY")

    # ---- runtime ----
    log_level: str = _env("LOG_LEVEL", "INFO")
    app_env: str = _env("APP_ENV", "local")

    # ---- analytics ----
    forecast_horizons: tuple[int, ...] = (30, 60, 90)

    # ---- allowlist of tables the LLM is allowed to query ----
    allowed_tables: tuple[str, ...] = field(
        default_factory=lambda: (
            "v_national_pressure",
            "v_regional_risk_latest",
            "v_forecast_long",
            "v_top_risk_trusts",
            "hospital_activity_fact",
            "dim_hospital",
            "dim_specialty",
            "dim_region",
            "ml_forecast",
            "risk_score",
            "recommendation",
        )
    )


settings = Settings()


def ensure_dirs() -> None:
    """Create data dirs on first run."""
    for p in (settings.bronze_path, settings.silver_path, settings.gold_path):
        p.mkdir(parents=True, exist_ok=True)
