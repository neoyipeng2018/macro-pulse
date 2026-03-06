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
    REDDIT = "reddit"
    TWITTER = "twitter_crypto"
    YOUTUBE = "youtube_crypto"
    CENTRAL_BANK = "central_bank"
    ECONOMIC_DATA = "economic_data"
    COT = "cot"
    FEAR_GREED = "fear_greed"
    PREDICTION_MARKET = "prediction_market"
    GOOGLE_TRENDS = "google_trends"
    SPREADS = "spreads"
    FUNDING_RATES = "funding_rates"
    ONCHAIN = "onchain"
    OPTIONS = "options"
    DERIVATIVES_CONSENSUS = "derivatives_consensus"
    ETF_FLOWS = "etf_flows"
    MEMPOOL = "mempool"
    ETH_ONCHAIN = "eth_onchain"
    EXA_NEWS = "exa_news"


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
    """LEGACY — only used by run_pipeline_legacy(). Aggregated weekly directional score for a single asset."""

    ticker: str
    asset_class: AssetClass
    direction: SentimentDirection
    score: float = 0.0           # -1 (max bearish) to +1 (max bullish)
    conviction: float = 0.0      # 0-1, average conviction across narratives
    narrative_count: int = 0     # how many narratives reference this asset
    top_narrative: str = ""      # title of highest-conviction narrative


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
    """LEGACY — only used by run_pipeline_legacy(). Composite score: 50% narrative + 25% technical + 25% scenario + flat contrarian nudge.

    Clamped to [-1.0, +1.0].
    """

    ticker: str
    asset_class: AssetClass
    direction: SentimentDirection
    composite_score: float = 0.0       # -1.0 to +1.0 (clamped)
    confidence: float = 0.0            # deprecated, kept for backwards compat with stored reports
    narrative_score: float = 0.0       # raw narrative ±1.0 (50% weight)
    technical_score: float = 0.0       # technical bias ±1.0 (25% weight)
    scenario_score: float = 0.0        # probability-weighted scenario ±1.0 (25% weight)
    contrarian_bonus: float = 0.0      # flat nudge: +0.1 contrarian, -0.05 aligned
    narrative_count: int = 0
    top_narrative: str = ""
    conflict_flag: bool = False
    edge_type: str = "aligned"


class ConsensusScore(BaseModel):
    """Quantitative consensus measurement for an asset from market positioning data."""

    ticker: str                                    # "Bitcoin" or "Ethereum"
    consensus_score: float = 0.0                   # -1.0 to +1.0
    consensus_direction: str = "neutral"           # bullish / bearish / neutral (±0.15 threshold)
    components: dict[str, float] = Field(default_factory=dict)  # breakdown by source (each -1 to +1)
    options_skew: float = 0.0                      # raw 25-delta risk reversal
    funding_rate_7d: float = 0.0                   # 7-day accumulated funding %
    top_trader_ls_ratio: float = 0.0               # raw ratio
    etf_flow_5d: float = 0.0                       # USD millions, 5-day rolling
    put_call_ratio: float = 0.0                    # raw PCR
    max_pain_distance_pct: float = 0.0             # (current_price - max_pain) / current_price
    oi_change_7d_pct: float = 0.0                  # % OI change over 7 days
    data_timestamp: datetime = Field(default_factory=datetime.utcnow)


class DivergenceMetrics(BaseModel):
    """LEGACY — only used by run_pipeline_legacy(). Measures how non-consensus our view is for an asset."""

    ticker: str
    consensus_score: float = 0.0       # from ConsensusScore
    our_score: float = 0.0             # from composite scoring pipeline
    divergence: float = 0.0            # our_score - consensus_score
    abs_divergence: float = 0.0        # abs(divergence)
    divergence_label: str = "aligned"  # strongly_contrarian / contrarian / mildly_non_consensus / aligned
    consensus_direction: str = "neutral"
    our_direction: str = "neutral"


class TradeThesis(BaseModel):
    """Structured trade with entry/exit levels and risk/reward."""

    ticker: str
    direction: str                           # bullish / bearish
    entry_price: float = 0.0
    entry_date: datetime = Field(default_factory=datetime.utcnow)
    take_profit_pct: float = 0.0             # e.g., +6%
    stop_loss_pct: float = 0.0               # e.g., -3%
    risk_reward_ratio: float = 0.0           # computed: TP / SL
    max_holding_days: int = 7                # hard 1-week cap
    consensus_score_at_entry: float = 0.0
    our_score_at_entry: float = 0.0
    divergence_at_entry: float = 0.0
    divergence_label: str = "aligned"
    composite_score: float = 0.0
    rationale: str = ""
    # Outcome fields (filled later)
    exit_price: float | None = None
    exit_date: datetime | None = None
    exit_reason: str | None = None           # tp_hit / sl_hit / time_expired / invalidated
    pnl_pct: float | None = None
    days_held: int | None = None
    direction_correct: bool | None = None


