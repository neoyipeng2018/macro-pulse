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
    PREDICTION_MARKET = "prediction_market"
    GOOGLE_TRENDS = "google_trends"
    SPREADS = "spreads"
    FUNDING_RATES = "funding_rates"
    ONCHAIN = "onchain"


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
    # Per-asset consensus vs. edge (what does the market think about THIS asset?)
    consensus_view: str = ""
    edge_type: str = "aligned"       # contrarian|more_aggressive|more_passive|aligned
    edge_rationale: str = ""
    catalyst: str = ""               # specific event/trigger creating the opportunity
    exit_condition: str = ""         # how to know when price discovery is done


class EdgeType(str, Enum):
    """How our signal differs from market consensus."""
    CONTRARIAN = "contrarian"          # opposite direction to consensus
    MORE_AGGRESSIVE = "more_aggressive"  # same direction but stronger conviction
    MORE_PASSIVE = "more_passive"        # same direction but weaker conviction
    ALIGNED = "aligned"                  # in line with consensus (no edge)


class Narrative(BaseModel):
    """A macro narrative extracted from signals, with per-asset directional sentiment."""

    id: str = Field(default_factory=lambda: "")
    title: str
    summary: str
    asset_sentiments: list[AssetSentiment] = Field(default_factory=list)
    affected_asset_classes: list[AssetClass] = Field(default_factory=list)
    signals: list[Signal] = Field(default_factory=list)
    horizon: str = "1 week"   # expected timeframe for thesis to play out
    confidence: float = 0.5      # 0-1, overall narrative confidence
    trend: str = "stable"        # intensifying, stable, fading
    # Consensus vs. edge analysis
    consensus_view: str = ""     # what the market/analysts consensus thinks
    consensus_sources: list[str] = Field(default_factory=list)  # citations for verification
    edge_type: EdgeType = EdgeType.ALIGNED  # how our signal differs from consensus
    edge_rationale: str = ""     # why we think consensus is wrong or incomplete
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


class ChainStep(BaseModel):
    """A single step in a macro transmission mechanism's causal chain."""

    description: str
    observable: str
    lag_days: list[int] = Field(default_factory=lambda: [0, 5])  # [min, max] days


class MechanismAssetImpact(BaseModel):
    """Expected asset impact from a transmission mechanism."""

    ticker: str
    asset_class: AssetClass
    direction: SentimentDirection
    sensitivity: str = "medium"     # low/medium/high
    lag_days: list[int] = Field(default_factory=lambda: [0, 7])


class TransmissionMechanism(BaseModel):
    """A known macro causal chain from the mechanism catalog."""

    id: str                         # e.g. "fed_dovish_pivot"
    name: str
    category: str                   # monetary_policy, risk_sentiment, etc.
    description: str
    trigger_sources: list[str] = Field(default_factory=list)  # SignalSource values
    trigger_keywords: list[str] = Field(default_factory=list)
    chain_steps: list[ChainStep] = Field(default_factory=list)
    asset_impacts: list[MechanismAssetImpact] = Field(default_factory=list)
    confirmation_criteria: list[str] = Field(default_factory=list)
    invalidation_criteria: list[str] = Field(default_factory=list)


class ChainStepProgress(BaseModel):
    """Progress status for a single step in an active scenario's chain."""

    step_index: int
    description: str
    status: str = "not_started"     # not_started/emerging/confirmed/invalidated
    evidence: str = ""
    confidence: float = 0.0


class ScenarioAssetImpact(BaseModel):
    """Asset impact within an active scenario."""

    ticker: str
    asset_class: AssetClass
    direction: SentimentDirection
    magnitude: float = 0.5          # 0-1
    conviction: float = 0.5
    rationale: str = ""


class ActiveScenario(BaseModel):
    """A transmission mechanism activated by current signals."""

    id: str = ""
    mechanism_id: str
    mechanism_name: str
    category: str
    probability: float = 0.5
    trigger_signals: list[str] = Field(default_factory=list)
    trigger_evidence: str = ""
    chain_progress: list[ChainStepProgress] = Field(default_factory=list)
    current_stage: str = "early"    # early/mid/late/complete
    expected_magnitude: str = "moderate"  # minor/moderate/major
    asset_impacts: list[ScenarioAssetImpact] = Field(default_factory=list)
    watch_items: list[str] = Field(default_factory=list)
    confirmation_status: str = ""
    invalidation_risk: str = ""
    horizon: str = "1 week"
    confidence: float = 0.5


