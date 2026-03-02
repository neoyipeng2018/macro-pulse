"""Application settings loaded from environment variables."""

from pathlib import Path

import yaml
from pydantic_settings import BaseSettings


def _load_yaml(filename: str) -> dict:
    path = Path(__file__).parent / filename
    if path.exists():
        with open(path) as f:
            return yaml.safe_load(f) or {}
    return {}


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # LLM providers
    anthropic_api_key: str = ""
    cerebras_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"
    cerebras_model: str = "gpt-oss-120b"

    # Data sources
    fred_api_key: str = ""
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    twitter_bearer_token: str = ""
    finnhub_api_key: str = ""

    # Google Sheets export
    google_sheets_credentials_file: str = ""
    google_sheets_spreadsheet_id: str = ""

    # App config
    max_narratives: int = 30
    narrative_lookback_weeks: int = 12

    @property
    def assets(self) -> dict:
        return _load_yaml("assets.yaml")

    @property
    def sources(self) -> dict:
        return _load_yaml("sources.yaml")


settings = Settings()
