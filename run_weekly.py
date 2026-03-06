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
    from collectors.mempool import MempoolCollector
    from collectors.eth_onchain import EthOnChainCollector
    from collectors.twitter import TwitterCryptoCollector
    from collectors.youtube_crypto import YouTubeCryptoCollector
    from collectors.exa_news import ExaNewsCollector

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
        "mempool": MempoolCollector,
        "eth_onchain": EthOnChainCollector,
        "twitter_crypto": TwitterCryptoCollector,
        "youtube_crypto": YouTubeCryptoCollector,
        "exa_news": ExaNewsCollector,
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


def collect_all_signals(sources: list[str] | None = None) -> dict[str, list]:
    """Single collection pass. Returns signals classified by role."""
    from config.signal_roles import CONSENSUS_SOURCES, ALPHA_SOURCES

    all_signals = collect_signals(sources)
    consensus_sigs = collect_consensus_signals()
    all_signals.extend(consensus_sigs)

    consensus = [
        s for s in all_signals
        if s.source.value in CONSENSUS_SOURCES
        or s.source.value in {"options", "derivatives_consensus", "etf_flows"}
    ]
    alpha = filter_stale_signals(
        [s for s in all_signals if s.source.value in ALPHA_SOURCES]
    )

    return {
        "all": all_signals,
        "consensus": consensus,
        "alpha": alpha,
    }


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



def run_phase_1(classified_signals: dict[str, list]) -> dict:
    """Phase 1: Build the consensus picture."""
    from config.signal_roles import POSITIONING_SOURCES, NARRATIVE_CONSENSUS_SOURCES
    from analysis.consensus_scorer import compute_consensus_scores
    from analysis.regime_voter import compute_regime_votes, tally_regime_votes
    from analysis.direction_targets import compute_ranges_for_assets
    from ai.llm import get_llm
    from ai.chains.consensus_synthesizer import synthesize_consensus

    logger.info("=" * 60)
    logger.info("PHASE 1: CONSENSUS COMPUTATION")
    logger.info("=" * 60)

    consensus_signals = classified_signals["consensus"]
    all_signals = classified_signals["all"]
    logger.info("Total consensus signals: %d", len(consensus_signals))

    logger.info("--- 1.1: Computing quantitative consensus ---")
    positioning_only = [
        s for s in consensus_signals
        if s.source.value in POSITIONING_SOURCES
    ]
    quant_scores = compute_consensus_scores(positioning_only)
    logger.info("Quantitative consensus for %d assets", len(quant_scores))

    logger.info("--- 1.2: Regime pre-scoring (quant votes) ---")
    regime_votes = compute_regime_votes(all_signals, quant_scores)
    regime_pre, regime_conf, regime_rationale = tally_regime_votes(regime_votes)
    logger.info(
        "Regime pre-score: %s (confidence=%.2f) — %s",
        regime_pre, regime_conf, regime_rationale,
    )
    for rv in regime_votes:
        logger.info("  Vote: %s → %s (%.2f) %s", rv.indicator, rv.regime, rv.confidence, rv.rationale)

    logger.info("--- 1.3: Computing 1-week consensus ranges ---")
    consensus_ranges = compute_ranges_for_assets(all_signals, quant_scores)
    for ticker, rng in consensus_ranges.items():
        logger.info(
            "  %s: $%.0f — $%.0f (mid=$%.0f, σ=$%.0f)",
            ticker, rng["consensus_low"], rng["consensus_high"],
            rng["consensus_mid"], rng["sigma_1w_usd"],
        )

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

    logger.info("--- 1.4: Synthesizing consensus (positioning + narrative) ---")
    llm = get_llm()
    consensus_views = synthesize_consensus(
        quant_scores, positioning_signals, narrative_signals, market_signals, llm
    )
    logger.info("Consensus views: %d assets", len(consensus_views))

    for cv in consensus_views:
        if cv.ticker in consensus_ranges:
            cv.one_week_range = consensus_ranges[cv.ticker]
        logger.info(
            "  %s: %s (score=%+.2f, confidence=%.1f, coherence=%s)",
            cv.ticker, cv.consensus_direction.value,
            cv.quant_score, cv.consensus_confidence, cv.consensus_coherence,
        )

    regime_vote_dicts = [
        {"indicator": rv.indicator, "regime": rv.regime,
         "confidence": rv.confidence, "rationale": rv.rationale}
        for rv in regime_votes
    ]

    return {
        "consensus_signals": consensus_signals,
        "quant_scores": quant_scores,
        "consensus_views": consensus_views,
        "regime_votes": regime_vote_dicts,
        "regime_pre_score": regime_pre,
        "regime_pre_confidence": regime_conf,
        "regime_pre_rationale": regime_rationale,
        "consensus_ranges": consensus_ranges,
        "llm": llm,
    }


