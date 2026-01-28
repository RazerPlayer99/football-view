"""Configuration management using pydantic-settings."""
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings


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
    current_season: int = 2024

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
