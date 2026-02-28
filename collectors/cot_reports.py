"""CFTC Commitment of Traders report collector."""

import hashlib
import logging
from datetime import datetime

import httpx
import pandas as pd

from collectors.base import BaseCollector
from models.schemas import Signal, SignalSource

logger = logging.getLogger(__name__)

# Key contracts to track for macro directional trading
COT_CONTRACTS = {
    "EUR": "099741",
    "GBP": "096742",
    "JPY": "097741",
    "AUD": "232741",
    "CAD": "090741",
    "CHF": "092741",
    "Gold": "088691",
    "Silver": "084691",
    "Crude Oil": "067651",
    "Natural Gas": "023651",
    "Copper": "085692",
    "S&P 500": "13874A",
    "Nasdaq 100": "20974A",
    "US 10Y Note": "043602",
    "Bitcoin": "133741",
}


class COTCollector(BaseCollector):
    """Collect CFTC Commitment of Traders positioning data."""

    source_name = "cot"

    # CFTC publishes COT data as CSV at this endpoint
    COT_URL = "https://www.cftc.gov/dea/newcot/deafut.txt"

    def collect(self) -> list[Signal]:
        signals: list[Signal] = []

        try:
            resp = httpx.get(self.COT_URL, timeout=30, follow_redirects=True)
            resp.raise_for_status()

            # Parse the fixed-width/CSV format
            lines = resp.text.strip().split("\n")
            if len(lines) < 2:
                return signals

            # COT data is comma-delimited with header row
            header = [h.strip().strip('"') for h in lines[0].split(",")]
            for line in lines[1:]:
                fields = [f.strip().strip('"') for f in line.split(",")]
                if len(fields) < len(header):
                    continue

                row = dict(zip(header, fields))
                contract_name = row.get("Market_and_Exchange_Names", "")
                cftc_code = row.get("CFTC_Contract_Market_Code", "")

                # Match to our tracked contracts
                matched_name = None
                for name, code in COT_CONTRACTS.items():
                    if code == cftc_code or name.lower() in contract_name.lower():
                        matched_name = name
                        break

                if not matched_name:
                    continue

                try:
                    long_spec = int(row.get("NonComm_Positions_Long_All", 0))
                    short_spec = int(row.get("NonComm_Positions_Short_All", 0))
                    net_spec = long_spec - short_spec

                    long_change = int(row.get("Change_in_NonComm_Long_All", 0))
                    short_change = int(row.get("Change_in_NonComm_Short_All", 0))
                    net_change = long_change - short_change

                    direction = "net long" if net_spec > 0 else "net short"
                    change_dir = "adding longs" if net_change > 0 else "adding shorts"

                    sig_id = hashlib.md5(
                        f"cot_{matched_name}_{datetime.utcnow().date()}".encode()
                    ).hexdigest()[:12]

                    signals.append(
                        Signal(
                            id=sig_id,
                            source=SignalSource.COT,
                            title=f"COT {matched_name}: specs {direction} ({net_spec:+,}), {change_dir} ({net_change:+,})",
                            content=(
                                f"CFTC Commitment of Traders for {matched_name}: "
                                f"Non-commercial net position: {net_spec:+,} contracts. "
                                f"Weekly change: {net_change:+,} contracts. "
                                f"Longs: {long_spec:,}, Shorts: {short_spec:,}."
                            ),
                            timestamp=datetime.utcnow(),
                            metadata={
                                "contract": matched_name,
                                "net_speculative": net_spec,
                                "net_change": net_change,
                                "long_spec": long_spec,
                                "short_spec": short_spec,
                            },
                        )
                    )
                except (ValueError, KeyError):
                    continue

        except Exception as e:
            logger.warning("Error fetching COT data: %s", e)

        return signals
