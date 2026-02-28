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

    collectors = {
        "news": RSSNewsCollector,
        "reddit": RedditCollector,
        "central_bank": CentralBankCollector,
        "economic_data": EconomicDataCollector,
        "cot": COTCollector,
        "fear_greed": FearGreedCollector,
        "market_data": MarketDataCollector,
    }

    enabled = sources or list(collectors.keys())
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

    # Step 7: Build and save report
    logger.info("=== Step 7: Saving report ===")
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
        price_validations=price_validations,
        signal_count=len(signals),
        summary=summary,
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
    print("=" * 60)


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
        choices=["news", "reddit", "central_bank", "economic_data", "cot", "fear_greed", "market_data"],
        help="Specific sources to collect from (default: all)",
    )
    args = parser.parse_args()
    run_pipeline(collect_only=args.collect_only, sources=args.sources)


if __name__ == "__main__":
    main()
