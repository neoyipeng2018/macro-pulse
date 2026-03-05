"""CLI entry point — run the weekly macro-pulse pipeline."""

import argparse
import json
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from tqdm import tqdm

from models.schemas import WeeklyReport

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("macro-pulse")


def collect_signals(sources: list[str] | None = None) -> list:
    """Collect signals from all enabled sources."""
    from collectors.rss_news import RSSNewsCollector
    from collectors.reddit import RedditCollector
    from collectors.central_bank import CentralBankCollector
    from collectors.economic_data import EconomicDataCollector
    from collectors.cot_reports import COTCollector
    from collectors.fear_greed import FearGreedCollector
    from collectors.market_data import MarketDataCollector
    from collectors.economic_calendar import EconomicCalendarCollector
    from collectors.prediction_markets import PredictionMarketCollector
    from collectors.spreads import SpreadsCollector
    from collectors.google_trends import GoogleTrendsCollector
    from collectors.funding_rates import FundingRatesCollector
    from collectors.onchain import OnChainCollector

    collectors = {
        "news": RSSNewsCollector,
        "reddit": RedditCollector,
        "central_bank": CentralBankCollector,
        "economic_data": EconomicDataCollector,
        "cot": COTCollector,
        "fear_greed": FearGreedCollector,
        "market_data": MarketDataCollector,
        "economic_calendar": EconomicCalendarCollector,
        "prediction_markets": PredictionMarketCollector,
        "spreads": SpreadsCollector,
        "google_trends": GoogleTrendsCollector,
        "funding_rates": FundingRatesCollector,
        "onchain": OnChainCollector,
    }

    if sources:
        enabled = sources
    else:
        from config.settings import settings as cfg
        enabled = cfg.sources.get("enabled_collectors", list(collectors.keys()))
    all_signals = []

    for name in tqdm(enabled, desc="Collecting signals"):
        if name not in collectors:
            logger.warning("Unknown source: %s", name)
            continue
        try:
            collector = collectors[name]()
            signals = collector.collect()
            logger.info("%s: collected %d signals", name, len(signals))
            all_signals.extend(signals)
        except Exception as e:
            logger.error("Error collecting from %s: %s", name, e)

    return all_signals


def collect_consensus_signals() -> list:
    """Collect consensus-specific signals from options, derivatives, and ETF flows."""
    from collectors.options_consensus import OptionsConsensusCollector
    from collectors.derivatives_consensus import DerivativesConsensusCollector
    from collectors.etf_flows import ETFFlowsCollector

    consensus_collectors = {
        "options": OptionsConsensusCollector,
        "derivatives_consensus": DerivativesConsensusCollector,
        "etf_flows": ETFFlowsCollector,
    }

    all_signals = []
    for name in tqdm(consensus_collectors, desc="Collecting consensus data"):
        try:
            collector = consensus_collectors[name]()
            signals = collector.collect()
            logger.info("%s: collected %d consensus signals", name, len(signals))
            all_signals.extend(signals)
        except Exception as e:
            logger.error("Error collecting consensus from %s: %s", name, e)

    return all_signals


def collect_signals_by_role(
    role: str,
    sources: list[str] | None = None,
) -> list:
    """Collect signals filtered by role ('consensus' or 'alpha')."""
    from config.signal_roles import CONSENSUS_SOURCES, ALPHA_SOURCES
    from models.schemas import Signal

    target_sources = CONSENSUS_SOURCES if role == "consensus" else ALPHA_SOURCES

    if sources:
        target_sources = target_sources & set(sources)

    # Consensus role also includes options/derivatives/ETF dedicated collectors
    all_signals: list[Signal] = []

    # Collect from standard collectors
    standard_names = [s for s in target_sources if s not in {"options", "derivatives_consensus", "etf_flows"}]
    if standard_names:
        all_signals.extend(collect_signals(standard_names))

    # Consensus role: also collect from dedicated consensus collectors
    if role == "consensus":
        all_signals.extend(collect_consensus_signals())

    return all_signals


