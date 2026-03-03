"""Actionable single-page view — what assets will do well, for how long, and why."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

import streamlit as st

from analysis.technicals import TechnicalSnapshot, compute_technicals
from config.settings import settings
from models.schemas import (
    AssetClass,
    AssetScenarioEntry,
    ConsensusScore,
    DivergenceMetrics,
    EdgeType,
    Narrative,
    ScenarioAssetView,
    SentimentDirection,
    SignalSource,
    TradeThesis,
    WeeklyAssetScore,
    WeeklyReport,
)

ASSET_LABELS = {
    AssetClass.FX: "FX",
    AssetClass.METALS: "Metals",
    AssetClass.ENERGY: "Energy",
    AssetClass.CRYPTO: "Crypto",
    AssetClass.INDICES: "Indices",
    AssetClass.BONDS: "Bonds",
}

SOURCE_LABELS = {
    SignalSource.NEWS: "News",
    SignalSource.MARKET_DATA: "Market Data",
    SignalSource.SOCIAL: "Social",
    SignalSource.CENTRAL_BANK: "Central Bank",
    SignalSource.ECONOMIC_DATA: "Econ Data",
    SignalSource.COT: "COT",
    SignalSource.FEAR_GREED: "Fear/Greed",
    SignalSource.PREDICTION_MARKET: "Predictions",
    SignalSource.GOOGLE_TRENDS: "Trends",
    SignalSource.SPREADS: "Spreads",
    SignalSource.FUNDING_RATES: "Funding",
    SignalSource.ONCHAIN: "On-Chain",
}


EDGE_LABELS = {
    EdgeType.CONTRARIAN: "CONTRARIAN",
    EdgeType.MORE_AGGRESSIVE: "MORE AGGRESSIVE",
    EdgeType.MORE_PASSIVE: "MORE PASSIVE",
    EdgeType.ALIGNED: "ALIGNED",
}


@dataclass
class SourceSignalDetail:
    """A single source signal's displayable info."""

    title: str
    url: str
    snippet: str


@dataclass
class NarrativeContext:
    """A single narrative's contribution to an asset's view."""

    narrative_title: str
    confidence: float
    horizon: str
    trend: str
    rationale: str
    signal_sources: list[str] = field(default_factory=list)
    consensus_view: str = ""
    edge_type: EdgeType = EdgeType.ALIGNED
    edge_rationale: str = ""
    consensus_sources: list[str] = field(default_factory=list)


@dataclass
class AssetIntel:
    """Enriched per-asset intelligence combining score + narrative context."""

    ticker: str
    asset_class: AssetClass
    direction: SentimentDirection
    score: float
    conviction: float
    narrative_count: int
    horizon: str  # from highest-confidence matching narrative
    trend: str  # majority vote across narratives
    primary_rationale: str  # from highest-confidence matching narrative
    source_narrative: str  # title of that narrative
    signal_sources: list[str] = field(default_factory=list)  # e.g. ["News", "Central Bank"]
    extra_narratives: list[NarrativeContext] = field(default_factory=list)
    # Consensus vs. edge from primary narrative
    consensus_view: str = ""
    consensus_sources: list[str] = field(default_factory=list)
    edge_type: EdgeType = EdgeType.ALIGNED
    edge_rationale: str = ""
    # Catalyst and exit condition from primary narrative
    catalyst: str = ""
    exit_condition: str = ""
    # Grouped source signals with links and snippets
    source_details: dict[str, list[SourceSignalDetail]] = field(default_factory=dict)
    # Composite score fields
    composite_score: float = 0.0
    narrative_score: float = 0.0
    technical_score: float = 0.0
    scenario_score: float = 0.0
    contrarian_bonus: float = 0.0


def build_asset_intel(report: WeeklyReport) -> list[AssetIntel]:
    """Link WeeklyAssetScore back to Narrative data to enrich each asset."""

    # Build composite_by_ticker lookup from report.composite_scores
    composite_by_ticker: dict[str, object] = {}
    for cs in getattr(report, "composite_scores", None) or []:
        composite_by_ticker[cs.ticker] = cs

    # Index narratives by ticker → list of (narrative, asset_sentiment)
    ticker_narratives: dict[str, list[tuple[Narrative, object]]] = {}
    for narrative in report.narratives:
        for asent in narrative.asset_sentiments:
            ticker_narratives.setdefault(asent.ticker, []).append(
                (narrative, asent)
            )

    results: list[AssetIntel] = []
    for score in report.asset_scores:
        entries = ticker_narratives.get(score.ticker, [])

        # Sort by narrative confidence descending to find the primary one
        entries.sort(key=lambda x: x[0].confidence, reverse=True)

        if entries:
            primary_narr, primary_asent = entries[0]
            horizon = primary_narr.horizon
            primary_rationale = primary_asent.rationale or primary_narr.summary
            source_narrative = primary_narr.title

            # Majority vote for trend
            trend_counts = Counter(n.trend for n, _ in entries)
            trend = trend_counts.most_common(1)[0][0]

            # Collect unique signal sources + details across all narratives
            all_sources: set[str] = set()
            source_details: dict[str, list[SourceSignalDetail]] = {}
            seen_signal_ids: set[str] = set()
            for narr, _ in entries:
                for sig in narr.signals:
                    label = SOURCE_LABELS.get(sig.source, sig.source.value)
                    all_sources.add(label)
                    # Deduplicate signals by id
                    if sig.id and sig.id in seen_signal_ids:
                        continue
                    if sig.id:
                        seen_signal_ids.add(sig.id)
                    snippet = (sig.content[:200] + "…") if len(sig.content) > 200 else sig.content
                    source_details.setdefault(label, []).append(
                        SourceSignalDetail(title=sig.title, url=sig.url, snippet=snippet)
                    )
            signal_sources = sorted(all_sources)

            # Catalyst & exit condition from primary asset sentiment
            catalyst = getattr(primary_asent, "catalyst", "") or ""
            exit_condition = getattr(primary_asent, "exit_condition", "") or ""

            # Consensus & edge from primary asset sentiment (per-asset),
            # falling back to narrative-level for older data
            consensus_view = primary_asent.consensus_view or primary_narr.consensus_view
            consensus_sources = primary_narr.consensus_sources
            try:
                edge_type = EdgeType(primary_asent.edge_type) if primary_asent.edge_type else primary_narr.edge_type
            except ValueError:
                edge_type = primary_narr.edge_type
            edge_rationale = primary_asent.edge_rationale or primary_narr.edge_rationale

            # Build extra narratives (skip the primary)
            extra = []
            for narr, asent in entries[1:]:
                narr_sources = sorted({
                    SOURCE_LABELS.get(s.source, s.source.value)
                    for s in narr.signals
                })
                # Prefer per-asset consensus, fall back to narrative-level
                try:
                    extra_edge = EdgeType(asent.edge_type) if asent.edge_type else narr.edge_type
                except ValueError:
                    extra_edge = narr.edge_type
                extra.append(
                    NarrativeContext(
                        narrative_title=narr.title,
                        confidence=narr.confidence,
                        horizon=narr.horizon,
                        trend=narr.trend,
                        rationale=asent.rationale or narr.summary,
                        signal_sources=narr_sources,
                        consensus_view=asent.consensus_view or narr.consensus_view,
                        edge_type=extra_edge,
                        edge_rationale=asent.edge_rationale or narr.edge_rationale,
                        consensus_sources=narr.consensus_sources,
                    )
                )
        else:
            horizon = "—"
            trend = "stable"
            primary_rationale = ""
            source_narrative = score.top_narrative
            signal_sources = []
            source_details = {}
            extra = []
            consensus_view = ""
            consensus_sources = []
            edge_type = EdgeType.ALIGNED
            edge_rationale = ""

        # Look up composite score for this ticker
        comp = composite_by_ticker.get(score.ticker)

        results.append(
            AssetIntel(
                ticker=score.ticker,
                asset_class=score.asset_class,
                direction=score.direction,
                score=score.score,
                conviction=score.conviction,
                narrative_count=score.narrative_count,
                horizon=horizon,
                trend=trend,
                primary_rationale=primary_rationale,
                source_narrative=source_narrative,
                signal_sources=signal_sources,
                extra_narratives=extra,
                consensus_view=consensus_view,
                consensus_sources=consensus_sources,
                edge_type=edge_type,
                edge_rationale=edge_rationale,
                catalyst=catalyst,
                exit_condition=exit_condition,
                source_details=source_details,
                composite_score=comp.composite_score if comp else 0.0,
                narrative_score=comp.narrative_score if comp else 0.0,
                technical_score=comp.technical_score if comp else 0.0,
                scenario_score=comp.scenario_score if comp else 0.0,
                contrarian_bonus=comp.contrarian_bonus if comp else 0.0,
            )
        )

    return results


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _render_regime_banner(report: WeeklyReport) -> None:
    """Compact regime badge + rationale + executive summary."""
    regime_val = report.regime.value.replace("_", " ").upper()
    regime_class = report.regime.value
    rationale = report.regime_rationale or ""
    summary = report.summary or ""

    # Combine rationale and summary — keep it compact
    detail = rationale
    if summary and summary != rationale:
        detail = f"{rationale}  ·  {summary}" if rationale else summary

    st.markdown(
        f'<div class="regime-banner">'
        f'<span class="regime-badge regime-{regime_class}">{regime_val}</span>'
        f'<span class="regime-summary">{detail}</span>'
        f"</div>",
        unsafe_allow_html=True,
    )


