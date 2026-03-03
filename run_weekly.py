"""CLI entry point — run the weekly macro-pulse pipeline."""

import argparse
import json
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from tqdm import tqdm

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


def run_pipeline(collect_only: bool = False, sources: list[str] | None = None):
    """Run the full weekly macro-pulse pipeline."""
    from models.schemas import WeeklyReport
    from storage.store import init_db, save_report

    init_db()

    # Step 7 (runs first): Score previous week's trades
    logger.info("=== Step 7: Scoring previous trades ===")
    try:
        score_previous_trades()
    except Exception as e:
        logger.error("Trade scoring failed (non-fatal): %s", e)

    # Step 1: Collect signals
    logger.info("=== Step 1: Collecting signals ===")
    signals = collect_signals(sources)
    logger.info("Total signals collected: %d", len(signals))

    if not signals:
        logger.warning("No signals collected. Exiting.")
        return

    # Step 1b: Collect consensus data (options, derivatives, ETF flows)
    logger.info("=== Step 1b: Collecting consensus data ===")
    consensus_signals = collect_consensus_signals()
    signals.extend(consensus_signals)
    logger.info("Consensus signals collected: %d (total: %d)", len(consensus_signals), len(signals))

    # Step 1c: Compute consensus scores for BTC and ETH
    logger.info("=== Step 1c: Computing consensus scores ===")
    from analysis.consensus_scorer import compute_consensus_scores

    consensus_scores = compute_consensus_scores(consensus_signals)
    logger.info("Consensus scores computed for %d assets", len(consensus_scores))

    # Step 1d: Filter stale signals (crypto sources expire faster)
    run_date = datetime.utcnow()
    CRYPTO_SOURCES = {"fear_greed", "funding_rates", "onchain", "options",
                      "derivatives_consensus", "etf_flows"}
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
    signals = filtered
    dropped = before - len(signals)
    if dropped:
        logger.info(
            "Relevance filter: dropped %d stale signals (crypto: %dd, default: %dd)",
            dropped, CRYPTO_MAX_AGE, DEFAULT_MAX_AGE,
        )
    logger.info("Signals after relevance filter: %d", len(signals))

    # Save raw signals
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

    # Step 2: Extract narratives via LLM (now with consensus data in prompt)
    logger.info("=== Step 2: Extracting narratives ===")
    from ai.llm import get_llm
    from ai.chains.narrative_extractor import extract_narratives

    llm = get_llm()
    narratives = extract_narratives(signals, llm, consensus_scores=consensus_scores)
    logger.info("Extracted %d narratives", len(narratives))

    if not narratives:
        logger.warning("No narratives extracted. Check LLM configuration.")
        return

    # Step 2b: Match signals to transmission mechanisms
    logger.info("=== Step 2b: Matching transmission mechanisms ===")
    from config.mechanisms import load_mechanisms
    from ai.chains.mechanism_matcher import match_mechanisms
    from analysis.scenario_aggregator import aggregate_scenarios

    mechanisms = load_mechanisms()
    if mechanisms:
        active_scenarios = match_mechanisms(signals, mechanisms, llm)
        scenario_views = aggregate_scenarios(active_scenarios)
        logger.info(
            "Matched %d active scenarios, %d asset views",
            len(active_scenarios), len(scenario_views),
        )
    else:
        active_scenarios, scenario_views = [], []
        logger.info("No mechanisms loaded — skipping scenario matching")

    # Step 3: Classify economic regime
    logger.info("=== Step 3: Classifying economic regime ===")
    from ai.chains.regime_classifier import classify_regime, generate_weekly_summary

    regime, regime_rationale, regime_confidence = classify_regime(narratives, llm)
    logger.info("Regime: %s (confidence: %.2f)", regime.value, regime_confidence)

    # Step 4: Aggregate asset scores
    logger.info("=== Step 4: Aggregating asset scores ===")
    from analysis.sentiment_aggregator import aggregate_asset_scores

    asset_scores = aggregate_asset_scores(narratives)
    logger.info("Scored %d assets", len(asset_scores))

    # Step 4b: Compute technicals
    logger.info("=== Step 4b: Computing technicals ===")
    from analysis.technicals import compute_technicals

    scored_tickers = [s.ticker for s in asset_scores]
    technicals = compute_technicals(scored_tickers)
    logger.info("Technicals computed for %d assets", len(technicals))

    # Step 4c: Composite scoring (now with divergence-scaled nudge)
    logger.info("=== Step 4c: Composite scoring ===")
    from analysis.composite_scorer import compute_composite_scores

    # Build edge_types map from narratives
    edge_types: dict[str, str] = {}
    for nar in narratives:
        for sent in nar.asset_sentiments:
            if sent.ticker not in edge_types:
                edge_types[sent.ticker] = sent.edge_type

    composite_scores = compute_composite_scores(
        asset_scores, technicals, scenario_views, edge_types,
        consensus_scores=consensus_scores,
    )
    logger.info("Composite scores: %d assets", len(composite_scores))

    # Step 4d: Compute divergence metrics
    logger.info("=== Step 4d: Computing divergence metrics ===")
    from analysis.consensus_scorer import compute_divergence
    from models.schemas import DivergenceMetrics

    composite_map = {cs.ticker: cs.composite_score for cs in composite_scores}
    divergence_data = compute_divergence(consensus_scores, composite_map)

    divergence_metrics = [
        DivergenceMetrics(**d) for d in divergence_data.values()
    ]

    # Step 4e: Generate structured trade theses for BTC and ETH
    logger.info("=== Step 4e: Generating trade theses ===")
    from analysis.outcome_tracker import generate_trade_theses

    trade_theses = generate_trade_theses(
        composite_scores, consensus_scores, divergence_data,
    )
    logger.info("Generated %d trade theses", len(trade_theses))

    # Step 5: Generate weekly summary
    logger.info("=== Step 5: Generating weekly summary ===")
    summary = generate_weekly_summary(
        narratives, asset_scores, regime, regime_rationale, llm
    )

    # Step 6: Build and save report
    logger.info("=== Step 6: Saving report ===")
    now = datetime.utcnow()
    week_start = now - timedelta(days=now.weekday())  # Monday
    week_end = week_start + timedelta(days=6)  # Sunday

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

    # Save JSON report
    reports_dir = Path("data/reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"report_{now.strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_path, "w") as f:
        json.dump(report.model_dump(mode="json"), f, indent=2, default=str)
    logger.info("JSON report saved to %s", report_path)

    # Export to Google Sheets (optional)
    from config.settings import settings as cfg

    if cfg.google_sheets_spreadsheet_id:
        try:
            from exports.sheets import export_to_sheets

            export_to_sheets(report)
        except Exception as e:
            logger.error("Google Sheets export failed: %s", e)

    # Print summary
    print("\n" + "=" * 60)
    print(f"MACRO-PULSE WEEKLY REPORT — {week_start.strftime('%b %d')} to {week_end.strftime('%b %d, %Y')}")
    print("=" * 60)
    print(f"\nRegime: {regime.value.upper()}")
    print(f"Narratives: {len(narratives)}")
    print(f"Signals processed: {len(signals)}")
    print(f"\n{summary}")

    # Print consensus scores
    if consensus_scores:
        print("\nConsensus Scores:")
        for cs in consensus_scores:
            print(f"  {cs.ticker}: {cs.consensus_score:+.2f} ({cs.consensus_direction})")
            for comp_name, comp_val in cs.components.items():
                print(f"    {comp_name}: {comp_val:+.2f}")

    # Print divergence
    if divergence_metrics:
        print("\nDivergence:")
        for dm in divergence_metrics:
            print(f"  {dm.ticker}: our={dm.our_score:+.2f} vs consensus={dm.consensus_score:+.2f} "
                  f"→ divergence={dm.divergence:+.2f} ({dm.divergence_label})")

    print("\nTop Asset Scores:")
    for s in sorted(composite_scores, key=lambda x: abs(x.composite_score), reverse=True)[:10]:
        arrow = "^" if s.composite_score > 0 else "v" if s.composite_score < 0 else "-"
        print(
            f"  {arrow} {s.ticker:20s} {s.composite_score:+.2f}  "
            f"({s.direction.value}, "
            f"nar={s.narrative_score:+.2f} tech={s.technical_score:+.2f} "
            f"scen={s.scenario_score:+.2f} nudge={s.contrarian_bonus:+.2f})"
        )

    if trade_theses:
        print(f"\nTrade Theses ({len(trade_theses)}):")
        for tt in trade_theses:
            arrow = "^" if tt.direction == "bullish" else "v"
            print(
                f"  {arrow} {tt.ticker}: {tt.direction} @ ${tt.entry_price:,.0f} "
                f"TP:{tt.take_profit_pct:+.1f}% SL:-{tt.stop_loss_pct:.1f}% "
                f"R:R={tt.risk_reward_ratio:.1f}x "
                f"div={tt.divergence_at_entry:+.2f} ({tt.divergence_label})"
            )

    if active_scenarios:
        print(f"\nActive Scenarios ({len(active_scenarios)}):")
        for sc in sorted(active_scenarios, key=lambda x: x.probability, reverse=True):
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

    args = parser.parse_args()
    run_pipeline(collect_only=args.collect_only, sources=args.sources)


if __name__ == "__main__":
    main()
