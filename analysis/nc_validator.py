"""Binary validation for non-consensus views: multi-source + causal mechanism gates."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from analysis.chain_verifier import verify_chain_progression
from models.schemas import Signal

logger = logging.getLogger(__name__)


@dataclass
class NCValidation:
    """Binary validation result for a non-consensus view."""

    multi_source_pass: bool
    independent_sources: list[str] = field(default_factory=list)
    source_count: int = 0

    causal_pass: bool = False
    mechanism_id: str | None = None
    mechanism_name: str | None = None
    mechanism_stage: str | None = None
    chain_steps_fired: list[dict] = field(default_factory=list)
    chain_steps_pending: list[dict] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.multi_source_pass and self.causal_pass


def validate_nc_view(
    nc_view: dict,
    active_scenarios: list[dict],
    mechanism_catalog: list[dict],
    all_signals: list[Signal],
) -> NCValidation:
    """Validate an NC view with two binary gates."""

    evidence = nc_view.get("evidence", [])
    unique_sources = list({e.get("source", "") for e in evidence if isinstance(e, dict)})
    multi_source_pass = len(unique_sources) >= 2

    best_mechanism: dict | None = None
    for scenario in active_scenarios:
        for impact in scenario.get("asset_impacts", []):
            impact_ticker = impact.get("ticker", "") if isinstance(impact, dict) else ""
            impact_direction = impact.get("direction", "") if isinstance(impact, dict) else ""

            if (impact_ticker == nc_view.get("ticker")
                    and impact_direction == nc_view.get("our_direction")):

                mech = _find_mechanism(scenario.get("mechanism_id", ""), mechanism_catalog)
                if not mech:
                    continue

                progression = verify_chain_progression(mech, all_signals, datetime.utcnow())
                fired = progression["fired_steps"]

                if len(fired) > 0:
                    stage = progression["stage"]
                    if best_mechanism is None or len(fired) > len(best_mechanism.get("fired", [])):
                        best_mechanism = {
                            "id": scenario.get("mechanism_id", ""),
                            "name": scenario.get("mechanism_name", ""),
                            "stage": stage,
                            "fired": fired,
                            "pending": progression["pending_steps"],
                        }

    causal_pass = best_mechanism is not None

    return NCValidation(
        multi_source_pass=multi_source_pass,
        independent_sources=unique_sources,
        source_count=len(unique_sources),
        causal_pass=causal_pass,
        mechanism_id=best_mechanism["id"] if best_mechanism else None,
        mechanism_name=best_mechanism["name"] if best_mechanism else None,
        mechanism_stage=best_mechanism["stage"] if best_mechanism else None,
        chain_steps_fired=best_mechanism["fired"] if best_mechanism else [],
        chain_steps_pending=best_mechanism["pending"] if best_mechanism else [],
    )


def validate_and_filter_nc_views(
    raw_nc_views: list[dict],
    active_scenarios: list[dict],
    mechanism_catalog: list[dict],
    all_signals: list[Signal],
) -> list[tuple[dict, NCValidation]]:
    """Post-LLM validation. Only returns NC views that pass both gates."""
    signal_lookup = {s.id: s for s in all_signals}

    validated: list[tuple[dict, NCValidation]] = []
    for nc in raw_nc_views:
        real_evidence: list[dict] = []
        for ev in nc.get("evidence", []):
            if not isinstance(ev, dict):
                continue
            sid = ev.get("signal_id", "")
            if sid in signal_lookup:
                actual_signal = signal_lookup[sid]
                ev["url"] = actual_signal.url or ev.get("url", "")
                ev["source"] = actual_signal.source.value
                real_evidence.append(ev)

        nc["evidence"] = real_evidence

        scenario_dicts = [
            s.model_dump() if hasattr(s, "model_dump") else s
            for s in active_scenarios
        ]

        validation = validate_nc_view(nc, scenario_dicts, mechanism_catalog, all_signals)

        if validation.is_valid:
            validated.append((nc, validation))
        else:
            reasons: list[str] = []
            if not validation.multi_source_pass:
                reasons.append(f"only {validation.source_count} source(s)")
            if not validation.causal_pass:
                reasons.append("no active causal mechanism")
            logger.info(
                "Dropped NC view %s %s: %s",
                nc.get("ticker", "?"), nc.get("our_direction", "?"), ", ".join(reasons),
            )

    return validated


def _find_mechanism(mechanism_id: str, catalog: list[dict]) -> dict | None:
    for m in catalog:
        if m.get("id") == mechanism_id:
            return m
    return None