def _conviction_bar_html(conviction: float, direction: SentimentDirection) -> str:
    pct = int(conviction * 100)
    dir_class = direction.value
    return (
        f'<span class="conviction-bar-bg">'
        f'<span class="conviction-bar-fill conviction-bar-fill-{dir_class}" '
        f'style="width:{pct}%"></span></span>'
        f'<span class="conviction-label">{conviction:.0%}</span>'
    )


def _extra_narratives_html(extra: list[NarrativeContext]) -> str:
    """Build HTML <details> block for additional narratives."""
    count = len(extra)
    label = f"{count} more narrative{'s' if count != 1 else ''}"
    items = ""
    for ctx in extra:
        trend_cls = f"trend-{ctx.trend}"
        ctx_chips = "".join(
            f'<span class="source-chip">{src}</span>' for src in ctx.signal_sources
        )
        items += (
            f'<div style="margin-bottom:8px;">'
            f'<span style="color:#e0e4ec;font-size:0.8rem;font-weight:600;">'
            f"{ctx.narrative_title}</span> "
            f'<span class="horizon-chip">{ctx.horizon}</span> '
            f'<span class="trend-chip {trend_cls}">{ctx.trend}</span> '
            f'<span style="color:#4a5568;font-size:0.65rem;">'
            f"conf {ctx.confidence:.0%}</span> "
            f"{ctx_chips}"
            f'<div class="rationale-text">{ctx.rationale}</div>'
            f"</div>"
        )
    return (
        f'<details class="extra-narratives">'
        f"<summary>{label}</summary>"
        f'<div style="padding-top:8px;">{items}</div>'
        f"</details>"
    )


def _consensus_edge_html(intel: AssetIntel) -> str:
    """Build the consensus vs. edge section for an asset card."""
    if not intel.consensus_view:
        return ""

    edge_label = EDGE_LABELS.get(intel.edge_type, "ALIGNED")
    edge_css_class = f"edge-{intel.edge_type.value}"

    # Consensus sources as citation chips
    citation_chips = ""
    for src in intel.consensus_sources:
        citation_chips += f'<span class="citation-chip">{src}</span> '

    edge_section = (
        f'<div class="consensus-edge-block">'
        # Edge badge
        f'<div class="edge-header">'
        f'<span class="edge-badge {edge_css_class}">{edge_label}</span>'
        f'<span class="edge-label">vs consensus</span>'
        f'</div>'
        # Consensus view
        f'<div class="consensus-row">'
        f'<span class="consensus-label">CONSENSUS:</span>'
        f'<span class="consensus-text">{intel.consensus_view}</span>'
        f'</div>'
    )

    # Citations
    if citation_chips:
        edge_section += (
            f'<div class="consensus-citations">{citation_chips}</div>'
        )

    # Edge rationale (our differentiated view)
    if intel.edge_rationale:
        edge_section += (
            f'<div class="consensus-row">'
            f'<span class="edge-diff-label">OUR EDGE:</span>'
            f'<span class="edge-diff-text">{intel.edge_rationale}</span>'
            f'</div>'
        )

    edge_section += '</div>'
    return edge_section


def _catalyst_exit_html(intel: AssetIntel) -> str:
    """Build the catalyst + exit condition section for an asset card."""
    if not intel.catalyst and not intel.exit_condition:
        return ""

    rows = ""
    if intel.catalyst:
        rows += (
            f'<div class="catalyst-row">'
            f'<span class="catalyst-label">CATALYST:</span>'
            f'<span class="catalyst-text">{intel.catalyst}</span>'
            f'</div>'
        )
    if intel.exit_condition:
        rows += (
            f'<div class="catalyst-row">'
            f'<span class="exit-label">EXIT WHEN:</span>'
            f'<span class="exit-text">{intel.exit_condition}</span>'
            f'</div>'
        )

    return f'<div class="catalyst-exit-block">{rows}</div>'


def _source_details_html(source_details: dict[str, list[SourceSignalDetail]]) -> str:
    """Build collapsed <details> sections per source type with links and snippets."""
    if not source_details:
        return ""

    sections = ""
    for label in sorted(source_details):
        signals = source_details[label]
        count = len(signals)
        items_html = ""
        for sig in signals:
            title_html = sig.title
            if sig.url:
                title_html = (
                    f'<a href="{sig.url}" target="_blank" rel="noopener" '
                    f'class="source-detail-link">{sig.title}</a>'
                )
            snippet_html = ""
            if sig.snippet:
                snippet_html = f'<div class="source-detail-snippet">{sig.snippet}</div>'
            items_html += (
                f'<div class="source-detail-item">'
                f'<div class="source-detail-title">{title_html}</div>'
                f'{snippet_html}'
                f'</div>'
            )
        sections += (
            f'<details class="source-detail-group">'
            f'<summary><span class="source-chip">{label}</span>'
            f'<span class="source-detail-count">{count} signal{"s" if count != 1 else ""}</span>'
            f'</summary>'
            f'<div class="source-detail-list">{items_html}</div>'
            f'</details>'
        )

    return f'<div class="source-details-container">{sections}</div>'


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_technicals(tickers: tuple[str, ...]) -> dict[str, TechnicalSnapshot]:
    """Cached wrapper — tuple arg required for Streamlit hashing."""
    return compute_technicals(list(tickers))