def filter_stale_signals(signals: list, run_date: datetime | None = None) -> list:
    """Filter out stale signals based on source-specific age limits."""
    if run_date is None:
        run_date = datetime.utcnow()

    CRYPTO_SOURCES = {
        "fear_greed", "funding_rates", "onchain", "options",
        "derivatives_consensus", "etf_flows",
    }
    CRYPTO_MAX_AGE = 5
    DEFAULT_MAX_AGE = 10

    crypto_cutoff = run_date - timedelta(days=CRYPTO_MAX_AGE)
    default_cutoff = run_date - timedelta(days=DEFAULT_MAX_AGE)

    before = len(signals)
    filtered = []
    for s in signals:
        if s.metadata.get("is_forward_looking"):
            filtered.append(s)
        elif s.source.value in CRYPTO_SOURCES or s.metadata.get("asset_class") == "crypto":
            if s.timestamp.replace(tzinfo=None) >= crypto_cutoff:
                filtered.append(s)
        else:
            if s.timestamp.replace(tzinfo=None) >= default_cutoff:
                filtered.append(s)

    dropped = before - len(filtered)
    if dropped:
        logger.info(
            "Stale filter: dropped %d signals (crypto: %dd, default: %dd)",
            dropped, CRYPTO_MAX_AGE, DEFAULT_MAX_AGE,
        )
    return filtered


def score_previous_trades() -> None:
    """Step 7: Score previous week's trades against actual outcomes."""
    from analysis.outcome_tracker import validate_pending_trades
    from storage.store import (
        get_pending_trades,
        save_trade_outcome,
        update_trade_thesis_outcome,
    )

    pending = get_pending_trades()
    if not pending:
        logger.info("No pending trades to validate")
        return

    logger.info("Checking %d pending trades for outcomes", len(pending))
    outcomes = validate_pending_trades(pending)

    for outcome in outcomes:
        try:
            save_trade_outcome(outcome)
            # Find matching trade thesis and update it
            for trade in pending:
                if (trade["ticker"] == outcome.ticker
                        and trade["entry_date"] == outcome.entry_date.isoformat()):
                    update_trade_thesis_outcome(
                        trade_id=trade["id"],
                        exit_price=outcome.exit_price,
                        exit_date=outcome.exit_date.isoformat(),
                        exit_reason=outcome.exit_reason,
                        pnl_pct=outcome.pnl_pct,
                        days_held=outcome.days_held,
                        direction_correct=outcome.direction_correct,
                    )
                    break
        except Exception as e:
            logger.error("Failed to save outcome for %s: %s", outcome.ticker, e)

    if outcomes:
        logger.info(
            "Scored %d trades: %s",
            len(outcomes),
            ", ".join(f"{o.ticker} {o.exit_reason} {o.pnl_pct:+.1f}%" for o in outcomes),
        )
        # Full sync to Google Sheets (handles dedup)
        try:
            from config.settings import settings as cfg
            if cfg.google_sheets_spreadsheet_id:
                from exports.sheets import sync_trades_to_sheets
                sync_trades_to_sheets()
        except Exception as e:
            logger.error("Failed to sync trades to Sheets: %s", e)


