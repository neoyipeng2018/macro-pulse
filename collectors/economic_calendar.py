"""Economic calendar collector — upcoming high-impact macro events."""

import hashlib
import logging
from datetime import datetime, timedelta

import httpx

from collectors.base import BaseCollector
from config.settings import settings
from models.schemas import Signal, SignalSource

logger = logging.getLogger(__name__)

CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# Country code mapping: ForexFactory uses currency codes, we normalise to ISO country
_CURRENCY_TO_COUNTRY = {
    "USD": "US", "EUR": "EU", "GBP": "GB", "JPY": "JP",
    "CNY": "CN", "AUD": "AU", "CAD": "CA", "CHF": "CH",
    "NZD": "NZ", "SEK": "SE", "NOK": "NO",
}

# Hardcoded 2025-2026 FOMC meeting dates (announcement days)
FOMC_DATES = [
    # 2025
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    # 2026
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
]


class EconomicCalendarCollector(BaseCollector):
    """Collect upcoming high-impact economic events."""

    source_name = "economic_calendar"

    def __init__(self):
        cal_cfg = settings.sources.get("economic_calendar", {})
        self.lookforward_days = cal_cfg.get("lookforward_days", 21)
        self.impact_filter = {v.lower() for v in cal_cfg.get("impact_filter", ["high", "medium"])}
        self.countries = set(cal_cfg.get("countries", ["US", "EU", "GB", "JP", "CN", "AU", "CA"]))

    def collect(self) -> list[Signal]:
        signals = self._collect_calendar_api()
        # Always merge FOMC fallback so we cover upcoming meetings beyond this week
        fomc_ids = {s.id for s in signals}
        for s in self._collect_fomc_fallback():
            if s.id not in fomc_ids:
                signals.append(s)
        if signals:
            logger.info("Economic calendar: %d upcoming events", len(signals))
        return signals

    def _collect_calendar_api(self) -> list[Signal]:
        """Fetch this week's events from the free ForexFactory calendar feed."""
        try:
            resp = httpx.get(CALENDAR_URL, timeout=15)
            resp.raise_for_status()
            events = resp.json()
        except Exception as e:
            logger.warning("Calendar API error: %s", e)
            return []

        today = datetime.utcnow()
        signals: list[Signal] = []
        for event in events:
            signal = self._event_to_signal(event, today)
            if signal:
                signals.append(signal)

        logger.info("Collected %d events from calendar API", len(signals))
        return signals

    def _event_to_signal(self, event: dict, now: datetime | None = None) -> Signal | None:
        """Convert a calendar event dict to a Signal (or None if filtered out)."""
        impact = (event.get("impact") or "low").lower()
        if impact not in self.impact_filter:
            return None

        # Normalise country: API may use currency codes (USD) or country codes (US)
        raw_country = (event.get("country") or "").upper()
        country = _CURRENCY_TO_COUNTRY.get(raw_country, raw_country)
        if country and country not in self.countries:
            return None

        event_name = event.get("title") or event.get("event") or "Unknown Event"
        event_date = event.get("date", "")
        forecast = event.get("forecast") or event.get("estimate")
        prev = event.get("previous") or event.get("prev")
        actual = event.get("actual")
        unit = event.get("unit", "")

        # Only keep future events
        try:
            ts = datetime.fromisoformat(event_date) if event_date else datetime.utcnow()
        except (ValueError, TypeError):
            ts = datetime.utcnow()

        # Compare as naive UTC to avoid tz-aware vs naive mismatch
        ts_naive = ts.replace(tzinfo=None) if ts.tzinfo else ts
        now_naive = now.replace(tzinfo=None) if now and now.tzinfo else now
        if now_naive and ts_naive < now_naive:
            return None

        sig_id = hashlib.md5(
            f"cal_{event_name}_{event_date}".encode()
        ).hexdigest()[:12]

        # Build descriptive content
        parts = [f"Scheduled: {event_date}"]
        parts.append(f"| Country: {country} | Impact: {impact.upper()}")
        if forecast is not None:
            parts.append(f"| Consensus forecast: {forecast}{unit}")
        if prev is not None:
            parts.append(f"| Previous: {prev}{unit}")
        if actual is not None:
            parts.append(f"| Actual: {actual}{unit}")

        content = " ".join(parts)

        return Signal(
            id=sig_id,
            source=SignalSource.ECONOMIC_DATA,
            title=f"[UPCOMING] {event_name} ({country})",
            content=content,
            timestamp=ts,
            metadata={
                "event_type": "economic_calendar",
                "event_name": event_name,
                "country": country,
                "impact": impact,
                "scheduled_time": event_date,
                "estimate": forecast,
                "prev": prev,
                "actual": actual,
                "is_forward_looking": True,
            },
        )

    def _collect_fomc_fallback(self) -> list[Signal]:
        """Return upcoming FOMC meeting dates as signals."""
        today = datetime.utcnow().date()
        cutoff = today + timedelta(days=self.lookforward_days)
        signals: list[Signal] = []

        for date_str in FOMC_DATES:
            meeting_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            if today <= meeting_date <= cutoff:
                days_until = (meeting_date - today).days
                sig_id = hashlib.md5(
                    f"fomc_{date_str}".encode()
                ).hexdigest()[:12]

                signals.append(
                    Signal(
                        id=sig_id,
                        source=SignalSource.ECONOMIC_DATA,
                        title=f"[UPCOMING] FOMC Rate Decision (US)",
                        content=(
                            f"Federal Reserve FOMC meeting concludes {date_str} "
                            f"({days_until} days away). Rate decision and statement "
                            f"to be released. Key catalyst for USD, bonds, and risk assets."
                        ),
                        timestamp=datetime.strptime(date_str, "%Y-%m-%d"),
                        metadata={
                            "event_type": "economic_calendar",
                            "event_name": "FOMC Rate Decision",
                            "country": "US",
                            "impact": "high",
                            "scheduled_time": date_str,
                            "estimate": None,
                            "prev": None,
                            "is_forward_looking": True,
                        },
                    )
                )

        logger.info("FOMC fallback: %d upcoming meetings within %d days", len(signals), self.lookforward_days)
        return signals