def _technicals_html(
    snapshot: TechnicalSnapshot, direction: SentimentDirection
) -> str:
    """Build a collapsible technicals section for an asset card."""
    # Alignment badge
    macro_dir = direction.value  # "bullish" / "bearish" / "neutral"
    if snapshot.agrees_with and snapshot.agrees_with == macro_dir:
        badge = '<span class="tech-agree-badge">ALIGNED</span>'
    elif snapshot.agrees_with and snapshot.agrees_with != macro_dir and macro_dir != "neutral":
        badge = '<span class="tech-diverge-badge">DIVERGENT</span>'
    else:
        badge = ""

    # RSI signal color
    if snapshot.rsi_label == "Overbought":
        rsi_cls = "tech-signal-bearish"
    elif snapshot.rsi_label == "Oversold":
        rsi_cls = "tech-signal-bullish"
    else:
        rsi_cls = "tech-signal-neutral"

    # MACD signal color
    macd_cls = "tech-signal-bullish" if snapshot.macd_histogram > 0 else "tech-signal-bearish"

    # SMA signal color
    if snapshot.sma_20_dist_pct > 0:
        sma_cls = "tech-signal-bullish"
    elif snapshot.sma_20_dist_pct < 0:
        sma_cls = "tech-signal-bearish"
    else:
        sma_cls = "tech-signal-neutral"

    # MACD display value
    macd_arrow = "&#9650;" if snapshot.macd_histogram > 0 else "&#9660;"

    return (
        f'<details class="technicals-section">'
        f"<summary>Technicals {badge}</summary>"
        f'<div class="tech-body">'
        # RSI row
        f'<div class="tech-row">'
        f'<span class="tech-label">RSI(14)</span>'
        f'<span class="tech-value">{snapshot.rsi:.1f}</span>'
        f'<span class="tech-signal {rsi_cls}">{snapshot.rsi_label}</span>'
        f"</div>"
        # MACD row
        f'<div class="tech-row">'
        f'<span class="tech-label">MACD</span>'
        f'<span class="tech-value">{macd_arrow}</span>'
        f'<span class="tech-signal {macd_cls}">{snapshot.macd_label}</span>'
        f"</div>"
        # SMA row
        f'<div class="tech-row">'
        f'<span class="tech-label">20d SMA</span>'
        f'<span class="tech-value">{snapshot.sma_20_dist_pct:+.1f}%</span>'
        f'<span class="tech-signal {sma_cls}">{snapshot.sma_20_label}</span>'
        f"</div>"
        f"</div>"
        f"</details>"
    )


def _render_asset_card(intel: AssetIntel, tech_snapshot: TechnicalSnapshot | None = None) -> None:
    """Render a single asset intel card."""
    dir_val = intel.direction.value
    # Use composite_score as primary display; fall back to narrative-only score
    primary_score = intel.composite_score if intel.composite_score != 0.0 else intel.score
    score_sign = "+" if primary_score > 0 else ""
    score_class = f"score-{dir_val}"
    trend_class = f"trend-{intel.trend}"
    ac_label = ASSET_LABELS.get(intel.asset_class, intel.asset_class.value)

    extra_html = ""
    if intel.extra_narratives:
        extra_html = _extra_narratives_html(intel.extra_narratives)

    source_chips = "".join(
        f'<span class="source-chip">{src}</span>' for src in intel.signal_sources
    )

    catalyst_exit_html = _catalyst_exit_html(intel)
    technicals_html = _technicals_html(tech_snapshot, intel.direction) if tech_snapshot else ""
    consensus_html = _consensus_edge_html(intel)
    source_details_html = _source_details_html(intel.source_details)

    # Component breakdown row (only shown when composite data exists)
    composite_breakdown_html = ""
    if intel.composite_score != 0.0:
        composite_breakdown_html = (
            f'<div class="composite-breakdown">'
            f'<span class="comp-label">NAR</span><span class="comp-val">{intel.narrative_score:+.2f}</span>'
            f'<span class="comp-sep">\u00b7</span>'
            f'<span class="comp-label">TECH</span><span class="comp-val">{intel.technical_score:+.2f}</span>'
            f'<span class="comp-sep">\u00b7</span>'
            f'<span class="comp-label">SCEN</span><span class="comp-val">{intel.scenario_score:+.2f}</span>'
            f'<span class="comp-sep">\u00b7</span>'
            f'<span class="comp-label">EDGE</span><span class="comp-val">{intel.contrarian_bonus:+.2f}</span>'
            f"</div>"
        )

    card_html = (
        f'<div class="asset-card asset-card-{dir_val}">'
        # Header row
        f'<div class="asset-card-header">'
        f'<span class="asset-ticker">{_get_ticker_name(intel.ticker)}</span>'
        f'<span class="asset-class-label">{ac_label}</span>'
        f'<span class="badge badge-{dir_val}">{dir_val}</span>'
        f'<span class="{score_class} score-value">{score_sign}{primary_score:.2f}</span>'
        f'{_conviction_bar_html(intel.conviction, intel.direction)}'
        f'<span class="horizon-chip">{intel.horizon}</span>'
        f'<span class="trend-chip {trend_class}">{intel.trend}</span>'
        f"</div>"
        # Composite score breakdown
        f"{composite_breakdown_html}"
        # Rationale
        f'<div class="rationale-text">{intel.primary_rationale}</div>'
        # Catalyst & exit condition
        f"{catalyst_exit_html}"
        # Technical indicators (collapsed)
        f"{technicals_html}"
        # Consensus vs. edge
        f"{consensus_html}"
        # Source + source chips
        f'<div class="source-narrative">via {intel.source_narrative}'
        f" · {intel.narrative_count} narrative{'s' if intel.narrative_count != 1 else ''}"
        f" · {source_chips}"
        f"</div>"
        # Collapsed source details with links and snippets
        f"{source_details_html}"
        # Extra narratives (inline HTML details/summary)
        f"{extra_html}"
        f"</div>"
    )
    st.markdown(card_html, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Scenario-based rendering
# ---------------------------------------------------------------------------

@dataclass
class ScenarioAssetIntel:
    """Enriched per-asset data for scenario-based rendering."""

    ticker: str
    asset_class: AssetClass
    net_direction: SentimentDirection
    net_score: float
    avg_probability: float = 0.0
    scenarios: list[AssetScenarioEntry] = field(default_factory=list)
    conflict_flag: bool = False
    scenario_count: int = 0
    dominant_scenario: str = ""
    consensus_view: str = ""
    consensus_sources: list[str] = field(default_factory=list)
    edge_type: EdgeType = EdgeType.ALIGNED
    edge_rationale: str = ""
    catalyst: str = ""
    exit_condition: str = ""
    source_details: dict[str, list[SourceSignalDetail]] = field(default_factory=dict)
    # Composite score fields
    composite_score: float = 0.0
    narrative_score: float = 0.0
    technical_score: float = 0.0
    scenario_score: float = 0.0
    contrarian_bonus: float = 0.0


# Known financial source names to extract from consensus_view text
_SOURCE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Goldman Sachs", re.compile(r"Goldman\s*Sachs|Goldman", re.I)),
    ("JPMorgan", re.compile(r"JPMorgan|JP\s*Morgan|JPM", re.I)),
    ("Morgan Stanley", re.compile(r"Morgan\s*Stanley", re.I)),
    ("CME FedWatch", re.compile(r"CME\s*FedWatch|FedWatch", re.I)),
    ("Bloomberg", re.compile(r"Bloomberg", re.I)),
    ("Reuters", re.compile(r"Reuters", re.I)),
    ("Citi", re.compile(r"\bCiti\b|Citigroup", re.I)),
    ("BofA", re.compile(r"BofA|Bank\s*of\s*America", re.I)),
    ("UBS", re.compile(r"\bUBS\b", re.I)),
    ("Deutsche Bank", re.compile(r"Deutsche\s*Bank", re.I)),
    ("Barclays", re.compile(r"Barclays", re.I)),
    ("HSBC", re.compile(r"\bHSBC\b", re.I)),
    ("Nomura", re.compile(r"Nomura", re.I)),
    ("ING", re.compile(r"\bING\b", re.I)),
    ("Wells Fargo", re.compile(r"Wells\s*Fargo", re.I)),
    ("Options Market", re.compile(r"options\s*market", re.I)),
    ("Futures Market", re.compile(r"futures\s*(market|pricing)", re.I)),
    ("Sell-side", re.compile(r"sell[\-\u2010\u2011\u2012\u2013 ]side", re.I)),
    ("Market Pricing", re.compile(r"market\s+(?:expects?|pricing|prices?|forecast)", re.I)),
    ("Consensus", re.compile(r"\bconsensus\b", re.I)),
    ("Analysts", re.compile(r"\banalysts?\b", re.I)),
]


