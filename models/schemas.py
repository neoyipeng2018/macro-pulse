"""Pydantic models for macro-pulse: weekly directional sentiment per asset class."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class SentimentDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class AssetClass(str, Enum):
    FX = "fx"
    METALS = "metals"
    ENERGY = "energy"
    CRYPTO = "crypto"
    INDICES = "indices"
    BONDS = "bonds"


class SignalSource(str, Enum):
    NEWS = "news"
    MARKET_DATA = "market_data"
    SOCIAL = "social"
    CENTRAL_BANK = "central_bank"
    ECONOMIC_DATA = "economic_data"
    COT = "cot"
    FEAR_GREED = "fear_greed"


class EconomicRegime(str, Enum):
    """Macro regime classification for positioning context."""
    RISK_ON = "risk_on"              # Growth + easing → long risk assets
    RISK_OFF = "risk_off"            # Recession fear + tightening → long USD/gold/bonds
    REFLATION = "reflation"          # Growth + inflation → long commodities/EM
    STAGFLATION = "stagflation"      # Stagnation + inflation → long gold, short equities
    GOLDILOCKS = "goldilocks"        # Moderate growth + low inflation → long everything
    TRANSITION = "transition"        # Mixed signals, regime changing


class Signal(BaseModel):
    """A raw signal from any data source."""

    id: str = Field(default_factory=lambda: "")
    source: SignalSource
    title: str
    content: str
    url: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict = Field(default_factory=dict)


class AssetSentiment(BaseModel):
    """Directional sentiment for a specific asset within a narrative."""

    ticker: str          # e.g. "EUR/USD", "Gold", "BTC-USD", "S&P 500"
    asset_class: AssetClass
    direction: SentimentDirection
    conviction: float = 0.5   # 0-1, strength of directional view
    rationale: str = ""       # why this direction


class Narrative(BaseModel):
    """A macro narrative extracted from signals, with per-asset directional sentiment."""

    id: str = Field(default_factory=lambda: "")
    title: str
    summary: str
    asset_sentiments: list[AssetSentiment] = Field(default_factory=list)
    affected_asset_classes: list[AssetClass] = Field(default_factory=list)
    signals: list[Signal] = Field(default_factory=list)
    horizon: str = "1-4 weeks"   # expected timeframe for thesis to play out
    confidence: float = 0.5      # 0-1, overall narrative confidence
    trend: str = "stable"        # intensifying, stable, fading
    first_seen: datetime = Field(default_factory=datetime.utcnow)
    last_updated: datetime = Field(default_factory=datetime.utcnow)


class WeeklyAssetScore(BaseModel):
    """Aggregated weekly directional score for a single asset."""

    ticker: str
    asset_class: AssetClass
    direction: SentimentDirection
    score: float = 0.0           # -1 (max bearish) to +1 (max bullish)
    conviction: float = 0.0      # 0-1, average conviction across narratives
    narrative_count: int = 0     # how many narratives reference this asset
    top_narrative: str = ""      # title of highest-conviction narrative


class PriceValidation(BaseModel):
    """Comparison of predicted sentiment vs actual weekly return."""

    ticker: str
    asset_class: AssetClass
    predicted_direction: SentimentDirection
    predicted_score: float = 0.0
    actual_return_pct: float = 0.0
    actual_direction: SentimentDirection = SentimentDirection.NEUTRAL
    hit: bool = False            # did predicted direction match actual?


class WeeklyReport(BaseModel):
    """Complete weekly macro-pulse report."""

    id: str = Field(default_factory=lambda: "")
    week_start: datetime
    week_end: datetime
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    regime: EconomicRegime = EconomicRegime.TRANSITION
    regime_rationale: str = ""
    narratives: list[Narrative] = Field(default_factory=list)
    asset_scores: list[WeeklyAssetScore] = Field(default_factory=list)
    price_validations: list[PriceValidation] = Field(default_factory=list)
    signal_count: int = 0
    summary: str = ""            # AI-generated executive summary