class TradeOutcome(BaseModel):
    """Realized outcome for a trade thesis."""

    ticker: str
    week: str                                # week start date ISO string
    direction: str
    entry_price: float
    entry_date: datetime
    exit_price: float
    exit_date: datetime
    exit_reason: str                         # tp_hit / sl_hit / time_expired
    pnl_pct: float
    direction_correct: bool
    consensus_score: float = 0.0
    our_score: float = 0.0
    divergence: float = 0.0
    divergence_label: str = "aligned"
    days_held: int = 0


class ConsensusView(BaseModel):
    """Complete consensus picture for an asset: positioning + narrative."""

    ticker: str
    asset_class: AssetClass
    quant_score: float = 0.0
    quant_direction: str = "neutral"
    quant_components: dict[str, float] = Field(default_factory=dict)
    positioning_consensus: str = ""
    positioning_summary: str = ""
    narrative_consensus: str = ""
    market_narrative: str = ""
    consensus_coherence: str = "aligned"
    coherence_detail: str = ""
    key_levels: list[str] = Field(default_factory=list)
    priced_in: list[str] = Field(default_factory=list)
    not_priced_in: list[str] = Field(default_factory=list)
    consensus_direction: SentimentDirection = SentimentDirection.NEUTRAL
    consensus_confidence: float = 0.0
    one_week_range: dict[str, float] = Field(default_factory=dict)
    last_updated: datetime = Field(default_factory=datetime.utcnow)


class EvidenceSource(BaseModel):
    """A single piece of evidence supporting a non-consensus view."""

    signal_id: str
    source: str
    summary: str
    strength: float = 0.5


class NonConsensusView(BaseModel):
    """A specific disagreement with market consensus, with evidence."""

    ticker: str
    asset_class: AssetClass
    consensus_direction: SentimentDirection
    consensus_narrative: str = ""
    our_direction: SentimentDirection
    our_conviction: float = 0.0
    thesis: str = ""
    edge_type: str = "contrarian"
    evidence: list[EvidenceSource] = Field(default_factory=list)
    independent_source_count: int = 0
    has_testable_mechanism: bool = False
    has_timing_edge: bool = False
    has_catalyst: str = ""
    invalidation: str = ""
    validity_score: float = 0.0  # LEGACY: kept for DB compat, no longer used for display
    signal_ids: list[str] = Field(default_factory=list)
    supporting_mechanisms: list[str] = Field(default_factory=list)
    mechanism_stage: str = ""
    regime_context: str = ""
    consensus_quant_score: float = 0.0
    consensus_coherence: str = ""
    # New binary validation fields
    validation_multi_source: bool = False
    validation_causal: bool = False
    validation_sources: list[str] = Field(default_factory=list)
    validation_mechanism_id: str | None = None
    validation_mechanism_stage: str | None = None
    evidence_urls: list[dict] = Field(default_factory=list)
    one_week_nc_range: dict[str, float] = Field(default_factory=dict)


class WeeklyReport(BaseModel):
    """Complete weekly macro-pulse report."""

    id: str = Field(default_factory=lambda: "")
    week_start: datetime
    week_end: datetime
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    regime: EconomicRegime = EconomicRegime.TRANSITION
    regime_rationale: str = ""
    signal_count: int = 0
    summary: str = ""
    # Phase 1: Consensus
    consensus_scores: list[ConsensusScore] = Field(default_factory=list)
    consensus_views: list[ConsensusView] = Field(default_factory=list)
    regime_votes: list[dict] = Field(default_factory=list)
    direction_calls: list[dict] = Field(default_factory=list)
    # Phase 2: Non-Consensus + Mechanisms
    non_consensus_views: list[NonConsensusView] = Field(default_factory=list)
    active_scenarios: list[ActiveScenario] = Field(default_factory=list)
    # LEGACY — kept for loading old reports from DB
    narratives: list[Narrative] = Field(default_factory=list)
    asset_scores: list[WeeklyAssetScore] = Field(default_factory=list)
    scenario_views: list[ScenarioAssetView] = Field(default_factory=list)
    composite_scores: list[CompositeAssetScore] = Field(default_factory=list)
    divergence_metrics: list[DivergenceMetrics] = Field(default_factory=list)
    trade_theses: list[TradeThesis] = Field(default_factory=list)