def _extract_sources(text: str) -> list[str]:
    """Extract financial source citations from consensus_view text."""
    if not text:
        return []
    return [name for name, pattern in _SOURCE_PATTERNS if pattern.search(text)]


def _build_name_to_ticker_map() -> dict[str, str]:
    """Build a mapping from human-readable asset names to Yahoo Finance tickers.

    Uses assets.yaml config. Keys are lowercased for case-insensitive matching.
    Also maps common LLM-generated name variants.
    """
    name_to_ticker: dict[str, str] = {}
    for _class, items in settings.assets.items():
        for item in items:
            ticker = item["ticker"]
            name = item["name"]
            name_to_ticker[name.lower()] = ticker
            # Also map the ticker itself (identity)
            name_to_ticker[ticker.lower()] = ticker
    # Common LLM-generated aliases that differ from assets.yaml names
    _aliases = {
        "wti crude": "CL=F",
        "wti": "CL=F",
        "brent crude": "BZ=F",
        "brent": "BZ=F",
        "dxy": "DX-Y.NYB",
        "us dollar index": "DX-Y.NYB",
        "dollar index": "DX-Y.NYB",
        "us 10y yield": "^TNX",
        "us 10y": "^TNX",
        "10y yield": "^TNX",
        "us 30y yield": "^TYX",
        "us 30y": "^TYX",
        "30y yield": "^TYX",
        "us 5y yield": "^FVX",
        "us 5y": "^FVX",
        "5y yield": "^FVX",
        "s&p 500": "^GSPC",
        "s&p500": "^GSPC",
        "spx": "^GSPC",
        "nasdaq": "^IXIC",
        "dow jones": "^DJI",
        "dow": "^DJI",
        "russell 2000": "^RUT",
        "vix": "^VIX",
        "ftse 100": "^FTSE",
        "ftse": "^FTSE",
        "nikkei 225": "^N225",
        "nikkei": "^N225",
        "hang seng": "^HSI",
        "eur/usd": "EURUSD=X",
        "gbp/usd": "GBPUSD=X",
        "usd/jpy": "USDJPY=X",
        "aud/usd": "AUDUSD=X",
        "usd/cad": "USDCAD=X",
        "usd/chf": "USDCHF=X",
        "usd/cnh": "USDCNH=X",
        "btc": "BTC-USD",
        "eth": "ETH-USD",
        "sol": "SOL-USD",
        "natural gas": "NG=F",
        "natgas": "NG=F",
        "copper": "HG=F",
        "20+ year treasury etf": "TLT",
    }
    for alias, ticker in _aliases.items():
        name_to_ticker.setdefault(alias, ticker)
    return name_to_ticker


def build_scenario_intel(report: WeeklyReport) -> list[ScenarioAssetIntel]:
    """Build ScenarioAssetIntel list from report's scenario_views."""
    # Build name→ticker map so we can match narrative asset names to scenario tickers
    name_to_ticker = _build_name_to_ticker_map()

    # Build ticker → consensus lookup and source_details from narratives
    ticker_consensus: dict[str, dict] = {}
    ticker_source_details: dict[str, dict[str, list[SourceSignalDetail]]] = {}
    ticker_seen_signals: dict[str, set[str]] = {}
    for narrative in report.narratives:
        for asent in narrative.asset_sentiments:
            # Resolve narrative asset name to canonical ticker
            resolved_ticker = name_to_ticker.get(asent.ticker.lower(), asent.ticker)
            existing = ticker_consensus.get(resolved_ticker)
            if existing is None or narrative.confidence > existing["confidence"]:
                consensus_view = asent.consensus_view or narrative.consensus_view
                try:
                    edge_type = EdgeType(asent.edge_type) if asent.edge_type else narrative.edge_type
                except ValueError:
                    edge_type = narrative.edge_type
                # Extract sources from text if not provided at narrative level
                sources = narrative.consensus_sources or _extract_sources(consensus_view)
                ticker_consensus[resolved_ticker] = {
                    "confidence": narrative.confidence,
                    "consensus_view": consensus_view,
                    "consensus_sources": sources,
                    "edge_type": edge_type,
                    "edge_rationale": asent.edge_rationale or narrative.edge_rationale,
                    "catalyst": getattr(asent, "catalyst", "") or "",
                    "exit_condition": getattr(asent, "exit_condition", "") or "",
                }
            # Collect source signals with links for this ticker
            seen = ticker_seen_signals.setdefault(resolved_ticker, set())
            details = ticker_source_details.setdefault(resolved_ticker, {})
            for sig in narrative.signals:
                if sig.id and sig.id in seen:
                    continue
                if sig.id:
                    seen.add(sig.id)
                label = SOURCE_LABELS.get(sig.source, sig.source.value)
                snippet = (sig.content[:200] + "\u2026") if len(sig.content) > 200 else sig.content
                details.setdefault(label, []).append(
                    SourceSignalDetail(title=sig.title, url=sig.url, snippet=snippet)
                )

    # Build composite_by_ticker lookup from report.composite_scores
    # Index by both raw name and resolved Yahoo ticker for cross-format matching
    composite_by_ticker: dict[str, object] = {}
    for cs in getattr(report, "composite_scores", None) or []:
        composite_by_ticker[cs.ticker] = cs
        resolved = name_to_ticker.get(cs.ticker.lower())
        if resolved:
            composite_by_ticker[resolved] = cs

    # Build mechanism_id → chain_progress lookup from active_scenarios
    # so we can backfill older reports where scenario_views lack chain_progress
    mech_chain: dict[str, list] = {}
    for sc in report.active_scenarios:
        if sc.chain_progress:
            mech_chain[sc.mechanism_id] = sc.chain_progress

    results: list[ScenarioAssetIntel] = []
    for sv in report.scenario_views:
        resolved_sv_ticker = name_to_ticker.get(sv.ticker.lower(), sv.ticker)
        cons = ticker_consensus.get(resolved_sv_ticker, {})
        # Backfill chain_progress from active_scenarios for older reports
        for entry in sv.scenarios:
            if not entry.chain_progress and entry.mechanism_id in mech_chain:
                entry.chain_progress = mech_chain[entry.mechanism_id]

        # Recompute avg_probability from scenario entries if missing from stored data
        avg_prob = sv.avg_probability
        if avg_prob == 0.0 and sv.scenarios:
            avg_prob = sum(s.probability for s in sv.scenarios) / len(sv.scenarios)

        # Look up composite score for this ticker (try raw, then resolved)
        comp = composite_by_ticker.get(sv.ticker) or composite_by_ticker.get(resolved_sv_ticker)

        # Use composite direction when available (matches Sheets export);
        # fall back to scenario-only net_direction for older reports.
        if comp:
            effective_direction = comp.direction
        else:
            effective_direction = sv.net_direction

        results.append(
            ScenarioAssetIntel(
                ticker=sv.ticker,
                asset_class=sv.asset_class,
                net_direction=effective_direction,
                net_score=sv.net_score,
                avg_probability=round(avg_prob, 4),
                scenarios=sv.scenarios,
                conflict_flag=sv.conflict_flag,
                scenario_count=sv.scenario_count,
                dominant_scenario=sv.dominant_scenario,
                consensus_view=cons.get("consensus_view", ""),
                consensus_sources=cons.get("consensus_sources", []),
                edge_type=cons.get("edge_type", EdgeType.ALIGNED),
                edge_rationale=cons.get("edge_rationale", ""),
                catalyst=cons.get("catalyst", ""),
                exit_condition=cons.get("exit_condition", ""),
                source_details=ticker_source_details.get(resolved_sv_ticker, {}),
                composite_score=comp.composite_score if comp else 0.0,
                narrative_score=comp.narrative_score if comp else 0.0,
                technical_score=comp.technical_score if comp else 0.0,
                scenario_score=comp.scenario_score if comp else 0.0,
                contrarian_bonus=comp.contrarian_bonus if comp else 0.0,
            )
        )
    return results