def run_phase_1(sources: list[str] | None = None) -> dict:
    """Phase 1: Build the consensus picture."""
    from config.signal_roles import POSITIONING_SOURCES, NARRATIVE_CONSENSUS_SOURCES
    from analysis.consensus_scorer import compute_consensus_scores
    from ai.llm import get_llm
    from ai.chains.consensus_synthesizer import synthesize_consensus

    logger.info("=" * 60)
    logger.info("PHASE 1: CONSENSUS COMPUTATION")
    logger.info("=" * 60)

    logger.info("--- 1.1: Collecting consensus signals ---")
    consensus_signals = collect_signals_by_role("consensus", sources)
    logger.info("Total consensus signals: %d", len(consensus_signals))

    logger.info("--- 1.2: Computing quantitative consensus ---")
    positioning_only = [
        s for s in consensus_signals
        if s.source.value in POSITIONING_SOURCES
    ]
    quant_scores = compute_consensus_scores(positioning_only)
    logger.info("Quantitative consensus for %d assets", len(quant_scores))

    market_signals = [s for s in consensus_signals if s.source.value == "market_data"]
    positioning_signals = [
        s for s in consensus_signals
        if s.source.value in POSITIONING_SOURCES and s.source.value != "market_data"
    ]
    narrative_signals = [
        s for s in consensus_signals
        if s.source.value in NARRATIVE_CONSENSUS_SOURCES
    ]
    logger.info(
        "Signal split: %d positioning, %d narrative, %d market_data",
        len(positioning_signals), len(narrative_signals), len(market_signals),
    )

    logger.info("--- 1.3: Synthesizing consensus (positioning + narrative) ---")
    llm = get_llm()
    consensus_views = synthesize_consensus(
        quant_scores, positioning_signals, narrative_signals, market_signals, llm
    )
    logger.info("Consensus views: %d assets", len(consensus_views))

    for cv in consensus_views:
        logger.info(
            "  %s: %s (score=%+.2f, confidence=%.1f, coherence=%s)",
            cv.ticker, cv.consensus_direction.value,
            cv.quant_score, cv.consensus_confidence, cv.consensus_coherence,
        )

    return {
        "consensus_signals": consensus_signals,
        "quant_scores": quant_scores,
        "consensus_views": consensus_views,
        "llm": llm,
    }


def run_phase_2(
    phase1: dict,
    sources: list[str] | None = None,
) -> dict:
    """Phase 2: Discover non-consensus views + match mechanisms + classify regime."""
    from ai.chains.non_consensus_discoverer import discover_non_consensus
    from config.mechanisms import load_mechanisms
    from ai.chains.mechanism_matcher import match_mechanisms
    from ai.chains.regime_classifier import (
        classify_regime_from_consensus,
        generate_summary_from_consensus,
    )
    from analysis.nc_enricher import enrich_nc_views

    llm = phase1["llm"]

    logger.info("=" * 60)
    logger.info("PHASE 2: NON-CONSENSUS DISCOVERY + MECHANISMS")
    logger.info("=" * 60)

    logger.info("--- 2.1: Collecting alpha signals ---")
    alpha_signals = collect_signals_by_role("alpha", sources)
    logger.info("Alpha signals: %d", len(alpha_signals))

    logger.info("--- 2.2: Filtering stale signals ---")
    alpha_signals = filter_stale_signals(alpha_signals)
    logger.info("Alpha signals after filter: %d", len(alpha_signals))

    all_signals = phase1["consensus_signals"] + alpha_signals

    logger.info("--- 2.3: Matching transmission mechanisms ---")
    mechanisms = load_mechanisms()
    active_scenarios = []
    if mechanisms:
        active_scenarios = match_mechanisms(all_signals, mechanisms, llm)
        logger.info("Matched %d active scenarios", len(active_scenarios))
    else:
        logger.info("No mechanisms loaded")

    logger.info("--- 2.4: Classifying regime ---")
    regime, regime_rationale, _ = classify_regime_from_consensus(
        phase1["consensus_views"], active_scenarios, llm
    )
    logger.info("Regime: %s", regime.value)

    logger.info("--- 2.5: Discovering non-consensus views ---")
    non_consensus_views = discover_non_consensus(
        consensus_views=phase1["consensus_views"],
        alpha_signals=alpha_signals,
        llm=llm,
    )
    logger.info("Valid non-consensus views: %d", len(non_consensus_views))

    for ncv in non_consensus_views:
        logger.info(
            "  %s: consensus=%s, ours=%s (%s), validity=%.2f, sources=%d",
            ncv.ticker, ncv.consensus_direction.value,
            ncv.our_direction.value, ncv.edge_type,
            ncv.validity_score, ncv.independent_source_count,
        )

    logger.info("--- 2.6: Enriching NC views with mechanism/consensus links ---")
    non_consensus_views = enrich_nc_views(
        non_consensus_views,
        active_scenarios,
        phase1["quant_scores"],
        phase1["consensus_views"],
        regime,
    )

    logger.info("--- 2.7: Generating weekly summary ---")
    summary = generate_summary_from_consensus(
        phase1["consensus_views"],
        non_consensus_views,
        active_scenarios,
        regime,
        regime_rationale,
        llm,
    )

    return {
        "alpha_signals": alpha_signals,
        "all_signals": all_signals,
        "non_consensus_views": non_consensus_views,
        "active_scenarios": active_scenarios,
        "regime": regime,
        "regime_rationale": regime_rationale,
        "summary": summary,
    }


