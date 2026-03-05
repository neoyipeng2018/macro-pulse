"""NC-centric dashboard — non-consensus views as the product, consensus as context."""

from __future__ import annotations

import streamlit as st

from config.settings import settings
from models.schemas import (
    ActiveScenario,
    AssetClass,
    ConsensusScore,
    ConsensusView,
    NonConsensusView,
    SentimentDirection,
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


def _build_ticker_to_name_map() -> dict[str, str]:
    ticker_to_name: dict[str, str] = {}
    for _class, items in settings.assets.items():
        for item in items:
            ticker_to_name[item["ticker"]] = item["name"]
    return ticker_to_name


_TICKER_NAMES: dict[str, str] = {}


def _get_ticker_name(ticker: str) -> str:
    global _TICKER_NAMES
    if not _TICKER_NAMES:
        _TICKER_NAMES = _build_ticker_to_name_map()
    return _TICKER_NAMES.get(ticker, ticker)


# ---------------------------------------------------------------------------
# Regime banner
# ---------------------------------------------------------------------------

def _render_regime_banner(report: WeeklyReport) -> None:
    regime_val = report.regime.value.replace("_", " ").upper()
    regime_class = report.regime.value
    rationale = report.regime_rationale or ""
    summary = report.summary or ""

    detail = rationale
    if summary and summary != rationale:
        detail = f"{rationale}  \u00b7  {summary}" if rationale else summary

    st.markdown(
        f'<div class="regime-banner">'
        f'<span class="regime-badge regime-{regime_class}">{regime_val}</span>'
        f'<span class="regime-summary">{detail}</span>'
        f"</div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Consensus section (collapsible context)
# ---------------------------------------------------------------------------

def _render_consensus_section(
    consensus_views: list[ConsensusView],
    consensus_scores: list[ConsensusScore],
) -> None:
    with st.expander("CONSENSUS PICTURE (Phase 1)", expanded=False):
        if not consensus_views:
            st.markdown(
                '<div style="color:#4a5568;font-size:0.75rem;">'
                "No consensus views available.</div>",
                unsafe_allow_html=True,
            )
            return

        cols = st.columns(min(len(consensus_views), 3))
        for idx, cv in enumerate(consensus_views):
            direction = cv.consensus_direction.value
            css_class = f"consensus-card consensus-card-{direction}"
            score_class = f"score-{direction}"
            coherence_class = f"coherence-{cv.consensus_coherence}"

            priced_in_html = ""
            if cv.priced_in:
                chips = "".join(f'<span class="priced-in-chip">{p}</span>' for p in cv.priced_in[:3])
                priced_in_html = (
                    f'<div style="margin-top:6px;">'
                    f'<span style="font-size:0.6rem;color:#4a5568;letter-spacing:0.06em;">PRICED IN:</span> {chips}'
                    f'</div>'
                )

            not_priced_html = ""
            if cv.not_priced_in:
                chips = "".join(f'<span class="not-priced-chip">{p}</span>' for p in cv.not_priced_in[:3])
                not_priced_html = (
                    f'<div style="margin-top:4px;">'
                    f'<span style="font-size:0.6rem;color:#FF9100;letter-spacing:0.06em;">NOT PRICED:</span> {chips}'
                    f'</div>'
                )

            positioning_html = ""
            if cv.positioning_summary:
                positioning_html = (
                    f'<div style="margin-top:6px;font-size:0.7rem;color:#8892a4;line-height:1.5;">'
                    f'{cv.positioning_summary[:200]}</div>'
                )

            narrative_html = ""
            if cv.market_narrative:
                narrative_html = (
                    f'<div style="margin-top:4px;font-size:0.7rem;color:#8892a4;line-height:1.5;">'
                    f'{cv.market_narrative[:250]}</div>'
                )

            # Consensus score component breakdown
            cs = next((c for c in consensus_scores if c.ticker == cv.ticker), None)
            components_html = ""
            if cs and cs.components:
                comp_items = ""
                for name, val in cs.components.items():
                    bar_color = "#00d4aa" if val > 0 else "#ff4444" if val < 0 else "#4a5568"
                    bar_width = abs(val) * 50
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
                    f'<summary style="color:#8892a0;font-size:0.65rem;cursor:pointer;">Quant Components</summary>'
                    f'<div style="padding:4px 0 0 8px;">{comp_items}</div>'
                    f'</details>'
                )

            card_html = (
                f'<div class="{css_class}">'
                f'<div class="asset-card-header">'
                f'<span class="asset-ticker">{_get_ticker_name(cv.ticker)}</span>'
                f'<span class="badge badge-{direction}">{direction.upper()}</span>'
                f'<span class="{score_class}" style="font-size:0.85rem;font-weight:700;">{cv.quant_score:+.2f}</span>'
                f'<span class="{coherence_class} coherence-badge">{cv.consensus_coherence}</span>'
                f'</div>'
                f'<div style="font-size:0.65rem;color:#4a5568;">confidence: {cv.consensus_confidence:.0%}</div>'
                f'{positioning_html}'
                f'{narrative_html}'
                f'{priced_in_html}'
                f'{not_priced_html}'
                f'{components_html}'
                f'</div>'
            )
            with cols[idx % len(cols)]:
                st.markdown(card_html, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# NC view cards (the product)
# ---------------------------------------------------------------------------

def _chain_progress_html(scenario: ActiveScenario) -> str:
    if not scenario.chain_progress:
        return ""

    status_icons = {
        "confirmed": "\u2713",
        "emerging": "~",
        "not_started": "\u00b7",
        "invalidated": "\u2717",
    }
    steps_html = ""
    for i, step in enumerate(scenario.chain_progress):
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
    return f'<div class="transmission-chain">{steps_html}</div>'


def _render_nc_view_card(
    ncv: NonConsensusView,
    consensus_view: ConsensusView | None,
    consensus_score: ConsensusScore | None,
    active_scenarios: list[ActiveScenario],
) -> None:
    consensus_dir = ncv.consensus_direction.value
    our_dir = ncv.our_direction.value
    validity_pct = int(ncv.validity_score * 100)
    conviction_pct = int(ncv.our_conviction * 100)
    ac_label = ASSET_LABELS.get(ncv.asset_class, ncv.asset_class.value)

    # Quality flags
    flags = []
    if ncv.has_testable_mechanism:
        flags.append('<span style="color:#00E676;font-size:0.6rem;">\u2713 mechanism</span>')
    else:
        flags.append('<span style="color:#4a5568;font-size:0.6rem;">\u2717 mechanism</span>')
    if ncv.has_timing_edge:
        flags.append('<span style="color:#00E676;font-size:0.6rem;">\u2713 timing</span>')
    if ncv.has_catalyst:
        flags.append('<span style="color:#00E676;font-size:0.6rem;">\u2713 catalyst</span>')
    flags_html = " &nbsp; ".join(flags)

    # --- Evidence section ---
    evidence_html = ""
    for ev in ncv.evidence:
        strength_bar = ""
        if hasattr(ev, "strength") and ev.strength:
            sw = int(ev.strength * 60)
            strength_bar = (
                f'<span style="display:inline-block;width:60px;height:4px;background:#1a2332;'
                f'border-radius:2px;vertical-align:middle;margin-left:6px;">'
                f'<span style="display:inline-block;width:{sw}px;height:4px;background:#00d4aa;'
                f'border-radius:2px;"></span></span>'
            )
        evidence_html += (
            f'<div class="nc-evidence-item">'
            f'<span class="nc-evidence-check">&#10003;</span>'
            f'<span class="nc-evidence-source">{ev.source}</span>'
            f'<span class="nc-evidence-text">{ev.summary[:250]}</span>'
            f'{strength_bar}'
            f'</div>'
        )

    # --- Mechanism section (collapsible) ---
    mechanism_html = ""
    supporting = [s for s in active_scenarios if s.mechanism_id in ncv.supporting_mechanisms]
    if supporting:
        mech_blocks = ""
        for sc in supporting:
            stage_class = f"stage-{sc.current_stage}" if sc.current_stage in ("early", "mid", "late", "complete") else "stage-early"
            category_display = sc.category.replace("_", " ")
            chain_html = _chain_progress_html(sc)

            watch_html = ""
            if sc.watch_items:
                watch_list = ", ".join(sc.watch_items[:4])
                watch_html = (
                    f'<div class="scenario-watch">'
                    f'<span class="scenario-watch-label">WATCH:</span> {watch_list}'
                    f'</div>'
                )

            confirm_html = ""
            if sc.confirmation_status:
                confirm_html = (
                    f'<div style="font-size:0.65rem;color:#8892a4;margin-top:2px;">'
                    f'Status: {sc.confirmation_status}</div>'
                )
            if sc.invalidation_risk:
                confirm_html += (
                    f'<div style="font-size:0.65rem;color:#FF9100;margin-top:2px;">'
                    f'Invalidation: {sc.invalidation_risk}</div>'
                )

            mech_blocks += (
                f'<div class="scenario-block">'
                f'<div class="scenario-header">'
                f'<span class="scenario-probability">{sc.probability:.0%}</span>'
                f'<span class="scenario-name">{sc.mechanism_name}</span>'
                f'<span class="scenario-category-chip">{category_display}</span>'
                f'<span class="stage-chip {stage_class}">{sc.current_stage}</span>'
                f'</div>'
                f'{chain_html}'
                f'{confirm_html}'
                f'{watch_html}'
                f'</div>'
            )

        mechanism_html = (
            f'<details style="margin-top:8px;">'
            f'<summary style="color:#8892a0;font-size:0.65rem;cursor:pointer;">'
            f'Transmission Mechanisms ({len(supporting)})</summary>'
            f'<div style="padding-top:4px;">{mech_blocks}</div>'
            f'</details>'
        )

    # --- Consensus context section (collapsible) ---
    consensus_context_html = ""
    if consensus_view:
        cv = consensus_view
        cv_dir = cv.consensus_direction.value
        coherence_class = f"coherence-{cv.consensus_coherence}"

        positioning = ""
        if cv.positioning_summary:
            positioning = (
                f'<div style="font-size:0.7rem;color:#8892a4;margin-top:4px;">'
                f'{cv.positioning_summary[:200]}</div>'
            )

        narrative = ""
        if cv.market_narrative:
            narrative = (
                f'<div style="font-size:0.7rem;color:#8892a4;margin-top:4px;">'
                f'{cv.market_narrative[:200]}</div>'
            )

        priced_html = ""
        if cv.priced_in:
            chips = "".join(f'<span class="priced-in-chip">{p}</span>' for p in cv.priced_in[:3])
            priced_html = (
                f'<div style="margin-top:4px;">'
                f'<span style="font-size:0.6rem;color:#4a5568;">PRICED IN:</span> {chips}'
                f'</div>'
            )
        if cv.not_priced_in:
            chips = "".join(f'<span class="not-priced-chip">{p}</span>' for p in cv.not_priced_in[:3])
            priced_html += (
                f'<div style="margin-top:4px;">'
                f'<span style="font-size:0.6rem;color:#FF9100;">NOT PRICED:</span> {chips}'
                f'</div>'
            )

        # Quant score components
        quant_html = ""
        if consensus_score and consensus_score.components:
            comp_items = ""
            for name, val in consensus_score.components.items():
                bar_color = "#00d4aa" if val > 0 else "#ff4444" if val < 0 else "#4a5568"
                bar_width = abs(val) * 50
                display_name = name.replace("_", " ").title()
                comp_items += (
                    f'<div style="display:flex;align-items:center;gap:6px;padding:2px 0;">'
                    f'<span style="color:#8892a0;font-size:0.6rem;width:70px;text-align:right;">{display_name}</span>'
                    f'<div style="width:80px;height:5px;background:#1a2332;border-radius:3px;position:relative;">'
                    f'<div style="position:absolute;left:50%;top:0;width:1px;height:5px;background:#4a5568;"></div>'
                    f'<div style="position:absolute;{"left" if val >= 0 else "right"}:50%;'
                    f'width:{abs(val) * 40}px;height:5px;background:{bar_color};'
                    f'border-radius:{"0 3px 3px 0" if val >= 0 else "3px 0 0 3px"};"></div>'
                    f'</div>'
                    f'<span style="color:#c0c8d0;font-size:0.6rem;">{val:+.2f}</span>'
                    f'</div>'
                )
            quant_html = f'<div style="margin-top:6px;">{comp_items}</div>'

        consensus_context_html = (
            f'<details style="margin-top:8px;">'
            f'<summary style="color:#8892a0;font-size:0.65rem;cursor:pointer;">Consensus Context</summary>'
            f'<div style="padding:6px 8px;background:#0d1117;border-radius:4px;margin-top:4px;">'
            f'<div style="display:flex;align-items:center;gap:8px;">'
            f'<span class="badge badge-{cv_dir}" style="font-size:0.55rem;">{cv_dir.upper()}</span>'
            f'<span style="color:#c0c8d0;font-size:0.7rem;">{cv.quant_score:+.2f}</span>'
            f'<span class="{coherence_class} coherence-badge">{cv.consensus_coherence}</span>'
            f'</div>'
            f'{positioning}'
            f'{narrative}'
            f'{priced_html}'
            f'{quant_html}'
            f'</div>'
            f'</details>'
        )

    # --- Catalyst & invalidation ---
    catalyst_html = ""
    if ncv.has_catalyst:
        catalyst_html = (
            f'<div style="margin-top:6px;">'
            f'<span style="font-size:0.6rem;font-weight:700;color:#00d4aa;letter-spacing:0.06em;">CATALYST:</span> '
            f'<span style="font-size:0.7rem;color:#c5c8d4;">{ncv.has_catalyst}</span>'
            f'</div>'
        )

    invalidation_html = ""
    if ncv.invalidation:
        invalidation_html = (
            f'<div style="margin-top:4px;">'
            f'<span style="font-size:0.6rem;font-weight:700;color:#FF9100;letter-spacing:0.06em;">INVALIDATION:</span> '
            f'<span style="font-size:0.7rem;color:#c5c8d4;">{ncv.invalidation[:200]}</span>'
            f'</div>'
        )

    # --- Stage badge ---
    stage_html = ""
    if ncv.mechanism_stage:
        stage_class = f"stage-{ncv.mechanism_stage}" if ncv.mechanism_stage in ("early", "mid", "late", "complete") else "stage-early"
        stage_html = f'<span class="stage-chip {stage_class}">{ncv.mechanism_stage}</span>'

    # --- Build the card ---
    card_html = (
        f'<div class="nc-view-card">'
        # Header
        f'<div class="asset-card-header">'
        f'<span class="asset-ticker">{_get_ticker_name(ncv.ticker)}</span>'
        f'<span class="asset-class-label">{ac_label}</span>'
        f'<span class="edge-badge edge-{ncv.edge_type}">{ncv.edge_type.upper()}</span>'
        f'{stage_html}'
        f'</div>'
        # Direction arrow
        f'<div style="font-size:0.7rem;color:#4a5568;margin-bottom:4px;">'
        f'Consensus: <span class="badge badge-{consensus_dir}" style="font-size:0.55rem;">{consensus_dir}</span> '
        f'&rarr; Our view: <span class="badge badge-{our_dir}" style="font-size:0.55rem;">{our_dir}</span>'
        f'</div>'
        # Thesis
        f'<div class="nc-thesis">{ncv.thesis[:500]}</div>'
        # Conviction + validity bars
        f'<div style="display:flex;gap:16px;align-items:center;margin:6px 0;">'
        f'<div style="display:flex;align-items:center;gap:4px;">'
        f'<span style="font-size:0.6rem;color:#4a5568;letter-spacing:0.06em;">CONVICTION:</span>'
        f'<span class="conviction-bar-bg">'
        f'<span class="conviction-bar-fill conviction-bar-fill-{our_dir}" style="width:{conviction_pct}%"></span></span>'
        f'<span class="conviction-label">{ncv.our_conviction:.0%}</span>'
        f'</div>'
        f'<div style="display:flex;align-items:center;gap:4px;">'
        f'<span style="font-size:0.6rem;color:#4a5568;letter-spacing:0.06em;">VALIDITY:</span>'
        f'<span class="validity-bar-bg"><span class="validity-bar-fill" style="width:{validity_pct}%"></span></span>'
        f'<span class="validity-label">{ncv.validity_score:.0%}</span>'
        f'</div>'
        f'</div>'
        # Quality flags
        f'<div style="margin:4px 0;">{flags_html}</div>'
        # Evidence
        f'<div style="font-size:0.65rem;color:#4a5568;margin:8px 0 4px 0;">'
        f'Evidence ({ncv.independent_source_count} independent sources):</div>'
        f'{evidence_html}'
        # Catalyst & invalidation
        f'{catalyst_html}'
        f'{invalidation_html}'
        # Mechanism drill-down
        f'{mechanism_html}'
        # Consensus context drill-down
        f'{consensus_context_html}'
        f'</div>'
    )
    st.markdown(card_html, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Active mechanisms summary (standalone)
# ---------------------------------------------------------------------------

def _render_mechanisms_summary(active_scenarios: list[ActiveScenario]) -> None:
    if not active_scenarios:
        return

    with st.expander(f"ACTIVE TRANSMISSION MECHANISMS ({len(active_scenarios)})", expanded=False):
        for sc in sorted(active_scenarios, key=lambda x: x.probability, reverse=True):
            stage_class = f"stage-{sc.current_stage}" if sc.current_stage in ("early", "mid", "late", "complete") else "stage-early"
            category_display = sc.category.replace("_", " ")
            chain_html = _chain_progress_html(sc)

            impacts_html = ""
            if sc.asset_impacts:
                impact_chips = " ".join(
                    f'<span class="badge badge-{imp.direction.value}" style="font-size:0.55rem;">'
                    f'{imp.ticker} {imp.direction.value}</span>'
                    for imp in sc.asset_impacts[:5]
                )
                impacts_html = f'<div style="margin-top:4px;">{impact_chips}</div>'

            watch_html = ""
            if sc.watch_items:
                watch_list = ", ".join(sc.watch_items[:4])
                watch_html = (
                    f'<div class="scenario-watch">'
                    f'<span class="scenario-watch-label">WATCH:</span> {watch_list}'
                    f'</div>'
                )

            st.markdown(
                f'<div class="scenario-block">'
                f'<div class="scenario-header">'
                f'<span class="scenario-probability">{sc.probability:.0%}</span>'
                f'<span class="scenario-name">{sc.mechanism_name}</span>'
                f'<span class="scenario-category-chip">{category_display}</span>'
                f'<span class="stage-chip {stage_class}">{sc.current_stage}</span>'
                f'</div>'
                f'{chain_html}'
                f'{impacts_html}'
                f'{watch_html}'
                f'</div>',
                unsafe_allow_html=True,
            )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def render_actionable_view(
    report: WeeklyReport | None,
    selected_assets: list[AssetClass],
) -> None:
    if not report:
        st.info("No report data yet. Run the weekly pipeline to generate your first report.")
        return

    _render_regime_banner(report)

    # Consensus context (collapsible)
    if report.consensus_views:
        _render_consensus_section(report.consensus_views, report.consensus_scores)

    # NC views — the product
    st.markdown(
        '<div class="section-header">NON-CONSENSUS VIEWS</div>',
        unsafe_allow_html=True,
    )

    # Build lookups
    cv_by_ticker: dict[str, ConsensusView] = {cv.ticker: cv for cv in report.consensus_views}
    cs_by_ticker: dict[str, ConsensusScore] = {cs.ticker: cs for cs in report.consensus_scores}

    # Filter by selected asset classes
    nc_views = [ncv for ncv in report.non_consensus_views if ncv.asset_class in selected_assets]

    if nc_views:
        for ncv in sorted(nc_views, key=lambda x: x.validity_score, reverse=True):
            _render_nc_view_card(
                ncv,
                cv_by_ticker.get(ncv.ticker),
                cs_by_ticker.get(ncv.ticker),
                report.active_scenarios,
            )
    else:
        st.markdown(
            '<div style="text-align:center;padding:40px 0;">'
            '<div style="color:#8892a4;font-size:0.85rem;font-weight:600;margin-bottom:8px;">'
            'No valid non-consensus views this week.</div>'
            '<div style="color:#4a5568;font-size:0.75rem;line-height:1.6;max-width:500px;margin:0 auto;">'
            'Our alpha signals agree with market consensus across all assets. '
            'This means either consensus is correct (no edge) or our signal coverage '
            'is insufficient to identify a disagreement. No trade is a valid position.'
            '</div></div>',
            unsafe_allow_html=True,
        )

    # Active mechanisms (informational, even without NC views)
    if report.active_scenarios:
        _render_mechanisms_summary(report.active_scenarios)