def _scenario_consensus_html(intel: ScenarioAssetIntel) -> str:
    """Build the consensus vs. edge section for a scenario card."""
    if not intel.consensus_view:
        return ""

    edge_label = EDGE_LABELS.get(intel.edge_type, "ALIGNED")
    edge_css_class = f"edge-{intel.edge_type.value}"

    citation_chips = ""
    for src in intel.consensus_sources:
        citation_chips += f'<span class="citation-chip">{src}</span> '

    html = (
        f'<div class="consensus-edge-block">'
        f'<div class="edge-header">'
        f'<span class="edge-badge {edge_css_class}">{edge_label}</span>'
        f'<span class="edge-label">vs consensus</span>'
        f'</div>'
        f'<div class="consensus-row">'
        f'<span class="consensus-label">CONSENSUS:</span>'
        f'<span class="consensus-text">{intel.consensus_view}</span>'
        f'</div>'
    )

    if citation_chips:
        html += f'<div class="consensus-citations">{citation_chips}</div>'

    if intel.edge_rationale:
        html += (
            f'<div class="consensus-row">'
            f'<span class="edge-diff-label">OUR EDGE:</span>'
            f'<span class="edge-diff-text">{intel.edge_rationale}</span>'
            f'</div>'
        )

    html += '</div>'
    return html


def _scenario_catalyst_exit_html(intel: ScenarioAssetIntel) -> str:
    """Build the catalyst + exit condition section for a scenario card."""
    if not intel.catalyst and not intel.exit_condition:
        return ""

    rows = ""
    if intel.catalyst:
        rows += (
            f'<div class="catalyst-row">'
            f'<span class="catalyst-label">CATALYST:</span>'
            f'<span class="catalyst-text">{intel.catalyst}</span>'
            f'</div>'
        )
    if intel.exit_condition:
        rows += (
            f'<div class="catalyst-row">'
            f'<span class="exit-label">EXIT WHEN:</span>'
            f'<span class="exit-text">{intel.exit_condition}</span>'
            f'</div>'
        )

    return f'<div class="catalyst-exit-block">{rows}</div>'


def _build_ticker_to_name_map() -> dict[str, str]:
    """Build a mapping from Yahoo Finance tickers to human-readable names."""
    ticker_to_name: dict[str, str] = {}
    for _class, items in settings.assets.items():
        for item in items:
            ticker_to_name[item["ticker"]] = item["name"]
    return ticker_to_name


_TICKER_NAMES: dict[str, str] = {}


def _get_ticker_name(ticker: str) -> str:
    """Return human-readable name for a ticker, falling back to the ticker itself."""
    global _TICKER_NAMES
    if not _TICKER_NAMES:
        _TICKER_NAMES = _build_ticker_to_name_map()
    return _TICKER_NAMES.get(ticker, ticker)


def _render_scenario_card(
    intel: ScenarioAssetIntel,
    tech_snapshot: TechnicalSnapshot | None = None,
) -> None:
    """Render a single scenario-based asset card."""
    dir_val = intel.net_direction.value
    # Use composite_score as primary display; fall back to net_score
    primary_score = intel.composite_score if intel.composite_score != 0.0 else intel.net_score
    score_sign = "+" if primary_score > 0 else ""
    score_class = f"score-{dir_val}"
    ac_label = ASSET_LABELS.get(intel.asset_class, intel.asset_class.value)
    display_name = _get_ticker_name(intel.ticker)

    conflict_html = ""
    if intel.conflict_flag:
        conflict_html = ' <span class="conflict-badge">CONFLICTING</span>'

    scenario_count_html = (
        f'<span class="scenario-count-chip">'
        f'{intel.scenario_count} scenario{"s" if intel.scenario_count != 1 else ""}'
        f"</span>"
    )

    # Build scenario sub-blocks
    scenario_blocks = ""
    for entry in intel.scenarios:
        stage_class = f"stage-{entry.chain_stage}" if entry.chain_stage in ("early", "mid", "late", "complete") else "stage-early"
        category_display = entry.category.replace("_", " ")

        watch_html = ""
        if entry.watch_items:
            watch_list = ", ".join(entry.watch_items[:4])
            watch_html = (
                f'<div class="scenario-watch">'
                f'<span class="scenario-watch-label">WATCH:</span> {watch_list}'
                f"</div>"
            )

        rationale_html = ""
        if entry.rationale:
            rationale_html = f'<div class="scenario-rationale">{entry.rationale}</div>'

        dir_badge = f'<span class="badge badge-{entry.direction.value}">{entry.direction.value}</span>'

        # Build chain progress visualization
        chain_html = ""
        if entry.chain_progress:
            status_icons = {
                "confirmed": "\u2713",
                "emerging": "~",
                "not_started": "\u00b7",
                "invalidated": "\u2717",
            }
            steps_html = ""
            for i, step in enumerate(entry.chain_progress):
                status = step.status if step.status in status_icons else "not_started"
                icon = status_icons[status]
                status_label = status.replace("_", " ")
                desc = step.description[:30] + "\u2026" if len(step.description) > 30 else step.description
                if i > 0:
                    steps_html += '<span class="chain-arrow">\u2192</span>'
                steps_html += (
                    f'<span class="chain-step step-{status}">'
                    f'<span class="chain-step-desc" title="{step.description}">{desc}</span>'
                    f'<span class="chain-step-status">{icon} {status_label}</span>'
                    f"</span>"
                )
            chain_html = f'<div class="transmission-chain">{steps_html}</div>'

        scenario_blocks += (
            f'<div class="scenario-block">'
            f'<div class="scenario-header">'
            f'<span class="scenario-probability">{entry.probability:.0%}</span>'
            f'<span class="scenario-name">{entry.mechanism_name}</span>'
            f'<span class="scenario-category-chip">{category_display}</span>'
            f'<span class="stage-chip {stage_class}">{entry.chain_stage}</span>'
            f" {dir_badge}"
            f"</div>"
            f"{chain_html}"
            f"{rationale_html}"
            f"{watch_html}"
            f"</div>"
        )

    # Consensus & catalyst sections
    consensus_html = _scenario_consensus_html(intel)
    catalyst_exit_html = _scenario_catalyst_exit_html(intel)

    # Technicals section
    technicals_html = ""
    if tech_snapshot:
        technicals_html = _technicals_html(tech_snapshot, intel.net_direction)

    # Source details with links
    source_details_html = _source_details_html(intel.source_details)

    # Component breakdown row (only shown when composite data exists)
    composite_breakdown_html = ""
    if intel.composite_score != 0.0:
        composite_breakdown_html = (
            f'<div class="composite-breakdown">'
            f'<span class="comp-label">NAR</span><span class="comp-val">{intel.narrative_score:+.2f}</span>'
            f'<span class="comp-sep">\u00b7</span>'
            f'<span class="comp-label">TECH</span><span class="comp-val">{intel.technical_score:+.2f}</span>'
            f'<span class="comp-sep">\u00b7</span>'
            f'<span class="comp-label">SCEN</span><span class="comp-val">{intel.scenario_score:+.2f}</span>'
            f'<span class="comp-sep">\u00b7</span>'
            f'<span class="comp-label">EDGE</span><span class="comp-val">{intel.contrarian_bonus:+.2f}</span>'
            f"</div>"
        )

    card_html = (
        f'<div class="asset-card asset-card-{dir_val}">'
        # Header row
        f'<div class="asset-card-header">'
        f'<span class="asset-ticker">{_get_ticker_name(intel.ticker)}</span>'
        f'<span class="asset-class-label">{ac_label}</span>'
        f'<span class="badge badge-{dir_val}">{dir_val}</span>'
        f'<span class="{score_class} score-value">{score_sign}{primary_score:.2f}</span>'
        f'<span class="avg-prob-chip">{intel.avg_probability:.0%} avg prob</span>'
        f" {scenario_count_html}"
        f"{conflict_html}"
        f"</div>"
        # Composite score breakdown
        f"{composite_breakdown_html}"
        # Scenario sub-blocks
        f"{scenario_blocks}"
        # Consensus vs. edge
        f"{consensus_html}"
        # Catalyst & exit condition
        f"{catalyst_exit_html}"
        # Technicals
        f"{technicals_html}"
        # Source signals with links
        f"{source_details_html}"
        f"</div>"
    )
    st.markdown(card_html, unsafe_allow_html=True)


