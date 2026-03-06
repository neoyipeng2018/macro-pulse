"""YouTube crypto analysis collector via yt-dlp."""

import hashlib
import json
import logging
import shutil
import subprocess
from datetime import datetime

from collectors.base import BaseCollector
from models.schemas import Signal, SignalSource

logger = logging.getLogger(__name__)

CHANNELS = [
    "UCqK_GSMbpiV8spgD3ZGloSw",  # Coin Bureau
    "UCRvqjQPSeaWn-uEx-w0XOIg",  # Benjamin Cowen
    "UCCatR7nWbYrkVXdxXb4cGXg",  # DataDash
    "UCVBhyBR41ckEBcJfMc_MkbQ",  # Real Vision Crypto
]

CRYPTO_KEYWORDS = [
    "bitcoin", "btc", "ethereum", "eth", "crypto", "defi",
    "altcoin", "bull", "bear", "fed", "rate", "macro",
    "solana", "sol", "halving", "etf",
]


class YouTubeCryptoCollector(BaseCollector):
    """Extract recent crypto analysis from YouTube via yt-dlp."""

    source_name = "youtube_crypto"

    def collect(self) -> list[Signal]:
        if not shutil.which("yt-dlp"):
            logger.info("yt-dlp not installed, skipping YouTube collection")
            return []

        signals: list[Signal] = []

        for channel_id in CHANNELS:
            try:
                result = subprocess.run(
                    [
                        "yt-dlp",
                        f"https://www.youtube.com/channel/{channel_id}/videos",
                        "--flat-playlist",
                        "--playlist-end", "3",
                        "--skip-download",
                        "--print-json",
                        "--no-warnings",
                    ],
                    capture_output=True, text=True, timeout=60,
                )
                if result.returncode == 0:
                    for line in result.stdout.strip().split("\n"):
                        if not line.strip():
                            continue
                        try:
                            video = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        sig = self._video_to_signal(video)
                        if sig:
                            signals.append(sig)
            except (subprocess.TimeoutExpired, OSError) as e:
                logger.warning("yt-dlp failed for channel %s: %s", channel_id, e)

        return signals

    def _video_to_signal(self, video: dict) -> Signal | None:
        title = video.get("title", "")
        if not any(kw in title.lower() for kw in CRYPTO_KEYWORDS):
            return None

        video_id = video.get("id", "")
        sig_id = hashlib.sha256(f"youtube_{video_id}".encode()).hexdigest()[:16]
        description = video.get("description", "")[:2000]

        upload_date = video.get("upload_date", "")
        try:
            ts = datetime.strptime(upload_date, "%Y%m%d") if upload_date else datetime.utcnow()
        except ValueError:
            ts = datetime.utcnow()

        return Signal(
            id=sig_id,
            source=SignalSource.YOUTUBE,
            title=f"[YouTube] {title}",
            content=f"{title}\n\n{description[:1000]}",
            url=f"https://youtube.com/watch?v={video_id}",
            timestamp=ts,
            metadata={
                "platform": "youtube",
                "channel": video.get("channel", ""),
                "view_count": video.get("view_count", 0),
                "duration": video.get("duration", 0),
                "asset_class": "crypto",
            },
        )
