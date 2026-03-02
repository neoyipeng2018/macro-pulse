"""CLI entry point — run the weekly macro-pulse pipeline."""

import argparse
import json
import logging
import sys
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


def run_pipeline(collect_only: bool = False, sources: list[str] | None = None):
    """Run the full weekly macro-pulse pipeline."""
    from models.schemas import WeeklyReport
    from storage.store import init_db, save_report

    init_db()

    # Step 1: Collect signals
    logger.info("=== Step 1: Collecting signals ===")
    signals = collect_signals(sources)
    logger.info("Total signals collected: %d", len(signals))

    if not signals:
        logger.warning("No signals collected. Exiting.")
        return

    # Step 1b: Filter stale signals (crypto sources expire faster)
    run_date = datetime.utcnow()
    CRYPTO_SOURCES = {"fear_greed", "funding_rates", "onchain"}
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

    # Step 2: Extract narratives via LLM
    logger.info("=== Step 2: Extracting narratives ===")
    from ai.llm import get_llm
    from ai.chains.narrative_extractor import extract_narratives

    llm = get_llm()
    narratives = extract_narratives(signals, llm)
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

    # Step 4b: Compute technicals (moved from dashboard render time to pipeline time)
    logger.info("=== Step 4b: Computing technicals ===")
    from analysis.technicals import compute_technicals

    scored_tickers = [s.ticker for s in asset_scores]
    technicals = compute_technicals(scored_tickers)
    logger.info("Technicals computed for %d assets", len(technicals))

    # Step 4c: Composite scoring
    logger.info("=== Step 4c: Composite scoring ===")
    from analysis.composite_scorer import compute_composite_scores
    from analysis.calibration import calibration_multiplier
    from storage.positions import load_trades

    # Build edge_types map from narratives
    edge_types: dict[str, str] = {}
    for nar in narratives:
        for sent in nar.asset_sentiments:
            if sent.ticker not in edge_types:
                edge_types[sent.ticker] = sent.edge_type

    # Get calibration from trade history
    trade_history = load_trades(limit=100)
    cal_mult = calibration_multiplier(trade_history)
    if cal_mult != 1.0:
        logger.info("Calibration multiplier: %.2f", cal_mult)

    composite_scores = compute_composite_scores(
        asset_scores, technicals, scenario_views, edge_types, cal_mult
    )
    logger.info("Composite scores: %d assets", len(composite_scores))

    # Step 4d: Parse trade parameters
    logger.info("=== Step 4d: Parsing trade parameters ===")
    from analysis.trade_params import parse_trade_params, fetch_current_prices

    # Extract exit conditions and horizons from narratives
    exit_conditions: dict[str, str] = {}
    horizons: dict[str, str] = {}
    for nar in narratives:
        for sent in nar.asset_sentiments:
            if sent.exit_condition and sent.ticker not in exit_conditions:
                exit_conditions[sent.ticker] = sent.exit_condition
            if sent.ticker not in horizons:
                horizons[sent.ticker] = nar.horizon

    current_prices = fetch_current_prices(scored_tickers)
    trade_params = parse_trade_params(composite_scores, exit_conditions, current_prices, horizons)
    logger.info("Trade params parsed for %d assets", len(trade_params))

    # Step 4e: Position sizing
    logger.info("=== Step 4e: Position sizing ===")
    from analysis.position_sizer import size_positions, load_risk_config

    risk_config = load_risk_config()

    # Calculate existing exposure from open positions
    open_trades = load_trades(status="open")
    existing_exposure = sum(t.position_usd for t in open_trades)

    sized_positions = size_positions(
        composite_scores, trade_params, regime,
        existing_exposure_usd=existing_exposure,
        risk_config=risk_config,
    )

    # Step 4f: Risk checks + trade sheet generation
    logger.info("=== Step 4f: Generating trade sheet ===")
    from analysis.risk_checks import check_trade
    from analysis.trade_sheet import build_trades, format_trade_sheet
    from storage.positions import get_recently_stopped

    recently_stopped = get_recently_stopped()
    all_existing_trades = load_trades(limit=200)
    proposed_count = 0
    risk_results = []
    skipped: list[tuple[str, str]] = []

    params_by_ticker = {tp.ticker: tp for tp in trade_params}
    sizes_by_ticker = {sp.ticker: sp for sp in sized_positions}

    for score in composite_scores:
        tp = params_by_ticker.get(score.ticker)
        sz = sizes_by_ticker.get(score.ticker)
        if tp is None or sz is None:
            continue

        if sz.skip_reason:
            skipped.append((score.ticker, sz.skip_reason))
            continue

        tech = technicals.get(score.ticker)
        tech_agrees = None
        if tech and tech.agrees_with:
            if score.direction.value == "bullish":
                tech_agrees = tech.agrees_with == "bullish"
            elif score.direction.value == "bearish":
                tech_agrees = tech.agrees_with == "bearish"

        rc = check_trade(
            score=score,
            params=tp,
            position_usd=sz.position_usd,
            portfolio_pct=sz.portfolio_pct,
            total_capital=risk_config.total_capital_usd,
            existing_trades=all_existing_trades,
            proposed_count=proposed_count,
            technical_agrees=tech_agrees,
            recently_stopped=recently_stopped,
        )
        risk_results.append(rc)

        if rc.passed:
            proposed_count += 1
        else:
            skipped.append((score.ticker, "; ".join(rc.rejections)))

    trades = build_trades(
        composite_scores, trade_params, sized_positions, risk_results,
        regime, report_id=uuid.uuid4().hex[:12],
        calibration_mult=cal_mult,
    )
    logger.info("Generated %d actionable trades", len(trades))

    # Step 4g: Check open positions against current prices
    logger.info("=== Step 4g: Checking open positions ===")
    from storage.positions import check_open_positions, save_trades as save_trades_db

    position_events = check_open_positions(current_prices)
    if position_events:
        for evt in position_events:
            logger.info("Position event: %s %s @ $%.2f", evt["ticker"], evt["event"], evt.get("price", 0))

    # Step 5: Price validation (compare last week's predictions vs actual)
    logger.info("=== Step 5: Price validation ===")
    from analysis.price_validator import validate_predictions, compute_hit_rate
    from collectors.market_data import MarketDataCollector

    mkt = MarketDataCollector()
    actual_returns = mkt.get_weekly_returns()
    price_validations = validate_predictions(asset_scores, actual_returns)
    hit_stats = compute_hit_rate(price_validations)
    logger.info(
        "Price validation: %d/%d hits (%.1f%%)",
        hit_stats["hits"], hit_stats["total"], hit_stats["overall"] * 100,
    )

    # Step 6: Generate weekly summary
    logger.info("=== Step 6: Generating weekly summary ===")
    summary = generate_weekly_summary(
        narratives, asset_scores, regime, regime_rationale, llm
    )

    # Step 7: Build and save report + trades
    logger.info("=== Step 7: Saving report ===")
    now = datetime.utcnow()
    week_start = now - timedelta(days=now.weekday())  # Monday
    week_end = week_start + timedelta(days=6)  # Sunday

    report_id = uuid.uuid4().hex[:12]
    for t in trades:
        t.report_id = report_id

    report = WeeklyReport(
        id=report_id,
        week_start=week_start,
        week_end=week_end,
        generated_at=now,
        regime=regime,
        regime_rationale=regime_rationale,
        narratives=narratives,
        asset_scores=asset_scores,
        price_validations=price_validations,
        signal_count=len(signals),
        summary=summary,
        active_scenarios=active_scenarios,
        scenario_views=scenario_views,
        composite_scores=composite_scores,
        trades=trades,
    )

    save_report(report)
    logger.info("Report saved to database (id: %s)", report.id)

    # Save trades to trades table
    save_trades_db(trades)
    logger.info("Saved %d proposed trades", len(trades))

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
    print("\nTop Asset Scores:")
    for s in asset_scores[:10]:
        arrow = "^" if s.score > 0 else "v" if s.score < 0 else "-"
        print(f"  {arrow} {s.ticker:20s} {s.score:+.2f}  ({s.direction.value}, {s.conviction:.1f} conviction)")

    if active_scenarios:
        print(f"\nActive Scenarios ({len(active_scenarios)}):")
        for sc in sorted(active_scenarios, key=lambda x: x.probability, reverse=True):
            print(f"  [{sc.probability:.0%}] {sc.mechanism_name} ({sc.category}) — {sc.current_stage}")

    # Print trade sheet
    regime_mult = risk_config.regime_dampening.get(regime.value, 0.6)
    trade_sheet = format_trade_sheet(
        trades, skipped, regime, regime_mult, risk_config.total_capital_usd
    )
    print("\n" + trade_sheet)