def _render_scenario_view(
    report: WeeklyReport,
    selected_assets: list[AssetClass],
    direction_filter: str,
    min_threshold: float,
) -> None:
    """Render the scenario-based asset view."""
    all_intel = build_scenario_intel(report)

    # Apply filters
    filtered = [
        i for i in all_intel
        if i.asset_class in selected_assets
    ]

    # Filter by max scenario probability for this asset
    if min_threshold > 0:
        filtered = [
            i for i in filtered
            if any(s.probability >= min_threshold for s in i.scenarios)
        ]

    if direction_filter == "Bullish":
        filtered = [i for i in filtered if i.net_direction == SentimentDirection.BULLISH]
    elif direction_filter == "Bearish":
        filtered = [i for i in filtered if i.net_direction == SentimentDirection.BEARISH]

    # Fetch technicals
    all_tickers = tuple(sorted({i.ticker for i in filtered}))
    tech_snapshots = _fetch_technicals(all_tickers) if all_tickers else {}

    # Partition by direction — sort by composite score when available, else net_score
    def _sort_key(i: ScenarioAssetIntel) -> float:
        return abs(i.composite_score) if i.composite_score != 0.0 else abs(i.net_score)

    bullish = sorted(
        [i for i in filtered if i.net_direction == SentimentDirection.BULLISH],
        key=_sort_key,
        reverse=True,
    )
    bearish = sorted(
        [i for i in filtered if i.net_direction == SentimentDirection.BEARISH],
        key=_sort_key,
        reverse=True,
    )
    neutral = sorted(
        [i for i in filtered if i.net_direction == SentimentDirection.NEUTRAL],
        key=lambda i: i.scenario_count,
        reverse=True,
    )

    if bullish:
        st.markdown(
            f'<div class="call-section-header call-section-bullish">'
            f"BULLISH SCENARIOS ({len(bullish)})</div>",
            unsafe_allow_html=True,
        )
        for intel in bullish:
            _render_scenario_card(intel, tech_snapshots.get(intel.ticker))

    if bearish:
        st.markdown(
            f'<div class="call-section-header call-section-bearish">'
            f"BEARISH SCENARIOS ({len(bearish)})</div>",
            unsafe_allow_html=True,
        )
        for intel in bearish:
            _render_scenario_card(intel, tech_snapshots.get(intel.ticker))

    if neutral:
        neutral_rows = ""
        for intel in neutral:
            ac_label = ASSET_LABELS.get(intel.asset_class, intel.asset_class.value)
            display_score = intel.composite_score if intel.composite_score != 0.0 else intel.net_score
            breakdown_html = ""
            if intel.composite_score != 0.0:
                breakdown_html = (
                    f'<span class="comp-label" style="margin-left:6px;">NAR</span>'
                    f'<span class="comp-val">{intel.narrative_score:+.2f}</span>'
                    f'<span class="comp-sep">\u00b7</span>'
                    f'<span class="comp-label">TECH</span>'
                    f'<span class="comp-val">{intel.technical_score:+.2f}</span>'
                    f'<span class="comp-sep">\u00b7</span>'
                    f'<span class="comp-label">SCEN</span>'
                    f'<span class="comp-val">{intel.scenario_score:+.2f}</span>'
                    f'<span class="comp-sep">\u00b7</span>'
                    f'<span class="comp-label">CONT</span>'
                    f'<span class="comp-val">{intel.contrarian_bonus:+.2f}</span>'
                )
            neutral_rows += (
                f'<div style="display:flex;align-items:center;gap:10px;'
                f'padding:6px 0;border-bottom:1px solid #1a2332;flex-wrap:wrap;">'
                f'<span class="asset-ticker" style="font-size:0.85rem;">{_get_ticker_name(intel.ticker)}</span>'
                f'<span class="asset-class-label">{ac_label}</span>'
                f'<span class="score-value score-neutral">{display_score:+.2f}</span>'
                f'<span class="scenario-count-chip">{intel.scenario_count} scenarios</span>'
                f'{breakdown_html}'
                f"</div>"
            )
        st.markdown(
            f'<details class="extra-narratives" style="margin-top:12px;">'
            f'<summary class="call-section-header call-section-neutral" '
            f'style="cursor:pointer;">NEUTRAL ({len(neutral)})</summary>'
            f'<div style="padding-top:8px;">{neutral_rows}</div>'
            f"</details>",
            unsafe_allow_html=True,
        )

    if not bullish and not bearish and not neutral:
        st.markdown(
            '<div class="text-muted" style="text-align:center;padding:40px 0;">'
            "No scenario calls match the current filters.</div>",
            unsafe_allow_html=True,
        )


def _render_legacy_view(
    report: WeeklyReport,
    selected_assets: list[AssetClass],
    direction_filter: str,
    min_threshold: float,
) -> None:
    """Legacy narrative-based rendering (existing logic, extracted)."""
    all_intel = build_asset_intel(report)

    filtered = [
        i for i in all_intel
        if i.asset_class in selected_assets and i.conviction >= min_threshold
    ]

    if direction_filter == "Bullish":
        filtered = [i for i in filtered if i.direction == SentimentDirection.BULLISH]
    elif direction_filter == "Bearish":
        filtered = [i for i in filtered if i.direction == SentimentDirection.BEARISH]

    all_tickers = tuple(sorted({i.ticker for i in filtered}))
    tech_snapshots = _fetch_technicals(all_tickers) if all_tickers else {}

    def _legacy_sort_key(i: AssetIntel) -> float:
        return abs(i.composite_score) if i.composite_score != 0.0 else abs(i.score)

    bullish = sorted(
        [i for i in filtered if i.direction == SentimentDirection.BULLISH],
        key=_legacy_sort_key,
        reverse=True,
    )
    bearish = sorted(
        [i for i in filtered if i.direction == SentimentDirection.BEARISH],
        key=_legacy_sort_key,
        reverse=True,
    )
    neutral = sorted(
        [i for i in filtered if i.direction == SentimentDirection.NEUTRAL],
        key=lambda i: abs(i.conviction),
        reverse=True,
    )

    if bullish:
        st.markdown(
            f'<div class="call-section-header call-section-bullish">'
            f"BULLISH CALLS ({len(bullish)})</div>",
            unsafe_allow_html=True,
        )
        for intel in bullish:
            _render_asset_card(intel, tech_snapshots.get(intel.ticker))

    if bearish:
        st.markdown(
            f'<div class="call-section-header call-section-bearish">'
            f"BEARISH CALLS ({len(bearish)})</div>",
            unsafe_allow_html=True,
        )
        for intel in bearish:
            _render_asset_card(intel, tech_snapshots.get(intel.ticker))

    if neutral:
        neutral_rows = ""
        for intel in neutral:
            ac_label = ASSET_LABELS.get(intel.asset_class, intel.asset_class.value)
            display_score = intel.composite_score if intel.composite_score != 0.0 else intel.score
            score_html = f'<span class="score-value score-neutral">{display_score:+.2f}</span>'
            neutral_rows += (
                f'<div style="display:flex;align-items:center;gap:10px;'
                f'padding:6px 0;border-bottom:1px solid #1a2332;">'
                f'<span class="asset-ticker" style="font-size:0.85rem;">{_get_ticker_name(intel.ticker)}</span>'
                f'<span class="asset-class-label">{ac_label}</span>'
                f'{score_html}'
                f'{_conviction_bar_html(intel.conviction, intel.direction)}'
                f'<span class="horizon-chip">{intel.horizon}</span>'
                f'<span class="rationale-text" style="flex:1;">{intel.primary_rationale}</span>'
                f"</div>"
            )
        st.markdown(
            f'<details class="extra-narratives" style="margin-top:12px;">'
            f'<summary class="call-section-header call-section-neutral" '
            f'style="cursor:pointer;">NEUTRAL ({len(neutral)})</summary>'
            f'<div style="padding-top:8px;">{neutral_rows}</div>'
            f"</details>",
            unsafe_allow_html=True,
        )

    if not bullish and not bearish and not neutral:
        st.markdown(
            '<div class="text-muted" style="text-align:center;padding:40px 0;">'
            "No asset calls match the current filters.</div>",
            unsafe_allow_html=True,
        )