class AssetScenarioEntry(BaseModel):
    """A single scenario's contribution to an asset's outlook."""

    mechanism_id: str
    mechanism_name: str
    category: str
    probability: float
    direction: SentimentDirection
    magnitude: float
    conviction: float
    rationale: str = ""
    trigger_evidence: str = ""
    chain_stage: str = "early"
    chain_progress: list[ChainStepProgress] = Field(default_factory=list)
    watch_items: list[str] = Field(default_factory=list)


class ScenarioAssetView(BaseModel):
    """Aggregated scenario-based outlook for a single asset."""

    ticker: str
    asset_class: AssetClass
    scenarios: list[AssetScenarioEntry] = Field(default_factory=list)
    net_direction: SentimentDirection = SentimentDirection.NEUTRAL
    net_score: float = 0.0
    avg_probability: float = 0.0
    dominant_scenario: str = ""
    scenario_count: int = 0
    conflict_flag: bool = False     # True if scenarios disagree on direction


class CompositeAssetScore(BaseModel):
    """Composite score combining narrative, technical, scenario, and contrarian inputs."""

    ticker: str
    asset_class: AssetClass
    direction: SentimentDirection
    composite_score: float = 0.0       # -1.5 to +1.5 (contrarian bonus extends range)
    confidence: float = 0.0            # 0-1
    narrative_score: float = 0.0       # raw narrative ±1.0
    technical_score: float = 0.0       # technical bias ±1.0
    scenario_score: float = 0.0        # probability-weighted scenario ±1.0
    contrarian_bonus: float = 0.0      # +0.3 contrarian, -0.1 aligned
    narrative_count: int = 0
    top_narrative: str = ""
    conflict_flag: bool = False
    edge_type: str = "aligned"


class TradeParams(BaseModel):
    """Structured trade parameters parsed from LLM exit conditions."""

    ticker: str
    direction: str = "long"             # "long" or "short"
    entry_price: float = 0.0            # current market price at signal time
    stop_loss_pct: float = -5.0         # e.g., -5.0
    take_profit_pct: float = 8.0        # e.g., +8.0
    intermediate_tp_pct: float | None = None  # e.g., +4.0 (partial exit)
    risk_reward: float = 1.6            # e.g., 1.6
    invalidation_triggers: list[str] = Field(default_factory=list)
    horizon_days: int = 7


class Trade(BaseModel):
    """A fully specified actionable trade with sizing and risk parameters."""

    id: str = Field(default_factory=lambda: "")
    report_id: str = ""
    ticker: str
    direction: str = "LONG"             # LONG / SHORT
    composite_score: float = 0.0
    narrative_score: float = 0.0      # component: narrative sentiment ±1.0
    technical_score: float = 0.0      # component: technical bias ±1.0
    scenario_score: float = 0.0       # component: probability-weighted scenario ±1.0
    contrarian_bonus: float = 0.0     # component: +0.3 contrarian, -0.1 aligned
    calibration_mult: float = 1.0     # calibration multiplier applied
    entry_price: float = 0.0
    position_usd: float = 0.0
    position_size: float = 0.0          # in asset units (e.g., 0.029 BTC)
    portfolio_pct: float = 0.0          # % of capital
    stop_loss_price: float = 0.0
    take_profit_price: float = 0.0
    intermediate_tp_price: float | None = None
    risk_reward: float = 0.0
    risk_usd: float = 0.0              # max loss in USD
    reward_usd: float = 0.0            # max gain in USD
    horizon_days: int = 7
    confidence: float = 0.0
    top_narrative: str = ""
    invalidation_triggers: list[str] = Field(default_factory=list)
    conflict_flag: bool = False
    regime: str = ""
    status: str = "proposed"            # proposed/open/partial_tp/closed/stopped/expired
    exit_price: float | None = None
    exit_time: datetime | None = None
    exit_reason: str | None = None      # tp_hit/stop_hit/manual/expired/invalidated
    pnl_usd: float | None = None
    pnl_pct: float | None = None
    notes: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PortfolioSnapshot(BaseModel):
    """Point-in-time snapshot of portfolio state."""

    id: str = Field(default_factory=lambda: "")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    total_capital: float = 0.0
    deployed_capital: float = 0.0
    open_positions: int = 0
    unrealized_pnl: float = 0.0
    realized_pnl_cumulative: float = 0.0


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
    active_scenarios: list[ActiveScenario] = Field(default_factory=list)
    scenario_views: list[ScenarioAssetView] = Field(default_factory=list)
    composite_scores: list[CompositeAssetScore] = Field(default_factory=list)
    trades: list[Trade] = Field(default_factory=list)