def run_phase_2(
    phase1: dict,
    classified_signals: dict[str, list],
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
    from analysis.nc_validator import validate_and_filter_nc_views

    llm = phase1["llm"]

    logger.info("=" * 60)
    logger.info("PHASE 2: NON-CONSENSUS DISCOVERY + MECHANISMS")
    logger.info("=" * 60)

    alpha_signals = classified_signals["alpha"]
    all_signals = classified_signals["all"]
    logger.info("Alpha signals: %d (total: %d)", len(alpha_signals), len(all_signals))

    logger.info("--- 2.1: Matching transmission mechanisms ---")
    mechanisms = load_mechanisms()
    active_scenarios: list = []
    if mechanisms:
        active_scenarios = match_mechanisms(all_signals, mechanisms, llm)
        logger.info("Matched %d active scenarios", len(active_scenarios))
    else:
        logger.info("No mechanisms loaded")

    logger.info("--- 2.2: Classifying regime (with quant pre-score: %s) ---", phase1.get("regime_pre_score", "n/a"))
    regime, regime_rationale, _ = classify_regime_from_consensus(
        phase1["consensus_views"], active_scenarios, llm
    )
    logger.info("Regime: %s", regime.value)

    logger.info("--- 2.3: Discovering non-consensus views ---")
    non_consensus_views = discover_non_consensus(
        consensus_views=phase1["consensus_views"],
        alpha_signals=alpha_signals,
        llm=llm,
    )
    logger.info("LLM produced %d raw NC views", len(non_consensus_views))

    logger.info("--- 2.4: Validating NC views (multi-source + causal gates) ---")
    raw_nc_dicts = [ncv.model_dump() for ncv in non_consensus_views]
    validated_pairs = validate_and_filter_nc_views(
        raw_nc_dicts, active_scenarios, mechanisms or [], all_signals
    )
    logger.info(
        "NC validation: %d/%d passed both gates",
        len(validated_pairs), len(non_consensus_views),
    )

    validated_nc_views = []
    for nc_dict, validation in validated_pairs:
        ncv = _rebuild_nc_view(nc_dict, validation, phase1.get("consensus_ranges", {}))
        validated_nc_views.append(ncv)

    for ncv in non_consensus_views:
        if ncv.ticker not in {v.ticker for v in validated_nc_views}:
            logger.info(
                "  DROPPED: %s %s — failed validation gates",
                ncv.ticker, ncv.our_direction.value,
            )

    for ncv in validated_nc_views:
        logger.info(
            "  PASSED: %s %s — sources=%s, mechanism=%s (%s)",
            ncv.ticker, ncv.our_direction.value,
            ncv.validation_sources,
            ncv.validation_mechanism_id or "none",
            ncv.validation_mechanism_stage or "n/a",
        )

    logger.info("--- 2.5: Enriching NC views with mechanism/consensus links ---")
    validated_nc_views = enrich_nc_views(
        validated_nc_views,
        active_scenarios,
        phase1["quant_scores"],
        phase1["consensus_views"],
        regime,
    )

    logger.info("--- 2.6: Generating weekly summary ---")
    summary = generate_summary_from_consensus(
        phase1["consensus_views"],
        validated_nc_views,
        active_scenarios,
        regime,
        regime_rationale,
        llm,
    )

    return {
        "alpha_signals": alpha_signals,
        "all_signals": all_signals,
        "non_consensus_views": validated_nc_views,
        "active_scenarios": active_scenarios,
        "regime": regime,
        "regime_rationale": regime_rationale,
        "summary": summary,
    }


def _rebuild_nc_view(nc_dict: dict, validation: "NCValidation", consensus_ranges: dict) -> "NonConsensusView":
    """Rebuild a NonConsensusView from a validated dict, populating validation fields."""
    from analysis.nc_validator import NCValidation
    from models.schemas import NonConsensusView, SentimentDirection, AssetClass

    evidence_urls = []
    for ev in nc_dict.get("evidence", []):
        if isinstance(ev, dict) and ev.get("url"):
            evidence_urls.append({"source": ev.get("source", ""), "url": ev["url"], "summary": ev.get("summary", "")})

    ticker = nc_dict.get("ticker", "")
    nc_range = consensus_ranges.get(ticker, {})

    return NonConsensusView(
        ticker=ticker,
        asset_class=AssetClass(nc_dict.get("asset_class", "crypto")),
        consensus_direction=SentimentDirection(nc_dict.get("consensus_direction", "neutral")),
        consensus_narrative=nc_dict.get("consensus_narrative", ""),
        our_direction=SentimentDirection(nc_dict.get("our_direction", "neutral")),
        our_conviction=nc_dict.get("our_conviction", 0.0),
        thesis=nc_dict.get("thesis", ""),
        edge_type=nc_dict.get("edge_type", "contrarian"),
        evidence=[ev for ev in nc_dict.get("evidence", []) if isinstance(ev, dict)],
        independent_source_count=validation.source_count,
        has_testable_mechanism=validation.causal_pass,
        has_catalyst=nc_dict.get("has_catalyst", ""),
        invalidation=nc_dict.get("invalidation", ""),
        validity_score=nc_dict.get("validity_score", 0.0),
        signal_ids=nc_dict.get("signal_ids", []),
        validation_multi_source=validation.multi_source_pass,
        validation_causal=validation.causal_pass,
        validation_sources=validation.independent_sources,
        validation_mechanism_id=validation.mechanism_id,
        validation_mechanism_stage=validation.mechanism_stage,
        evidence_urls=evidence_urls,
        one_week_nc_range=nc_range,
    )


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
        regime_votes=phase1.get("regime_votes", []),
        non_consensus_views=phase2["non_consensus_views"],
        active_scenarios=phase2["active_scenarios"],
    )