def cmd_review_trades():
    """Show proposed trades from the latest run."""
    from storage.positions import load_trades
    trades = load_trades(status="proposed")
    if not trades:
        print("No proposed trades found.")
        return
    print(f"\nProposed Trades ({len(trades)}):")
    print("-" * 80)
    for t in trades:
        print(
            f"  [{t.id}] {t.ticker:12s} {t.direction:5s}  "
            f"Score: {t.composite_score:+.2f}  "
            f"Size: ${t.position_usd:,.0f}  "
            f"Entry: ${t.entry_price:,.2f}  "
            f"R:R: {t.risk_reward:.1f}x"
        )


def cmd_open_trade(trade_id: str, entry_price: float | None = None):
    """Mark a proposed trade as executed."""
    from storage.positions import update_trade_status
    update_trade_status(trade_id, "open", entry_price=entry_price)
    print(f"Trade {trade_id} marked as OPEN")


def cmd_close_trade(trade_id: str, exit_price: float, reason: str = "manual"):
    """Close a trade manually."""
    from storage.positions import update_trade_status
    update_trade_status(trade_id, "closed", exit_price=exit_price, exit_reason=reason)
    print(f"Trade {trade_id} CLOSED at ${exit_price:.2f} ({reason})")


def cmd_positions():
    """Show open positions with unrealized P&L."""
    from storage.positions import load_trades
    from analysis.trade_params import fetch_current_prices

    open_trades = load_trades(status="open") + load_trades(status="partial_tp")
    if not open_trades:
        print("No open positions.")
        return

    tickers = list({t.ticker for t in open_trades})
    prices = fetch_current_prices(tickers)

    print(f"\nOpen Positions ({len(open_trades)}):")
    print("-" * 90)
    total_pnl = 0.0
    for t in open_trades:
        current = prices.get(t.ticker, 0)
        if current and t.entry_price:
            if t.direction == "LONG":
                pnl = (current - t.entry_price) * t.position_size
                pnl_pct = (current - t.entry_price) / t.entry_price * 100
            else:
                pnl = (t.entry_price - current) * t.position_size
                pnl_pct = (t.entry_price - current) / t.entry_price * 100
            total_pnl += pnl
        else:
            pnl = 0
            pnl_pct = 0

        arrow = "+" if pnl >= 0 else ""
        print(
            f"  [{t.id}] {t.ticker:12s} {t.direction:5s}  "
            f"Entry: ${t.entry_price:,.2f}  Current: ${current:,.2f}  "
            f"P&L: {arrow}${pnl:,.2f} ({arrow}{pnl_pct:.1f}%)  "
            f"Status: {t.status}"
        )

    print("-" * 90)
    arrow = "+" if total_pnl >= 0 else ""
    print(f"  Total Unrealized P&L: {arrow}${total_pnl:,.2f}")