def _consensus_meter_html(
    ticker: str,
    consensus_scores: list[ConsensusScore],
    divergence_metrics: list[DivergenceMetrics],
) -> str:
    """Render a consensus meter bar with our_score overlaid + divergence badge."""
    cs = next((c for c in consensus_scores if c.ticker == ticker), None)
    dm = next((d for d in divergence_metrics if d.ticker == ticker), None)
    if not cs:
        return ""

    # Consensus bar position: map -1..+1 to 0..100%
    consensus_pct = (cs.consensus_score + 1) / 2 * 100
    our_pct = ((dm.our_score + 1) / 2 * 100) if dm else consensus_pct

    # Divergence badge
    badge_html = ""
    if dm:
        label = dm.divergence_label.upper().replace("_", " ")
        badge_colors = {
            "strongly_contrarian": "#ff4444",
            "contrarian": "#ff8800",
            "mildly_non_consensus": "#ffcc00",
            "aligned": "#4a5568",
        }
        color = badge_colors.get(dm.divergence_label, "#4a5568")
        badge_html = (
            f'<span style="background:{color};color:#fff;padding:2px 8px;'
            f'border-radius:3px;font-size:0.65rem;font-weight:700;letter-spacing:0.05em;'
            f'margin-left:8px;">{label}</span>'
        )

    # Consensus component breakdown (collapsible)
    components_html = ""
    if cs.components:
        comp_items = ""
        for name, val in cs.components.items():
            bar_color = "#00d4aa" if val > 0 else "#ff4444" if val < 0 else "#4a5568"
            bar_width = abs(val) * 50  # max 50px per side
            display_name = name.replace("_", " ").title()
            comp_items += (
                f'<div style="display:flex;align-items:center;gap:6px;padding:2px 0;">'
                f'<span style="color:#8892a0;font-size:0.65rem;width:80px;text-align:right;">{display_name}</span>'
                f'<div style="width:100px;height:6px;background:#1a2332;border-radius:3px;position:relative;">'
                f'<div style="position:absolute;left:50%;top:0;width:1px;height:6px;background:#4a5568;"></div>'
                f'<div style="position:absolute;{"left" if val >= 0 else "right"}:50%;'
                f'width:{bar_width}px;height:6px;background:{bar_color};'
                f'border-radius:{"0 3px 3px 0" if val >= 0 else "3px 0 0 3px"};"></div>'
                f'</div>'
                f'<span style="color:#c0c8d0;font-size:0.65rem;width:35px;">{val:+.2f}</span>'
                f'</div>'
            )
        components_html = (
            f'<details style="margin-top:4px;">'
            f'<summary style="color:#8892a0;font-size:0.65rem;cursor:pointer;">Components</summary>'
            f'<div style="padding:4px 0 0 8px;">{comp_items}</div>'
            f'</details>'
        )

    # Main meter bar
    return (
        f'<div style="margin:6px 0 4px 0;padding:6px 10px;background:#0d1117;border-radius:4px;">'
        f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">'
        f'<span style="color:#8892a0;font-size:0.65rem;font-weight:600;">CONSENSUS</span>'
        f'<span style="color:#c0c8d0;font-size:0.7rem;">{cs.consensus_score:+.2f}</span>'
        f'<span style="color:#8892a0;font-size:0.6rem;">({cs.consensus_direction})</span>'
        f'{badge_html}'
        f'</div>'
        # Bar
        f'<div style="position:relative;height:12px;background:#1a2332;border-radius:6px;overflow:visible;">'
        # Center line
        f'<div style="position:absolute;left:50%;top:0;width:1px;height:12px;background:#4a5568;z-index:1;"></div>'
        # Consensus marker
        f'<div style="position:absolute;left:{consensus_pct}%;top:-1px;width:3px;height:14px;'
        f'background:#00d4aa;border-radius:2px;transform:translateX(-50%);z-index:2;" '
        f'title="Consensus: {cs.consensus_score:+.2f}"></div>'
        # Our score marker
        f'<div style="position:absolute;left:{our_pct}%;top:-2px;width:5px;height:16px;'
        f'background:#ff8800;border-radius:2px;transform:translateX(-50%);z-index:3;" '
        f'title="Our score: {dm.our_score:+.2f}" ></div>'
        f'</div>'
        f'<div style="display:flex;justify-content:space-between;margin-top:2px;">'
        f'<span style="color:#ff4444;font-size:0.55rem;">BEARISH</span>'
        f'<span style="color:#00d4aa;font-size:0.55rem;">BULLISH</span>'
        f'</div>'
        f'{components_html}'
        f'</div>'
    )


def _trade_thesis_html(ticker: str, trade_theses: list[TradeThesis]) -> str:
    """Render structured trade thesis for an asset."""
    thesis = next((t for t in trade_theses if t.ticker == ticker), None)
    if not thesis:
        return ""

    dir_color = "#00d4aa" if thesis.direction == "bullish" else "#ff4444"
    dir_arrow = "\u25b2" if thesis.direction == "bullish" else "\u25bc"

    # TP/SL levels
    if thesis.direction == "bullish":
        tp_price = thesis.entry_price * (1 + thesis.take_profit_pct / 100)
        sl_price = thesis.entry_price * (1 - abs(thesis.stop_loss_pct) / 100)
    else:
        tp_price = thesis.entry_price * (1 - abs(thesis.take_profit_pct) / 100)
        sl_price = thesis.entry_price * (1 + abs(thesis.stop_loss_pct) / 100)

    outcome_html = ""
    if thesis.exit_reason:
        outcome_color = "#00d4aa" if (thesis.pnl_pct or 0) > 0 else "#ff4444"
        outcome_html = (
            f'<div style="margin-top:4px;padding:4px 8px;background:#1a2332;border-radius:3px;">'
            f'<span style="color:{outcome_color};font-size:0.7rem;font-weight:600;">'
            f'RESOLVED: {thesis.exit_reason.upper()} | P&L: {thesis.pnl_pct:+.1f}%</span>'
            f'</div>'
        )

    return (
        f'<div style="margin:6px 0;padding:8px 10px;background:#0d1117;border:1px solid #1a2332;border-radius:4px;">'
        f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">'
        f'<span style="color:{dir_color};font-size:0.75rem;font-weight:700;">'
        f'{dir_arrow} TRADE THESIS</span>'
        f'<span style="color:#c0c8d0;font-size:0.65rem;">R:R {thesis.risk_reward_ratio:.1f}x</span>'
        f'</div>'
        f'<div style="display:flex;gap:16px;flex-wrap:wrap;">'
        f'<div style="color:#8892a0;font-size:0.65rem;">'
        f'Entry: <span style="color:#c0c8d0;">${thesis.entry_price:,.0f}</span></div>'
        f'<div style="color:#00d4aa;font-size:0.65rem;">'
        f'TP: <span style="color:#c0c8d0;">${tp_price:,.0f} ({thesis.take_profit_pct:+.1f}%)</span></div>'
        f'<div style="color:#ff4444;font-size:0.65rem;">'
        f'SL: <span style="color:#c0c8d0;">${sl_price:,.0f} (-{thesis.stop_loss_pct:.1f}%)</span></div>'
        f'<div style="color:#8892a0;font-size:0.65rem;">'
        f'Max hold: <span style="color:#c0c8d0;">{thesis.max_holding_days}d</span></div>'
        f'</div>'
        f'{outcome_html}'
        f'</div>'
    )


