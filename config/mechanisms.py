"""Load transmission mechanism catalog from YAML."""

import logging
from pathlib import Path

import yaml

from models.schemas import (
    AssetClass,
    ChainStep,
    MechanismAssetImpact,
    SentimentDirection,
    TransmissionMechanism,
)

logger = logging.getLogger(__name__)

MECHANISMS_PATH = Path(__file__).parent / "mechanisms.yaml"


def load_mechanisms() -> list[TransmissionMechanism]:
    """Load transmission mechanisms from YAML catalog.

    Returns empty list if the file is missing or malformed (graceful fallback).
    """
    if not MECHANISMS_PATH.exists():
        logger.warning("mechanisms.yaml not found at %s", MECHANISMS_PATH)
        return []

    try:
        with open(MECHANISMS_PATH) as f:
            data = yaml.safe_load(f)
    except Exception as e:
        logger.error("Failed to parse mechanisms.yaml: %s", e)
        return []

    raw_list = data.get("mechanisms", [])
    mechanisms: list[TransmissionMechanism] = []

    for item in raw_list:
        try:
            chain_steps = [
                ChainStep(**step) for step in item.get("chain_steps", [])
            ]
            asset_impacts = []
            for imp in item.get("asset_impacts", []):
                asset_impacts.append(
                    MechanismAssetImpact(
                        ticker=imp["ticker"],
                        asset_class=AssetClass(imp["asset_class"]),
                        direction=SentimentDirection(imp["direction"]),
                        sensitivity=imp.get("sensitivity", "medium"),
                        lag_days=imp.get("lag_days", [0, 7]),
                    )
                )

            mechanisms.append(
                TransmissionMechanism(
                    id=item["id"],
                    name=item["name"],
                    category=item["category"],
                    description=item["description"].strip(),
                    trigger_sources=item.get("trigger_sources", []),
                    trigger_keywords=item.get("trigger_keywords", []),
                    chain_steps=chain_steps,
                    asset_impacts=asset_impacts,
                    confirmation_criteria=item.get("confirmation_criteria", []),
                    invalidation_criteria=item.get("invalidation_criteria", []),
                )
            )
        except (KeyError, ValueError) as e:
            logger.warning("Skipping malformed mechanism %s: %s", item.get("id", "?"), e)
            continue

    logger.info("Loaded %d transmission mechanisms", len(mechanisms))
    return mechanisms