def cmd_journal(last: int = 20):
    """Show trade journal with P&L history."""
    from storage.positions import get_trade_journal, get_cumulative_pnl

    trades = get_trade_journal(limit=last)
    closed = [t for t in trades if t.status in ("closed", "stopped")]

    if not trades:
        print("No trade history found.")
        return

    print(f"\nTrade Journal (last {last}):")
    print("-" * 100)
    for t in trades:
        pnl_str = ""
        if t.pnl_usd is not None:
            arrow = "+" if t.pnl_usd >= 0 else ""
            pnl_str = f"P&L: {arrow}${t.pnl_usd:,.2f} ({arrow}{t.pnl_pct:.1f}%)"
        print(
            f"  [{t.id}] {t.ticker:12s} {t.direction:5s}  "
            f"Entry: ${t.entry_price:,.2f}  "
            f"Status: {t.status:10s}  "
            f"{pnl_str}"
        )

    cum_pnl = get_cumulative_pnl()
    hits = sum(1 for t in closed if t.pnl_usd and t.pnl_usd > 0)
    hit_rate = (hits / len(closed) * 100) if closed else 0

    print("-" * 100)
    arrow = "+" if cum_pnl >= 0 else ""
    print(f"  Cumulative P&L: {arrow}${cum_pnl:,.2f}  |  Hit Rate: {hit_rate:.0f}% ({hits}/{len(closed)})")


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
        choices=["news", "reddit", "central_bank", "economic_data", "cot", "fear_greed", "market_data", "economic_calendar", "prediction_markets", "spreads", "google_trends", "funding_rates", "onchain"],
        help="Specific sources to collect from (default: all)",
    )
    # Trade management commands
    parser.add_argument(
        "--review-trades", action="store_true",
        help="Show proposed trades from last run",
    )
    parser.add_argument(
        "--open-trade", type=str, metavar="TRADE_ID",
        help="Mark a trade as executed",
    )
    parser.add_argument(
        "--entry-price", type=float,
        help="Override entry price when opening a trade",
    )
    parser.add_argument(
        "--close-trade", type=str, metavar="TRADE_ID",
        help="Close a trade manually",
    )
    parser.add_argument(
        "--exit-price", type=float,
        help="Exit price when closing a trade",
    )
    parser.add_argument(
        "--reason", type=str, default="manual",
        help="Reason for closing a trade (default: manual)",
    )
    parser.add_argument(
        "--positions", action="store_true",
        help="Show open positions with unrealized P&L",
    )
    parser.add_argument(
        "--journal", action="store_true",
        help="Show trade journal with P&L history",
    )
    parser.add_argument(
        "--last", type=int, default=20,
        help="Number of trades to show in journal (default: 20)",
    )

    args = parser.parse_args()

    # Handle trade management commands
    if args.review_trades:
        from storage.store import init_db
        init_db()
        cmd_review_trades()
        return
    if args.open_trade:
        from storage.store import init_db
        init_db()
        cmd_open_trade(args.open_trade, args.entry_price)
        return
    if args.close_trade:
        from storage.store import init_db
        init_db()
        if not args.exit_price:
            print("Error: --exit-price required when closing a trade")
            sys.exit(1)
        cmd_close_trade(args.close_trade, args.exit_price, args.reason)
        return
    if args.positions:
        from storage.store import init_db
        init_db()
        cmd_positions()
        return
    if args.journal:
        from storage.store import init_db
        init_db()
        cmd_journal(args.last)
        return

    run_pipeline(collect_only=args.collect_only, sources=args.sources)


if __name__ == "__main__":
    main()