def build_report(phase1: dict, phase2: dict) -> WeeklyReport:
    """Assemble the final report from Phase 1 + Phase 2 outputs."""
    now = datetime.utcnow()
    week_start = now - timedelta(days=now.weekday())
    week_end = week_start + timedelta(days=6)

    return WeeklyReport(
        id=uuid.uuid4().hex[:12],
        week_start=week_start,
        week_end=week_end,
        generated_at=now,
        regime=phase2["regime"],
        regime_rationale=phase2["regime_rationale"],
        signal_count=len(phase2["all_signals"]),
        summary=phase2["summary"],
        consensus_scores=phase1["quant_scores"],
        consensus_views=phase1["consensus_views"],
        non_consensus_views=phase2["non_consensus_views"],
        active_scenarios=phase2["active_scenarios"],
    )


def run_pipeline(collect_only: bool = False, sources: list[str] | None = None):
    """Run the two-phase weekly macro-pulse pipeline."""
    from storage.store import init_db, save_report

    init_db()

    if collect_only:
        logger.info("--- Collect-only mode: gathering all signals ---")
        signals = collect_signals(sources)
        consensus_sigs = collect_consensus_signals()
        signals.extend(consensus_sigs)
        logger.info("Total signals collected: %d", len(signals))

        raw_dir = Path("data/raw")
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_path = raw_dir / f"signals_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
        with open(raw_path, "w") as f:
            json.dump(
                [s.model_dump(mode="json") for s in signals],
                f, indent=2, default=str,
            )
        logger.info("Raw signals saved to %s", raw_path)
        return

    # Phase 1: Consensus Computation
    phase1 = run_phase_1(sources)
    if not phase1["consensus_views"]:
        logger.warning("Phase 1 produced no consensus views. Exiting.")
        return

    # Phase 2: Non-Consensus Discovery + Mechanisms + Regime
    phase2 = run_phase_2(phase1, sources)

    # Build report
    report = build_report(phase1, phase2)

    # Save to database
    save_report(report)
    logger.info("Report saved to database (id: %s)", report.id)

    # Save JSON report
    reports_dir = Path("data/reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"report_{report.generated_at.strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_path, "w") as f:
        json.dump(report.model_dump(mode="json"), f, indent=2, default=str)
    logger.info("JSON report saved to %s", report_path)

    # Export to Google Sheets
    from config.settings import settings as cfg
    if cfg.google_sheets_spreadsheet_id:
        try:
            from exports.sheets import export_to_sheets
            export_to_sheets(report)
        except Exception as e:
            logger.error("Google Sheets export failed: %s", e)

    _print_report_summary(report)


def run_pipeline_legacy(collect_only: bool = False, sources: list[str] | None = None):
    """Legacy monolithic pipeline (pre-three-phase restructure)."""
    from storage.store import init_db, save_report

    init_db()

    logger.info("=== Step 7: Scoring previous trades ===")
    try:
        score_previous_trades()
    except Exception as e:
        logger.error("Trade scoring failed (non-fatal): %s", e)

    logger.info("=== Step 1: Collecting signals ===")
    signals = collect_signals(sources)
    logger.info("Total signals collected: %d", len(signals))

    if not signals:
        logger.warning("No signals collected. Exiting.")
        return

    logger.info("=== Step 1b: Collecting consensus data ===")
    consensus_signals = collect_consensus_signals()
    signals.extend(consensus_signals)
    logger.info("Consensus signals collected: %d (total: %d)", len(consensus_signals), len(signals))

    logger.info("=== Step 1c: Computing consensus scores ===")
    from analysis.consensus_scorer import compute_consensus_scores
    consensus_scores = compute_consensus_scores(consensus_signals)
    logger.info("Consensus scores computed for %d assets", len(consensus_scores))

    signals = filter_stale_signals(signals)
    logger.info("Signals after relevance filter: %d", len(signals))

    raw_dir = Path("data/raw")
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"signals_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    with open(raw_path, "w") as f:
        json.dump(
            [s.model_dump(mode="json") for s in signals],
            f, indent=2, default=str,
        )
    logger.info("Raw signals saved to %s", raw_path)

    if collect_only:
        logger.info("--collect-only flag set. Stopping after collection.")
        return

    logger.info("=== Step 2: Extracting narratives ===")
    from ai.llm import get_llm
    from ai.chains.narrative_extractor import extract_narratives
    llm = get_llm()
    narratives = extract_narratives(signals, llm, consensus_scores=consensus_scores)
    logger.info("Extracted %d narratives", len(narratives))

    if not narratives:
        logger.warning("No narratives extracted. Check LLM configuration.")
        return

    logger.info("=== Step 2b: Matching transmission mechanisms ===")
    from config.mechanisms import load_mechanisms
    from ai.chains.mechanism_matcher import match_mechanisms
    from analysis.scenario_aggregator import aggregate_scenarios
    mechanisms = load_mechanisms()
    if mechanisms:
        active_scenarios = match_mechanisms(signals, mechanisms, llm)
        scenario_views = aggregate_scenarios(active_scenarios)
    else:
        active_scenarios, scenario_views = [], []

    logger.info("=== Step 3: Classifying economic regime ===")
    from ai.chains.regime_classifier import classify_regime, generate_weekly_summary
    regime, regime_rationale, regime_confidence = classify_regime(narratives, llm)

    logger.info("=== Step 4: Aggregating asset scores ===")
    from analysis.sentiment_aggregator import aggregate_asset_scores
    asset_scores = aggregate_asset_scores(narratives)

    from analysis.technicals import compute_technicals
    technicals = compute_technicals([s.ticker for s in asset_scores])

    from analysis.composite_scorer import compute_composite_scores
    edge_types: dict[str, str] = {}
    for nar in narratives:
        for sent in nar.asset_sentiments:
            if sent.ticker not in edge_types:
                edge_types[sent.ticker] = sent.edge_type

    composite_scores = compute_composite_scores(
        asset_scores, technicals, scenario_views, edge_types,
        consensus_scores=consensus_scores,
    )

    from analysis.consensus_scorer import compute_divergence
    from models.schemas import DivergenceMetrics
    composite_map = {cs.ticker: cs.composite_score for cs in composite_scores}
    divergence_data = compute_divergence(consensus_scores, composite_map)
    divergence_metrics = [DivergenceMetrics(**d) for d in divergence_data.values()]

    from analysis.outcome_tracker import generate_trade_theses
    trade_theses = generate_trade_theses(
        composite_scores, consensus_scores, divergence_data,
    )

    summary = generate_weekly_summary(
        narratives, asset_scores, regime, regime_rationale, llm
    )

    now = datetime.utcnow()
    week_start = now - timedelta(days=now.weekday())
    week_end = week_start + timedelta(days=6)

    report = WeeklyReport(
        id=uuid.uuid4().hex[:12],
        week_start=week_start,
        week_end=week_end,
        generated_at=now,
        regime=regime,
        regime_rationale=regime_rationale,
        narratives=narratives,
        asset_scores=asset_scores,
        signal_count=len(signals),
        summary=summary,
        active_scenarios=active_scenarios,
        scenario_views=scenario_views,
        composite_scores=composite_scores,
        consensus_scores=consensus_scores,
        divergence_metrics=divergence_metrics,
        trade_theses=trade_theses,
    )

    save_report(report)
    logger.info("Report saved to database (id: %s)", report.id)

    reports_dir = Path("data/reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"report_{now.strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_path, "w") as f:
        json.dump(report.model_dump(mode="json"), f, indent=2, default=str)
    logger.info("JSON report saved to %s", report_path)

    from config.settings import settings as cfg
    if cfg.google_sheets_spreadsheet_id:
        try:
            from exports.sheets import export_to_sheets
            export_to_sheets(report)
        except Exception as e:
            logger.error("Google Sheets export failed: %s", e)

    _print_report_summary(report)


def _print_report_summary(report: WeeklyReport) -> None:
    """Print a human-readable summary of the report to stdout."""
    print("\n" + "=" * 60)
    print(f"MACRO-PULSE WEEKLY REPORT — {report.week_start.strftime('%b %d')} to {report.week_end.strftime('%b %d, %Y')}")
    print("=" * 60)
    print(f"\nRegime: {report.regime.value.upper()}")
    print(f"Signals processed: {report.signal_count}")
    print(f"\n{report.summary}")

    if report.consensus_views:
        print("\nConsensus Picture (Phase 1):")
        for cv in report.consensus_views:
            print(f"  {cv.ticker}: {cv.consensus_direction.value} "
                  f"(quant={cv.quant_score:+.2f}, confidence={cv.consensus_confidence:.1f}, "
                  f"coherence={cv.consensus_coherence})")

    if report.consensus_scores:
        print("\nConsensus Scores:")
        for cs in report.consensus_scores:
            print(f"  {cs.ticker}: {cs.consensus_score:+.2f} ({cs.consensus_direction})")

    if report.non_consensus_views:
        print(f"\nNon-Consensus Views (Phase 2): {len(report.non_consensus_views)}")
        for ncv in report.non_consensus_views:
            mechanisms_str = ""
            if ncv.supporting_mechanisms:
                mechanisms_str = f", mechanisms={','.join(ncv.supporting_mechanisms)}"
            print(f"  {ncv.ticker}: {ncv.edge_type} {ncv.our_direction.value} "
                  f"(validity={ncv.validity_score:.2f}, sources={ncv.independent_source_count}"
                  f"{mechanisms_str})")
    else:
        print("\nNo non-consensus views this week.")

    if report.active_scenarios:
        print(f"\nActive Mechanisms ({len(report.active_scenarios)}):")
        for sc in sorted(report.active_scenarios, key=lambda x: x.probability, reverse=True):
            print(f"  [{sc.probability:.0%}] {sc.mechanism_name} ({sc.category}) — {sc.current_stage}")


def main():
    parser = argparse.ArgumentParser(description="macro-pulse weekly pipeline")
    parser.add_argument(
        "--collect-only",
        action="store_true",
        help="Only collect signals, skip LLM processing",
    )
    parser.add_argument(
        "--sources",
        nargs="+",
        choices=[
            "news", "reddit", "central_bank", "economic_data", "cot",
            "fear_greed", "market_data", "economic_calendar",
            "prediction_markets", "spreads", "google_trends",
            "funding_rates", "onchain",
        ],
        help="Specific sources to collect from (default: all)",
    )
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="Use legacy monolithic pipeline instead of three-phase",
    )

    args = parser.parse_args()
    if args.legacy:
        run_pipeline_legacy(collect_only=args.collect_only, sources=args.sources)
    else:
        run_pipeline(collect_only=args.collect_only, sources=args.sources)


if __name__ == "__main__":
    main()