def run_pipeline(collect_only: bool = False, sources: list[str] | None = None):
    """Run the two-phase weekly macro-pulse pipeline."""
    from storage.store import init_db, save_report

    init_db()

    logger.info("--- Collecting all signals (single pass) ---")
    classified = collect_all_signals(sources)
    logger.info(
        "Collected %d signals (consensus=%d, alpha=%d)",
        len(classified["all"]), len(classified["consensus"]), len(classified["alpha"]),
    )

    if collect_only:
        raw_dir = Path("data/raw")
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_path = raw_dir / f"signals_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
        with open(raw_path, "w") as f:
            json.dump(
                [s.model_dump(mode="json") for s in classified["all"]],
                f, indent=2, default=str,
            )
        logger.info("Raw signals saved to %s", raw_path)
        return

    # Phase 1: Consensus Computation
    phase1 = run_phase_1(classified)
    if not phase1["consensus_views"]:
        logger.warning("Phase 1 produced no consensus views. Exiting.")
        return

    # Phase 2: Non-Consensus Discovery + Mechanisms + Regime
    phase2 = run_phase_2(phase1, classified)

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



def _print_report_summary(report: WeeklyReport) -> None:
    """Print a human-readable summary of the report to stdout."""
    print("\n" + "=" * 60)
    print(f"MACRO-PULSE WEEKLY REPORT — {report.week_start.strftime('%b %d')} to {report.week_end.strftime('%b %d, %Y')}")
    print("=" * 60)
    print(f"\nRegime: {report.regime.value.upper()}")
    print(f"Signals processed: {report.signal_count}")
    print(f"\n{report.summary}")

    if report.regime_votes:
        print("\nRegime Votes:")
        for rv in report.regime_votes:
            print(f"  {rv['indicator']}: {rv['regime']} ({rv['confidence']:.2f}) — {rv['rationale']}")

    if report.consensus_views:
        print("\nConsensus Picture (Phase 1):")
        for cv in report.consensus_views:
            range_str = ""
            if cv.one_week_range:
                range_str = f", range=${cv.one_week_range.get('consensus_low', 0):.0f}-${cv.one_week_range.get('consensus_high', 0):.0f}"
            print(f"  {cv.ticker}: {cv.consensus_direction.value} "
                  f"(quant={cv.quant_score:+.2f}, confidence={cv.consensus_confidence:.1f}, "
                  f"coherence={cv.consensus_coherence}{range_str})")

    if report.consensus_scores:
        print("\nConsensus Scores:")
        for cs in report.consensus_scores:
            print(f"  {cs.ticker}: {cs.consensus_score:+.2f} ({cs.consensus_direction})")

    if report.non_consensus_views:
        print(f"\nNon-Consensus Views (Phase 2): {len(report.non_consensus_views)}")
        for ncv in report.non_consensus_views:
            multi = "Y" if ncv.validation_multi_source else "N"
            causal = "Y" if ncv.validation_causal else "N"
            mech_str = f", mechanism={ncv.validation_mechanism_id}" if ncv.validation_mechanism_id else ""
            print(f"  {ncv.ticker}: {ncv.edge_type} {ncv.our_direction.value} "
                  f"(multi-source={multi}, causal={causal}, sources={ncv.independent_source_count}"
                  f"{mech_str})")
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
            "funding_rates", "onchain", "mempool", "eth_onchain",
            "twitter_crypto", "youtube_crypto", "exa_news",
        ],
        help="Specific sources to collect from (default: all)",
    )

    args = parser.parse_args()
    run_pipeline(collect_only=args.collect_only, sources=args.sources)


if __name__ == "__main__":
    main()
