"""Application configuration.

Loads environment variables once at import time. Centralising config here
keeps secrets out of code and makes it easy to point the same code at
local DuckDB, Postgres, or Synapse by changing `WAREHOUSE_PATH` / `DB_URL`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

# Load .env (no-op if not present, e.g. in production)
load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent  # src/config.py -> project root


def _env(key: str, default: str | None = None) -> str | None:
    """Read an env var, treating empty strings as unset."""
    val = os.getenv(key, default)
    return val if val not in (None, "") else default


def _env_str(key: str, default: str) -> str:
    """Same, for settings that always have a value — keeps the field type `str`."""
    val = _env(key, default)
    return val if val is not None else default


def resolve_database_url() -> str | None:
    """Return the Postgres URI, assembling it from parts when asked to.

    A URI embeds the password in a field with its own escaping rules, so a
    password containing ``/``, ``@``, ``:`` or ``%`` must be percent-encoded by
    hand. Getting that wrong produces *"password authentication failed"* — a
    message that sends you off rotating a password that was never wrong. That
    exact mistake left this warehouse unrefreshed for 72 days.

    So: set ``DATABASE_URL`` directly if you like (unchanged behaviour), or set
    ``DB_PASSWORD`` alongside ``DB_HOST``/``DB_USER`` and let ``quote()`` do the
    encoding. The latter cannot be got wrong by hand.
    """
    explicit = _env("DATABASE_URL")
    if explicit:
        return explicit

    host = _env("DB_HOST")
    user = _env("DB_USER")
    password = _env("DB_PASSWORD")
    if not (host and user and password):
        return None

    return (
        f"postgresql+psycopg2://{quote(user, safe='')}:{quote(password, safe='')}"
        f"@{host}:{_env_str('DB_PORT', '5432')}/{_env_str('DB_NAME', 'postgres')}"
        f"?sslmode={_env_str('DB_SSLMODE', 'require')}"
    )


# Not frozen: the warehouse/data paths are overridable at runtime (e.g. tests
# point them at a tmp dir, deployments point them at Postgres/Synapse).
@dataclass
class Settings:
    # ---- paths ----
    project_root: Path = PROJECT_ROOT
    bronze_path: Path = Path(_env_str("BRONZE_PATH", str(PROJECT_ROOT / "data" / "raw")))
    silver_path: Path = Path(_env_str("SILVER_PATH", str(PROJECT_ROOT / "data" / "processed")))
    gold_path: Path = Path(_env_str("GOLD_PATH", str(PROJECT_ROOT / "data" / "gold")))
    warehouse_path: Path = Path(
        _env_str("WAREHOUSE_PATH", str(PROJECT_ROOT / "data" / "gold" / "warehouse.duckdb"))
    )
    # PostgreSQL system-of-record (managed cloud or local). When set, the API
    # and publisher use it; the offline batch pipeline still builds the gold
    # tables in DuckDB and `publish_to_postgres` loads them here.
    database_url: str | None = field(default_factory=resolve_database_url)

    # ---- LLM ----
    # Default provider is Anthropic (Claude). Set LLM_PROVIDER=openrouter|openai|azure|ollama to switch.
    llm_provider: str = _env_str("LLM_PROVIDER", "anthropic")
    anthropic_api_key: str | None = _env("ANTHROPIC_API_KEY")
    anthropic_model: str = _env_str("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    openai_api_key: str | None = _env("OPENAI_API_KEY")
    openai_model: str = _env_str("OPENAI_MODEL", "gpt-4o-mini")
    # OpenRouter (OpenAI-compatible gateway to many models)
    openrouter_api_key: str | None = _env("OPENROUTER_API_KEY")
    openrouter_model: str = _env_str("OPENROUTER_MODEL", "anthropic/claude-sonnet-4.6")
    openrouter_base_url: str = _env_str("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    # Let the (slow, optional) LLM rewrite rule-based recommendations. Off by
    # default so the batch pipeline stays fast and deterministic.
    recommender_use_llm: bool = _env_str("RECOMMENDER_USE_LLM", "false").lower() in ("1", "true", "yes")
    azure_openai_endpoint: str | None = _env("AZURE_OPENAI_ENDPOINT")
    azure_openai_deployment: str | None = _env("AZURE_OPENAI_DEPLOYMENT")
    azure_openai_api_key: str | None = _env("AZURE_OPENAI_API_KEY")

    # ---- runtime ----
    log_level: str = _env_str("LOG_LEVEL", "INFO")
    app_env: str = _env_str("APP_ENV", "local")

    # ---- API ----
    # Optional API-key auth. When set, every /api/* route (except health) requires
    # an `X-API-Key` header matching this value; when unset, the API is open.
    api_key: str | None = _env("API_KEY")
    # Comma-separated allowed CORS origins for the React frontend.
    cors_origins: tuple[str, ...] = tuple(
        o.strip() for o in _env_str(
            "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000"
        ).split(",") if o.strip()
    )

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
