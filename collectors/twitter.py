"""Twitter/X collector — placeholder, requires API key."""

import logging

from collectors.base import BaseCollector
from config.settings import settings
from models.schemas import Signal

logger = logging.getLogger(__name__)


class TwitterCollector(BaseCollector):
    """Placeholder collector for Twitter/X macro signals."""

    source_name = "twitter"

    def collect(self) -> list[Signal]:
        if not settings.twitter_bearer_token:
            logger.info("TWITTER_BEARER_TOKEN not set, skipping Twitter collection")
            return []

        # TODO: Implement Twitter API v2 search for macro keywords
        # Suggested queries: "fed rate", "inflation", "USD", "gold",
        #   "bitcoin", "recession", "tariff"
        # Filter by verified accounts / high-follower macro accounts
        logger.info("Twitter collector not yet implemented")
        return []