def _render_performance_tab(report: WeeklyReport) -> None:
    """Render the performance tracking tab with outcome metrics."""
    from storage.store import get_all_outcomes

    outcomes = get_all_outcomes()

    st.markdown(
        '<div style="padding:12px 0;">'
        '<span style="color:#00d4aa;font-size:1rem;font-weight:700;letter-spacing:0.1em;">'
        'PERFORMANCE TRACKER</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    if not outcomes:
        st.info("No trade outcomes yet. Outcomes are recorded after trades resolve (TP hit, SL hit, or 7-day expiry).")
        return

    # Compute metrics
    total = len(outcomes)
    wins = sum(1 for o in outcomes if o.get("pnl_pct", 0) > 0)
    losses = total - wins
    hit_rate = wins / total * 100 if total > 0 else 0
    avg_pnl = sum(o.get("pnl_pct", 0) for o in outcomes) / total if total > 0 else 0
    total_pnl = sum(o.get("pnl_pct", 0) for o in outcomes)

    # Direction accuracy
    dir_correct = sum(1 for o in outcomes if o.get("direction_correct"))
    dir_accuracy = dir_correct / total * 100 if total > 0 else 0

    # By exit reason
    tp_hits = sum(1 for o in outcomes if o.get("exit_reason") == "tp_hit")
    sl_hits = sum(1 for o in outcomes if o.get("exit_reason") == "sl_hit")
    expired = sum(1 for o in outcomes if o.get("exit_reason") == "time_expired")

    # Metrics by divergence bucket
    contrarian_outcomes = [o for o in outcomes if o.get("divergence_label") in ("contrarian", "strongly_contrarian")]
    aligned_outcomes = [o for o in outcomes if o.get("divergence_label") == "aligned"]

    contrarian_pnl = (sum(o.get("pnl_pct", 0) for o in contrarian_outcomes) / len(contrarian_outcomes)) if contrarian_outcomes else 0
    aligned_pnl = (sum(o.get("pnl_pct", 0) for o in aligned_outcomes) / len(aligned_outcomes)) if aligned_outcomes else 0

    # Display metrics in columns
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Trades", total)
        st.metric("Wins / Losses", f"{wins} / {losses}")
    with col2:
        st.metric("Hit Rate", f"{hit_rate:.0f}%")
        st.metric("Direction Accuracy", f"{dir_accuracy:.0f}%")
    with col3:
        st.metric("Avg P&L", f"{avg_pnl:+.1f}%")
        st.metric("Total P&L", f"{total_pnl:+.1f}%")
    with col4:
        st.metric("TP / SL / Expired", f"{tp_hits} / {sl_hits} / {expired}")
        st.metric("Avg Days Held", f"{sum(o.get('days_held', 0) for o in outcomes) / total:.1f}")

    # Divergence analysis
    if contrarian_outcomes or aligned_outcomes:
        st.markdown("---")
        st.markdown(
            '<span style="color:#00d4aa;font-size:0.85rem;font-weight:600;">EDGE VALIDATION</span>',
            unsafe_allow_html=True,
        )
        c1, c2 = st.columns(2)
        with c1:
            st.metric(
                f"Contrarian Avg P&L ({len(contrarian_outcomes)} trades)",
                f"{contrarian_pnl:+.1f}%",
            )
        with c2:
            st.metric(
                f"Aligned Avg P&L ({len(aligned_outcomes)} trades)",
                f"{aligned_pnl:+.1f}%",
            )

    # Outcome log
    st.markdown("---")
    st.markdown(
        '<span style="color:#8892a0;font-size:0.75rem;font-weight:600;">OUTCOME LOG</span>',
        unsafe_allow_html=True,
    )
    for o in outcomes[:20]:
        pnl = o.get("pnl_pct", 0)
        pnl_color = "#00d4aa" if pnl > 0 else "#ff4444"
        correct = "Y" if o.get("direction_correct") else "N"
        st.markdown(
            f'<div style="display:flex;gap:12px;padding:4px 0;border-bottom:1px solid #1a2332;'
            f'font-size:0.7rem;flex-wrap:wrap;">'
            f'<span style="color:#8892a0;width:70px;">{o.get("week", "")[:10]}</span>'
            f'<span style="color:#c0c8d0;width:70px;">{o.get("ticker", "")}</span>'
            f'<span style="color:#c0c8d0;width:50px;">{o.get("direction", "")}</span>'
            f'<span style="color:{pnl_color};width:50px;">{pnl:+.1f}%</span>'
            f'<span style="color:#8892a0;width:70px;">{o.get("exit_reason", "")}</span>'
            f'<span style="color:#8892a0;width:50px;">dir:{correct}</span>'
            f'<span style="color:#8892a0;width:60px;">div:{o.get("divergence", 0):+.2f}</span>'
            f'<span style="color:#8892a0;">{o.get("divergence_label", "")}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )


def render_actionable_view(
    report: WeeklyReport | None,
    selected_assets: list[AssetClass],
    direction_filter: str,
    min_threshold: float,
) -> None:
    """Main render entry point for the single-page actionable view."""

    if not report:
        st.info("No report data yet. Run the weekly pipeline to generate your first report.")
        return

    # --- Regime banner ---
    _render_regime_banner(report)

    # --- Tabs: Main View | Performance ---
    tab_main, tab_perf = st.tabs(["ASSET CALLS", "PERFORMANCE"])

    with tab_main:
        # --- Consensus scores summary (if available) ---
        if report.consensus_scores:
            cols = st.columns(len(report.consensus_scores))
            for idx, cs in enumerate(report.consensus_scores):
                dm = next((d for d in report.divergence_metrics if d.ticker == cs.ticker), None)
                with cols[idx]:
                    meter_html = _consensus_meter_html(
                        cs.ticker, report.consensus_scores, report.divergence_metrics
                    )
                    st.markdown(meter_html, unsafe_allow_html=True)

        # --- Trade theses summary ---
        if report.trade_theses:
            for tt in report.trade_theses:
                thesis_html = _trade_thesis_html(tt.ticker, report.trade_theses)
                st.markdown(thesis_html, unsafe_allow_html=True)

        # --- Branch: scenario-based vs legacy rendering ---
        if report.scenario_views:
            _render_scenario_view(report, selected_assets, direction_filter, min_threshold)
        else:
            _render_legacy_view(report, selected_assets, direction_filter, min_threshold)

    with tab_perf:
        _render_performance_tab(report)
