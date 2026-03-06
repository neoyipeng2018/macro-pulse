"""Verify which steps in a mechanism's causal chain have observable evidence."""

from __future__ import annotations

from datetime import datetime, timedelta

from models.schemas import Signal


def verify_chain_progression(
    mechanism: dict,
    signals: list[Signal],
    current_date: datetime,
) -> dict:
    """Check which steps in a mechanism's causal chain have observable evidence."""
    chain_steps = mechanism.get("chain_steps", [])
    trigger_keywords = [kw.lower() for kw in mechanism.get("trigger_keywords", [])]

    fired: list[dict] = []
    pending: list[dict] = []

    for i, step in enumerate(chain_steps):
        observable = step.get("observable", "").lower()
        lag_days = step.get("lag_days", [0, 7])
        lag_max = lag_days[1] if len(lag_days) > 1 else 7

        step_evidence = _find_evidence_for_step(
            observable, signals, trigger_keywords, current_date,
            max_age_days=lag_max + 3,
        )

        if step_evidence:
            fired.append({
                "step": i + 1,
                "description": step.get("description", ""),
                "evidence": step_evidence,
            })
        else:
            lag_min = lag_days[0] if lag_days else 0
            pending.append({
                "step": i + 1,
                "description": step.get("description", ""),
                "expected_lag": f"{lag_min}-{lag_max} days",
            })

    total = len(chain_steps)
    fired_count = len(fired)

    if fired_count == 0:
        stage = "not_started"
    elif fired_count / total < 0.33:
        stage = "early"
    elif fired_count / total < 0.66:
        stage = "mid"
    else:
        stage = "late"

    next_obs = pending[0]["description"] if pending else "All steps fired"

    return {
        "mechanism_id": mechanism.get("id", ""),
        "total_steps": total,
        "fired_steps": fired,
        "pending_steps": pending,
        "stage": stage,
        "next_observable": next_obs,
    }


def _find_evidence_for_step(
    observable: str,
    signals: list[Signal],
    keywords: list[str],
    current_date: datetime,
    max_age_days: int,
) -> str | None:
    """Search signals for evidence that a chain step has fired."""
    cutoff = current_date - timedelta(days=max_age_days)
    observable_words = set(observable.split())

    for signal in signals:
        ts = signal.timestamp.replace(tzinfo=None) if signal.timestamp.tzinfo else signal.timestamp
        if ts < cutoff:
            continue

        signal_text = f"{signal.title} {signal.content}".lower()

        overlap = observable_words & set(signal_text.split())
        if len(overlap) >= 2 or any(kw in signal_text for kw in keywords):
            return f"[{signal.source.value}] {signal.title}"

    return None
