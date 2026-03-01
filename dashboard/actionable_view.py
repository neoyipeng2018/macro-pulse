"""Actionable single-page view — what assets will do well, for how long, and why."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import streamlit as st

from analysis.technicals import TechnicalSnapshot, compute_technicals
from config.settings import settings
from models.schemas import (
    AssetClass,
    AssetScenarioEntry,
    EdgeType,
    Narrative,
    ScenarioAssetView,
    SentimentDirection,
    SignalSource,
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


def build_asset_intel(report: WeeklyReport) -> list[AssetIntel]:
    """Link WeeklyAssetScore back to Narrative data to enrich each asset."""

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
    score_sign = "+" if intel.score > 0 else ""
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

    card_html = (
        f'<div class="asset-card asset-card-{dir_val}">'
        # Header row
        f'<div class="asset-card-header">'
        f'<span class="asset-ticker">{intel.ticker}</span>'
        f'<span class="asset-class-label">{ac_label}</span>'
        f'<span class="badge badge-{dir_val}">{dir_val}</span>'
        f'<span class="{score_class} score-value">{score_sign}{intel.score:.2f}</span>'
        f'{_conviction_bar_html(intel.conviction, intel.direction)}'
        f'<span class="horizon-chip">{intel.horizon}</span>'
        f'<span class="trend-chip {trend_class}">{intel.trend}</span>'
        f"</div>"
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

    # Build ticker → consensus lookup from narratives (highest-confidence per ticker)
    ticker_consensus: dict[str, dict] = {}
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
                ticker_consensus[resolved_ticker] = {
                    "confidence": narrative.confidence,
                    "consensus_view": consensus_view,
                    "consensus_sources": narrative.consensus_sources,
                    "edge_type": edge_type,
                    "edge_rationale": asent.edge_rationale or narrative.edge_rationale,
                    "catalyst": getattr(asent, "catalyst", "") or "",
                    "exit_condition": getattr(asent, "exit_condition", "") or "",
                }

    results: list[ScenarioAssetIntel] = []
    for sv in report.scenario_views:
        resolved_sv_ticker = name_to_ticker.get(sv.ticker.lower(), sv.ticker)
        cons = ticker_consensus.get(resolved_sv_ticker, {})
        # Recompute avg_probability from scenario entries if missing from stored data
        avg_prob = sv.avg_probability
        if avg_prob == 0.0 and sv.scenarios:
            avg_prob = sum(s.probability for s in sv.scenarios) / len(sv.scenarios)
        results.append(
            ScenarioAssetIntel(
                ticker=sv.ticker,
                asset_class=sv.asset_class,
                net_direction=sv.net_direction,
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


def _render_scenario_card(
    intel: ScenarioAssetIntel,
    tech_snapshot: TechnicalSnapshot | None = None,
) -> None:
    """Render a single scenario-based asset card."""
    dir_val = intel.net_direction.value
    score_sign = "+" if intel.net_score > 0 else ""
    score_class = f"score-{dir_val}"
    ac_label = ASSET_LABELS.get(intel.asset_class, intel.asset_class.value)

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

        scenario_blocks += (
            f'<div class="scenario-block">'
            f'<div class="scenario-header">'
            f'<span class="scenario-probability">{entry.probability:.0%}</span>'
            f'<span class="scenario-name">{entry.mechanism_name}</span>'
            f'<span class="scenario-category-chip">{category_display}</span>'
            f'<span class="stage-chip {stage_class}">{entry.chain_stage}</span>'
            f" {dir_badge}"
            f"</div>"
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

    card_html = (
        f'<div class="asset-card asset-card-{dir_val}">'
        # Header row
        f'<div class="asset-card-header">'
        f'<span class="asset-ticker">{intel.ticker}</span>'
        f'<span class="asset-class-label">{ac_label}</span>'
        f'<span class="badge badge-{dir_val}">{dir_val}</span>'
        f'<span class="{score_class} score-value">{score_sign}{intel.net_score:.2f}</span>'
        f'<span class="avg-prob-chip">{intel.avg_probability:.0%} avg prob</span>'
        f" {scenario_count_html}"
        f"{conflict_html}"
        f"</div>"
        # Scenario sub-blocks
        f"{scenario_blocks}"
        # Consensus vs. edge
        f"{consensus_html}"
        # Catalyst & exit condition
        f"{catalyst_exit_html}"
        # Technicals
        f"{technicals_html}"
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

    # Partition by direction
    bullish = sorted(
        [i for i in filtered if i.net_direction == SentimentDirection.BULLISH],
        key=lambda i: abs(i.net_score),
        reverse=True,
    )
    bearish = sorted(
        [i for i in filtered if i.net_direction == SentimentDirection.BEARISH],
        key=lambda i: abs(i.net_score),
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
            neutral_rows += (
                f'<div style="display:flex;align-items:center;gap:10px;'
                f'padding:6px 0;border-bottom:1px solid #1a2332;">'
                f'<span class="asset-ticker" style="font-size:0.85rem;">{intel.ticker}</span>'
                f'<span class="asset-class-label">{ac_label}</span>'
                f'<span class="score-value score-neutral">{intel.net_score:+.2f}</span>'
                f'<span class="scenario-count-chip">{intel.scenario_count} scenarios</span>'
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

    bullish = sorted(
        [i for i in filtered if i.direction == SentimentDirection.BULLISH],
        key=lambda i: abs(i.score),
        reverse=True,
    )
    bearish = sorted(
        [i for i in filtered if i.direction == SentimentDirection.BEARISH],
        key=lambda i: abs(i.score),
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
            neutral_rows += (
                f'<div style="display:flex;align-items:center;gap:10px;'
                f'padding:6px 0;border-bottom:1px solid #1a2332;">'
                f'<span class="asset-ticker" style="font-size:0.85rem;">{intel.ticker}</span>'
                f'<span class="asset-class-label">{ac_label}</span>'
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

    # --- Branch: scenario-based vs legacy rendering ---
    if report.scenario_views:
        _render_scenario_view(report, selected_assets, direction_filter, min_threshold)
    else:
        _render_legacy_view(report, selected_assets, direction_filter, min_threshold)
