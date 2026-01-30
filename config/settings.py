"""Configuration management using pydantic-settings."""
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings


def _compute_current_season() -> int:
    """
    Compute the current football season year.

    API-Football uses the starting year of the season (2025 for 2025-26).
    Football seasons run Aug-May, so Jan-Jul uses previous year's season code.
    """
    now = datetime.now()
    # If we're in Jan-Jul, we're still in last year's season
    if now.month <= 7:
        return now.year - 1
    return now.year


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # API-Football configuration
    api_football_key: Optional[str] = None
    api_football_base_url: str = "https://v3.football.api-sports.io"

    # Claude LLM configuration (for search fallback)
    anthropic_api_key: Optional[str] = None

    # Cache settings
    cache_enabled: bool = True
    cache_directory: Path = Path("./cache")
    cache_ttl_seconds: int = 3600

    # Output settings
    output_directory: Path = Path("./output")

    # Rate limiting
    requests_per_minute: int = 30

    # Premier League ID for API-Football
    premier_league_id: int = 39

    # Current season (single source of truth)
    # Computed dynamically: Jan-Jul = previous year, Aug-Dec = current year
    current_season: int = _compute_current_season()

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
