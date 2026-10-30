from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    platform_database_url: str | None = None
    app_env: str = "demo"
    data_provider: str = "auto"
    uqer_token: str | None = None
    market_cache_dir: Path = PROJECT_ROOT / "var" / "market"
    market_ticker: str = "c2701"
    data_start_date: str = "2025-12-31"
    data_end_date: str = "2026-10-23"
    comparison_store_dir: Path = PROJECT_ROOT / "var" / "comparison"
    model_store_dir: Path = PROJECT_ROOT / "var" / "models"
    price_store_dir: Path = PROJECT_ROOT / "var" / "price"
    comparison_data_mode: str = "measured"
    cors_origins: str = "http://localhost:5173,http://frontend:8080"
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
