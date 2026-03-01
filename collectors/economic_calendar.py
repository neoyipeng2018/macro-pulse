"""Economic calendar collector — upcoming high-impact macro events."""

import hashlib
import logging
from datetime import datetime, timedelta

import httpx

from collectors.base import BaseCollector
from config.settings import settings
from models.schemas import Signal, SignalSource

logger = logging.getLogger(__name__)

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
    """Collect upcoming high-impact economic events from Finnhub or fallback."""

    source_name = "economic_calendar"

    def __init__(self):
        cal_cfg = settings.sources.get("economic_calendar", {})
        self.lookforward_days = cal_cfg.get("lookforward_days", 14)
        self.impact_filter = set(cal_cfg.get("impact_filter", ["high", "medium"]))
        self.countries = set(cal_cfg.get("countries", ["US", "EU", "GB", "JP", "CN", "AU", "CA"]))

    def collect(self) -> list[Signal]:
        if settings.finnhub_api_key:
            return self._collect_finnhub()
        logger.info("FINNHUB_API_KEY not set, using hardcoded FOMC fallback")
        return self._collect_fomc_fallback()

    def _collect_finnhub(self) -> list[Signal]:
        """Fetch upcoming events from Finnhub economic calendar API."""
        today = datetime.utcnow().date()
        from_date = today.isoformat()
        to_date = (today + timedelta(days=self.lookforward_days)).isoformat()

        url = "https://finnhub.io/api/v1/calendar/economic"
        params = {
            "from": from_date,
            "to": to_date,
            "token": settings.finnhub_api_key,
        }

        try:
            resp = httpx.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error("Finnhub calendar API error: %s", e)
            return self._collect_fomc_fallback()

        events = data.get("economicCalendar", [])
        if not events:
            logger.info("No upcoming events from Finnhub")
            return self._collect_fomc_fallback()

        signals: list[Signal] = []
        for event in events:
            signals_from_event = self._event_to_signal(event)
            if signals_from_event:
                signals.append(signals_from_event)

        logger.info("Collected %d upcoming economic events from Finnhub", len(signals))
        return signals

    def _event_to_signal(self, event: dict) -> Signal | None:
        """Convert a Finnhub calendar event to a Signal."""
        impact = (event.get("impact") or "low").lower()
        country = (event.get("country") or "").upper()

        if impact not in self.impact_filter:
            return None
        if country and country not in self.countries:
            return None

        event_name = event.get("event", "Unknown Event")
        scheduled_time = event.get("time", "")
        event_date = event.get("date", "")
        estimate = event.get("estimate")
        prev = event.get("prev")
        actual = event.get("actual")
        unit = event.get("unit", "")

        sig_id = hashlib.md5(
            f"cal_{event_name}_{event_date}".encode()
        ).hexdigest()[:12]

        # Build descriptive content
        parts = [f"Scheduled: {event_date}"]
        if scheduled_time:
            parts.append(f"at {scheduled_time}")
        parts.append(f"| Country: {country} | Impact: {impact.upper()}")
        if estimate is not None:
            parts.append(f"| Consensus estimate: {estimate}{unit}")
        if prev is not None:
            parts.append(f"| Previous: {prev}{unit}")
        if actual is not None:
            parts.append(f"| Actual: {actual}{unit}")

        content = " ".join(parts)

        try:
            ts = datetime.fromisoformat(event_date) if event_date else datetime.utcnow()
        except (ValueError, TypeError):
            ts = datetime.utcnow()

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
                "scheduled_time": scheduled_time,
                "estimate": estimate,
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
