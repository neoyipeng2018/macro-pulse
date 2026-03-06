"""Application settings loaded from environment variables."""

import logging
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings

logger = logging.getLogger("macro-pulse.settings")


def _load_yaml(filename: str) -> dict:
    path = Path(__file__).parent / filename
    if path.exists():
        with open(path) as f:
            return yaml.safe_load(f) or {}
    return {}


def _load_streamlit_secrets() -> dict[str, str]:
    """Load secrets from Streamlit Cloud (st.secrets) if available."""
    try:
        import streamlit as st
        secrets = {}
        for key in (
            "GOOGLE_SHEETS_CREDENTIALS_FILE",
            "GOOGLE_SHEETS_SPREADSHEET_ID",
            "ANTHROPIC_API_KEY",
            "CEREBRAS_API_KEY",
            "FRED_API_KEY",
            "REDDIT_CLIENT_ID",
            "REDDIT_CLIENT_SECRET",
            "TWITTER_BEARER_TOKEN",
            "FINNHUB_API_KEY",
        ):
            if key in st.secrets:
                secrets[key.lower()] = st.secrets[key]
        return secrets
    except Exception:
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

    @property
    def assets(self) -> dict:
        return _load_yaml("assets.yaml")

    @property
    def sources(self) -> dict:
        return _load_yaml("sources.yaml")


def _build_settings() -> Settings:
    """Build settings, overlaying Streamlit secrets on top of env vars."""
    st_secrets = _load_streamlit_secrets()
    if st_secrets:
        logger.debug("Loaded %d settings from Streamlit secrets", len(st_secrets))
        return Settings(**st_secrets)
    return Settings()


settings = _build_settings()
