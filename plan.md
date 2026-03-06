# Macro-Pulse v2: Simplified Crypto Regime & Direction System

## Executive Summary

Redesign macro-pulse from a general macro system into a **focused crypto regime + 1-week direction engine** for BTC and ETH. The current system has friction points: dual signal collection, 5 LLM calls per run, disabled collectors cluttering the codebase, and source enum mismatches. This plan simplifies the pipeline to a **single collection pass → 3 LLM calls**, expands the data universe with social sentiment from Agent-Reach and on-chain data from mempool.space, and validates every directional thesis through causal crypto/macro transmission mechanisms.

**Target output**: A single weekly report answering three questions:
1. **What regime are we in?** (risk_on, risk_off, reflation, stagflation, goldilocks, transition)
2. **Where does consensus say BTC and ETH are going in 1 week?**
3. **What non-consensus signals disagree, and do causal mechanisms support them?**

---

## 1. Current Problems & What Changes

### 1.1 Flow Friction (Fix)

| Problem | Current | Proposed |
|---------|---------|----------|
| Dual collection | Same sources collected twice (Phase 1 + Phase 2) | **Single pass**, then classify signals by role |
| LLM calls | 5 per run (consensus, mechanisms, regime, NC discovery, summary) | **3 per run** (consensus+regime, NC+mechanisms, summary) |
| Legacy code | `run_pipeline_legacy()` + unused scoring modules | **Delete** legacy pipeline, old scorers, dead code |
| Source mismatches | RedditCollector uses `SOCIAL` enum but role checks for `"reddit"` | **Fix** enum→role mapping |
| Disabled collectors | 5 collectors commented out, cluttering imports | **Remove** disabled ones from main registry, keep as opt-in |

### 1.2 Missing Data (Add)

| Gap | Current | Proposed Source |
|-----|---------|-----------------|
| Crypto Twitter sentiment | None | **xreach CLI** (Agent-Reach) — free, cookie-auth |
| YouTube crypto analysis | None | **yt-dlp** (Agent-Reach) — transcript extraction |
| Semantic news search | RSS only (CoinTelegraph, CoinDesk) | **Exa AI** — semantic search for breaking crypto news |
| BTC on-chain (fees, hashrate) | Only stablecoin supply via DeFi Llama | **mempool.space** — fees, hashrate, difficulty, UTXO |
| ETH on-chain (gas, staking) | None | **Beacon chain API + ultrasound.money** — gas, burn, staking flows |
| Macro rates context | FRED disabled | **Re-enable FRED** — Fed Funds, yield curve, breakevens, financial stress |
| Exchange flows | None | **CryptoQuant free tier** or **Arkham Intelligence** — exchange net flows |

### 1.3 Analytical Gaps (Strengthen)

| Gap | Current | Proposed |
|-----|---------|----------|
| Direction horizon | Implicit "1 week" | **Explicit 7-day price target ranges** per asset |
| Causal validation | LLM matches signals to mechanisms | **Chain-step verification**: check if prior steps in the causal chain have fired |
| Regime confidence | Single LLM confidence score | **Multi-signal regime voting**: quant indicators vote on regime independently |
| NC validation | ≥2 independent sources | **Add causal gate**: NC view must map to ≥1 active transmission mechanism |

---

## 2. New Pipeline Architecture

### 2.1 Overview

```
                    ┌──────────────────────────────┐
                    │     COLLECT (single pass)     │
                    │  all sources → Signal[]       │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │     CLASSIFY                  │
                    │  signal_roles → consensus[]   │
                    │                  alpha[]       │
                    └──────────────┬───────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                     ▼
    ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
    │ LLM CALL 1      │  │ QUANT SCORING   │  │ STALENESS       │
    │ Consensus +     │  │ 6-component     │  │ FILTER          │
    │ Regime          │  │ equal-weight    │  │ alpha signals   │
    └────────┬────────┘  └────────┬────────┘  └────────┬────────┘
             │                    │                     │
             └────────────────────┼─────────────────────┘
                                  │
                    ┌─────────────▼────────────────┐
                    │     LLM CALL 2               │
                    │  NC Discovery + Mechanism    │
                    │  Matching (merged)           │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │     LLM CALL 3               │
                    │  Summary + Direction         │
                    │  Targets (7-day ranges)      │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │     OUTPUT                    │
                    │  WeeklyReport → DB/Sheets/UI │
                    └──────────────────────────────┘
```

### 2.2 Single Collection Pass

Replace `collect_signals_by_role()` (which collects twice) with a single pass:

```python
# run_weekly.py — new collect_all_signals()

def collect_all_signals(sources: list[str] | None = None) -> dict[str, list[Signal]]:
    """Single collection pass. Returns signals classified by role."""
    from config.signal_roles import CONSENSUS_SOURCES, ALPHA_SOURCES

    # Collect everything once
    all_signals = collect_signals(sources)
    consensus_sigs = collect_consensus_signals()
    all_signals.extend(consensus_sigs)

    # Classify by role (some signals are dual-role)
    consensus = [s for s in all_signals if s.source.value in CONSENSUS_SOURCES
                 or s.source.value in {"options", "derivatives_consensus", "etf_flows"}]
    alpha = filter_stale_signals(
        [s for s in all_signals if s.source.value in ALPHA_SOURCES]
    )

    return {
        "all": all_signals,
        "consensus": consensus,
        "alpha": alpha,
    }
```

### 2.3 Merged LLM Calls

**LLM Call 1: Consensus + Regime** (merge `consensus_synthesizer` + `regime_classifier`)

```python
# ai/chains/consensus_regime.py

CONSENSUS_REGIME_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a macro strategist at a crypto-native hedge fund.
Today is {today}. Analyze the consensus picture and classify the current regime.

QUANT CONSENSUS SCORES:
{quant_scores}

POSITIONING DATA:
{positioning_signals}

NARRATIVE SIGNALS:
{narrative_signals}

MARKET DATA:
{market_data}

Return JSON:
{{
  "regime": "risk_on|risk_off|reflation|stagflation|goldilocks|transition",
  "regime_confidence": 0.0-1.0,
  "regime_rationale": "2-3 sentences",
  "consensus_views": [
    {{
      "ticker": "Bitcoin",
      "consensus_direction": "bullish|bearish|neutral",
      "quant_score": -1.0 to 1.0,
      "positioning_summary": "what derivatives/flows say",
      "narrative_summary": "what news/social says",
      "consensus_coherence": "strong|moderate|weak|conflicted",
      "consensus_confidence": 0.0-1.0,
      "priced_in": ["what market has absorbed"],
      "not_priced_in": ["what market hasn't absorbed"],
      "key_levels": {{"support": 0, "resistance": 0}},
      "one_week_consensus_range": {{"low": 0, "high": 0}}
    }}
  ]
}}"""),
    ("human", "Analyze consensus and regime now."),
])


async def synthesize_consensus_and_regime(
    quant_scores, positioning_signals, narrative_signals, market_signals, llm
):
    """Single LLM call: consensus views + regime classification."""
    chain = CONSENSUS_REGIME_PROMPT | llm | JsonOutputParser()
    result = await chain.ainvoke({
        "today": datetime.utcnow().strftime("%Y-%m-%d"),
        "quant_scores": format_quant_scores(quant_scores),
        "positioning_signals": format_signals(positioning_signals),
        "narrative_signals": format_signals(narrative_signals),
        "market_data": format_signals(market_signals),
    })
    return result
```

**LLM Call 2: NC Discovery + Mechanism Matching** (merge `non_consensus_discoverer` + `mechanism_matcher`)

```python
# ai/chains/nc_mechanisms.py

NC_MECHANISMS_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a non-consensus analyst. Today is {today}.

ESTABLISHED CONSENSUS:
{consensus_views}

CURRENT REGIME: {regime} (confidence: {regime_confidence})

ALPHA SIGNALS (may disagree with consensus):
{alpha_signals}

TRANSMISSION MECHANISM CATALOG:
{mechanisms_catalog}

Your job:
1. Find where alpha signals DISAGREE with consensus
2. For each disagreement, identify which transmission mechanism supports the non-consensus view
3. Check if earlier steps in the mechanism's causal chain have already fired
4. Only output NC views that have ≥2 independent sources AND ≥1 active mechanism

Return JSON:
{{
  "non_consensus_views": [
    {{
      "ticker": "Bitcoin",
      "consensus_direction": "bullish|bearish|neutral",
      "our_direction": "bullish|bearish|neutral",
      "edge_type": "contrarian|more_aggressive|more_passive|aligned",
      "thesis": "2-3 sentence thesis",
      "evidence": [
        {{"signal_id": "...", "source": "...", "strength": "strong|moderate|weak"}}
      ],
      "independent_source_count": 0,
      "validity_score": 0.0-1.0,
      "mechanism_id": "fed_dovish_pivot",
      "mechanism_stage": "early|mid|late",
      "chain_steps_fired": ["step 1 description", "step 2 description"],
      "chain_steps_pending": ["step 3 description"],
      "one_week_nc_range": {{"low": 0, "high": 0}}
    }}
  ],
  "active_scenarios": [
    {{
      "mechanism_id": "...",
      "mechanism_name": "...",
      "category": "...",
      "probability": 0.0-1.0,
      "current_stage": "early|mid|late",
      "trigger_signals": ["signal_id_1", "signal_id_2"],
      "asset_impacts": [{{"ticker": "...", "direction": "...", "sensitivity": "..."}}],
      "watch_items": ["what to monitor next"]
    }}
  ]
}}"""),
    ("human", "Discover non-consensus views and match mechanisms now."),
])
```

**LLM Call 3: Summary + Direction Synthesis**

```python
# ai/chains/summary.py

SUMMARY_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are writing the weekly macro-pulse brief. Today is {today}.

REGIME: {regime}
CONSENSUS VIEWS: {consensus_views}
NON-CONSENSUS VIEWS: {nc_views}
ACTIVE MECHANISMS: {active_scenarios}

Write a 3-5 sentence executive summary covering:
1. Current regime and why
2. Consensus direction for BTC and ETH (with 1-week price ranges)
3. The strongest non-consensus signal and its causal mechanism
4. What to watch this week

Also produce explicit 1-week direction calls:

Return JSON:
{{
  "summary": "3-5 sentence executive summary",
  "direction_calls": [
    {{
      "ticker": "Bitcoin",
      "consensus_range": {{"low": 0, "high": 0}},
      "nc_range": {{"low": 0, "high": 0}},
      "primary_catalyst": "what drives the move",
      "risk_event": "what could invalidate"
    }}
  ]
}}"""),
    ("human", "Generate the weekly summary and direction calls."),
])
```

---

## 3. New Data Sources

### 3.1 Twitter/X Crypto Sentiment (via Agent-Reach xreach)

**Why**: Crypto Twitter is the fastest sentiment signal — narratives form on CT hours before they hit news. Currently missing entirely.

**How**: Use Agent-Reach's `xreach` CLI to scrape crypto influencer tweets without API fees.

```python
# collectors/twitter_crypto.py

import subprocess
import json
from collectors.base import BaseCollector
from models.schemas import Signal, SignalSource

class TwitterCryptoCollector(BaseCollector):
    """Collect crypto sentiment from Twitter/X via xreach CLI (Agent-Reach)."""

    # Crypto influencers + analysts to track
    ACCOUNTS = [
        "100trillionUSD",   # PlanB (S2F model)
        "CryptoHayes",      # Arthur Hayes
        "zaborow",          # Will Clemente (on-chain)
        "CryptoCred",       # Technical analysis
        "inversebrah",      # Derivatives/funding
        "EmberCN",          # On-chain whale tracking
        "DegenSpartan",     # DeFi/sentiment
        "CryptoCapo_",      # Contrarian calls
    ]

    # Keyword searches for market-moving tweets
    SEARCHES = [
        "bitcoin liquidation",
        "ETH unlock",
        "crypto regulation",
        "FOMC crypto",
        "bitcoin whale",
        "stablecoin mint",
    ]

    def collect(self) -> list[Signal]:
        signals = []

        # Collect from tracked accounts
        for account in self.ACCOUNTS:
            try:
                result = subprocess.run(
                    ["xreach", "twitter", "user-tweets", account, "--limit", "10"],
                    capture_output=True, text=True, timeout=30,
                )
                if result.returncode == 0:
                    tweets = json.loads(result.stdout)
                    for tweet in tweets:
                        signals.append(self._tweet_to_signal(tweet, account))
            except Exception as e:
                logger.warning("xreach failed for @%s: %s", account, e)

        # Collect from keyword searches
        for query in self.SEARCHES:
            try:
                result = subprocess.run(
                    ["xreach", "twitter", "search", query, "--limit", "20"],
                    capture_output=True, text=True, timeout=30,
                )
                if result.returncode == 0:
                    tweets = json.loads(result.stdout)
                    for tweet in tweets:
                        signals.append(self._tweet_to_signal(tweet, f"search:{query}"))
            except Exception as e:
                logger.warning("xreach search failed for '%s': %s", query, e)

        return signals

    def _tweet_to_signal(self, tweet: dict, source_label: str) -> Signal:
        return Signal(
            id=self._make_id(tweet.get("id", "")),
            source=SignalSource.SOCIAL,
            title=f"@{tweet.get('author', source_label)}: {tweet.get('text', '')[:80]}",
            content=tweet.get("text", ""),
            url=tweet.get("url", ""),
            timestamp=self._parse_timestamp(tweet.get("created_at", "")),
            metadata={
                "platform": "twitter",
                "author": tweet.get("author", ""),
                "likes": tweet.get("likes", 0),
                "retweets": tweet.get("retweets", 0),
                "replies": tweet.get("replies", 0),
                "engagement_score": self._engagement_score(tweet),
                "source_label": source_label,
            },
        )

    @staticmethod
    def _engagement_score(tweet: dict) -> float:
        """Weighted engagement: retweets matter more than likes."""
        return (
            tweet.get("retweets", 0) * 3
            + tweet.get("likes", 0)
            + tweet.get("replies", 0) * 2
        )
```

### 3.2 YouTube Crypto Analysis (via Agent-Reach yt-dlp)

**Why**: Long-form crypto analysis on YouTube (Coin Bureau, Benjamin Cowen, DataDash) provides thesis-level sentiment not captured by headlines.

```python
# collectors/youtube_crypto.py

import subprocess
import json
from collectors.base import BaseCollector
from models.schemas import Signal, SignalSource

class YouTubeCryptoCollector(BaseCollector):
    """Extract recent crypto analysis transcripts from YouTube via yt-dlp."""

    CHANNELS = [
        "UCqK_GSMbpiV8spgD3ZGloSw",  # Coin Bureau
        "UCRvqjQPSeaWn-uEx-w0XOIg",  # Benjamin Cowen
        "UCCatR7nWbYrkVXdxXb4cGXg",  # DataDash
        "UCVBhyBR41ckEBcJfMc_MkbQ",  # Real Vision Crypto
    ]

    def collect(self) -> list[Signal]:
        signals = []
        for channel_id in self.CHANNELS:
            try:
                # Get latest video metadata + auto-generated subtitles
                result = subprocess.run(
                    [
                        "yt-dlp",
                        f"https://www.youtube.com/channel/{channel_id}/videos",
                        "--flat-playlist",
                        "--playlist-end", "3",          # last 3 videos
                        "--write-auto-sub",
                        "--sub-lang", "en",
                        "--skip-download",
                        "--print-json",
                    ],
                    capture_output=True, text=True, timeout=60,
                )
                if result.returncode == 0:
                    for line in result.stdout.strip().split("\n"):
                        if line.strip():
                            video = json.loads(line)
                            sig = self._video_to_signal(video)
                            if sig:
                                signals.append(sig)
            except Exception as e:
                logger.warning("yt-dlp failed for channel %s: %s", channel_id, e)

        return signals

    def _video_to_signal(self, video: dict) -> Signal | None:
        title = video.get("title", "")
        # Only keep videos with crypto-relevant titles
        crypto_keywords = ["bitcoin", "btc", "ethereum", "eth", "crypto", "defi",
                          "altcoin", "bull", "bear", "fed", "rate", "macro"]
        if not any(kw in title.lower() for kw in crypto_keywords):
            return None

        description = video.get("description", "")[:2000]
        # Transcript would be in subtitles file — extract key sentences
        transcript = video.get("subtitles", {}).get("en", [{}])[0].get("data", "")

        return Signal(
            id=self._make_id(video.get("id", "")),
            source=SignalSource.SOCIAL,
            title=f"[YouTube] {title}",
            content=f"{title}\n\n{description[:500]}\n\nTranscript excerpt: {transcript[:1000]}",
            url=f"https://youtube.com/watch?v={video.get('id', '')}",
            timestamp=self._parse_timestamp(video.get("upload_date", "")),
            metadata={
                "platform": "youtube",
                "channel": video.get("channel", ""),
                "view_count": video.get("view_count", 0),
                "duration": video.get("duration", 0),
            },
        )
```

### 3.3 Exa Semantic Search (via Agent-Reach mcporter)

**Why**: RSS feeds only capture 2 sources (CoinTelegraph, CoinDesk). Exa's semantic search finds breaking news across the entire web, catching stories RSS misses.

```python
# collectors/exa_news.py

import subprocess
import json
from datetime import datetime, timedelta
from collectors.base import BaseCollector
from models.schemas import Signal, SignalSource

class ExaNewsCollector(BaseCollector):
    """Semantic search for breaking crypto/macro news via Exa (Agent-Reach mcporter)."""

    QUERIES = [
        "bitcoin price analysis this week",
        "ethereum market outlook",
        "crypto regulatory news",
        "federal reserve impact on crypto",
        "bitcoin whale accumulation",
        "crypto derivatives liquidation",
        "stablecoin flows depegging risk",
    ]

    def collect(self) -> list[Signal]:
        signals = []
        since = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")

        for query in self.QUERIES:
            try:
                result = subprocess.run(
                    [
                        "mcporter", "call",
                        f"exa.search(query='{query}', "
                        f"startPublishedDate='{since}', "
                        f"numResults=5, type='auto')",
                    ],
                    capture_output=True, text=True, timeout=30,
                )
                if result.returncode == 0:
                    results = json.loads(result.stdout)
                    for item in results.get("results", []):
                        signals.append(Signal(
                            id=self._make_id(item.get("url", query)),
                            source=SignalSource.NEWS,
                            title=item.get("title", query),
                            content=item.get("text", item.get("highlight", ""))[:2000],
                            url=item.get("url", ""),
                            timestamp=self._parse_timestamp(
                                item.get("publishedDate", datetime.utcnow().isoformat())
                            ),
                            metadata={
                                "search_query": query,
                                "exa_score": item.get("score", 0),
                                "domain": item.get("url", "").split("/")[2] if item.get("url") else "",
                            },
                        ))
            except Exception as e:
                logger.warning("Exa search failed for '%s': %s", query, e)

        return signals
```

### 3.4 mempool.space — Bitcoin On-Chain (Fees, Hashrate, Difficulty)

**Why**: Bitcoin network health signals (hashrate, difficulty, fee pressure) are leading indicators of miner capitulation/accumulation and network demand. Currently missing entirely.

```python
# collectors/mempool.py

import httpx
import logging
from datetime import datetime
from collectors.base import BaseCollector
from models.schemas import Signal, SignalSource

logger = logging.getLogger(__name__)

MEMPOOL_BASE = "https://mempool.space/api/v1"

class MempoolCollector(BaseCollector):
    """Bitcoin on-chain data from mempool.space (free, no auth)."""

    def collect(self) -> list[Signal]:
        signals = []
        client = httpx.Client(timeout=15)

        # 1. Difficulty adjustment
        try:
            resp = client.get(f"{MEMPOOL_BASE}/difficulty-adjustment")
            data = resp.json()
            signals.append(Signal(
                id=self._make_id("difficulty_adjustment"),
                source=SignalSource.ON_CHAIN,
                title=f"BTC Difficulty Adjustment: {data['difficultyChange']:+.2f}%",
                content=(
                    f"Progress: {data['progressPercent']:.1f}% through epoch. "
                    f"Estimated adjustment: {data['difficultyChange']:+.2f}%. "
                    f"Remaining blocks: {data['remainingBlocks']}. "
                    f"Time ahead/behind: {data['timeAvg'] / 600000 - 1:.1%}."
                ),
                timestamp=datetime.utcnow(),
                metadata={
                    "metric": "difficulty_adjustment",
                    "difficulty_change_pct": data["difficultyChange"],
                    "progress_pct": data["progressPercent"],
                    "remaining_blocks": data["remainingBlocks"],
                    "estimated_retarget": data.get("estimatedRetargetDate"),
                    "asset_class": "crypto",
                    "symbol": "BTC",
                },
            ))
        except Exception as e:
            logger.warning("mempool difficulty failed: %s", e)

        # 2. Hashrate (weekly average)
        try:
            resp = client.get(f"{MEMPOOL_BASE}/mining/hashrate/1w")
            data = resp.json()
            if data.get("hashrates"):
                latest = data["hashrates"][-1]
                prev = data["hashrates"][-2] if len(data["hashrates"]) > 1 else latest
                hr_change = (latest["avgHashrate"] - prev["avgHashrate"]) / prev["avgHashrate"]

                signals.append(Signal(
                    id=self._make_id("hashrate_weekly"),
                    source=SignalSource.ON_CHAIN,
                    title=f"BTC Hashrate: {latest['avgHashrate'] / 1e18:.1f} EH/s ({hr_change:+.1%} WoW)",
                    content=(
                        f"Weekly average hashrate: {latest['avgHashrate'] / 1e18:.1f} EH/s. "
                        f"Change: {hr_change:+.2%} week-over-week. "
                        f"{'Rising hashrate = miner confidence.' if hr_change > 0 else 'Falling hashrate = potential miner capitulation.'}"
                    ),
                    timestamp=datetime.utcnow(),
                    metadata={
                        "metric": "hashrate",
                        "hashrate_eh": latest["avgHashrate"] / 1e18,
                        "hashrate_change_pct": hr_change * 100,
                        "asset_class": "crypto",
                        "symbol": "BTC",
                    },
                ))
        except Exception as e:
            logger.warning("mempool hashrate failed: %s", e)

        # 3. Recommended fees (demand proxy)
        try:
            resp = client.get("https://mempool.space/api/v1/fees/recommended")
            data = resp.json()
            signals.append(Signal(
                id=self._make_id("fees_recommended"),
                source=SignalSource.ON_CHAIN,
                title=f"BTC Fees: {data['fastestFee']} sat/vB (fast), {data['hourFee']} sat/vB (hour)",
                content=(
                    f"Fastest: {data['fastestFee']} sat/vB. "
                    f"Half-hour: {data['halfHourFee']} sat/vB. "
                    f"Hour: {data['hourFee']} sat/vB. "
                    f"Economy: {data['economyFee']} sat/vB. "
                    f"{'High fees = high demand for block space.' if data['fastestFee'] > 50 else 'Low fees = subdued on-chain activity.'}"
                ),
                timestamp=datetime.utcnow(),
                metadata={
                    "metric": "fees",
                    "fastest_fee": data["fastestFee"],
                    "half_hour_fee": data["halfHourFee"],
                    "hour_fee": data["hourFee"],
                    "economy_fee": data["economyFee"],
                    "asset_class": "crypto",
                    "symbol": "BTC",
                },
            ))
        except Exception as e:
            logger.warning("mempool fees failed: %s", e)

        # 4. Mining pool distribution (centralization risk)
        try:
            resp = client.get(f"{MEMPOOL_BASE}/mining/pools/1w")
            data = resp.json()
            if data.get("pools"):
                top3 = sorted(data["pools"], key=lambda p: p["blockCount"], reverse=True)[:3]
                total_blocks = sum(p["blockCount"] for p in data["pools"])
                top3_share = sum(p["blockCount"] for p in top3) / total_blocks if total_blocks else 0

                signals.append(Signal(
                    id=self._make_id("mining_pools"),
                    source=SignalSource.ON_CHAIN,
                    title=f"BTC Mining: Top 3 pools control {top3_share:.0%} of hashrate",
                    content=(
                        f"Top 3 pools: {', '.join(p['name'] + f' ({p[\"blockCount\"]/total_blocks:.0%})' for p in top3)}. "
                        f"Total blocks this week: {total_blocks}."
                    ),
                    timestamp=datetime.utcnow(),
                    metadata={
                        "metric": "mining_pools",
                        "top3_share_pct": top3_share * 100,
                        "total_blocks": total_blocks,
                        "asset_class": "crypto",
                        "symbol": "BTC",
                    },
                ))
        except Exception as e:
            logger.warning("mempool mining pools failed: %s", e)

        client.close()
        return signals
```

### 3.5 FRED Macro Context (Re-enable)

**Why**: Crypto doesn't trade in a vacuum. Real yields, financial stress, and yield curve shape are the macro transmission channels. Currently disabled.

```python
# collectors/economic_data.py — already exists, just needs re-enabling

# In config/sources.yaml, uncomment:
enabled_collectors:
  - news
  - reddit
  - fear_greed
  - market_data
  - spreads
  # - google_trends  # REMOVE: unreliable rate limits
  - funding_rates
  - onchain
  - economic_data    # RE-ENABLE
  - mempool          # NEW
  - twitter_crypto   # NEW (requires xreach installed)
  - youtube_crypto   # NEW (requires yt-dlp installed)
  - exa_news         # NEW (requires mcporter installed)

# Trimmed FRED series for crypto relevance:
fred_series:
  - id: DFF
    name: Federal Funds Rate
  - id: T10Y2Y
    name: 10Y-2Y Treasury Spread      # yield curve
  - id: T10YIE
    name: 10Y Breakeven Inflation      # inflation expectations
  - id: STLFSI2
    name: Financial Stress Index       # stress → risk-off → crypto down
  - id: BAMLH0A0HYM2
    name: HY OAS Spread                # credit stress → risk-off
  - id: DGS2
    name: 2Y Treasury Yield            # rate expectations
```

### 3.6 Ethereum On-Chain (Beacon Chain + Ultrasound.money)

**Why**: ETH has unique supply dynamics (burn, staking, unlocks) that drive its price independently of BTC.

```python
# collectors/eth_onchain.py

import httpx
import logging
from datetime import datetime
from collectors.base import BaseCollector
from models.schemas import Signal, SignalSource

logger = logging.getLogger(__name__)

class EthOnChainCollector(BaseCollector):
    """ETH-specific on-chain data: gas, burn rate, staking flows."""

    def collect(self) -> list[Signal]:
        signals = []
        client = httpx.Client(timeout=15)

        # 1. Ultrasound.money supply data (burn rate, issuance)
        try:
            resp = client.get("https://ultrasound.money/api/v2/fees/eth-burn-total")
            data = resp.json()
            # Alternative: use beaconcha.in API for validator stats
            # resp = client.get("https://beaconcha.in/api/v1/epoch/latest")
        except Exception as e:
            logger.warning("ETH on-chain ultrasound failed: %s", e)

        # 2. Gas prices via public RPC
        try:
            resp = client.post(
                "https://eth.llamarpc.com",  # free public RPC
                json={"jsonrpc": "2.0", "method": "eth_gasPrice", "params": [], "id": 1},
            )
            data = resp.json()
            gas_gwei = int(data["result"], 16) / 1e9
            signals.append(Signal(
                id=self._make_id("eth_gas"),
                source=SignalSource.ON_CHAIN,
                title=f"ETH Gas: {gas_gwei:.1f} gwei",
                content=(
                    f"Current gas price: {gas_gwei:.1f} gwei. "
                    f"{'High gas = strong on-chain demand.' if gas_gwei > 30 else 'Low gas = subdued activity.'}"
                ),
                timestamp=datetime.utcnow(),
                metadata={
                    "metric": "gas_price",
                    "gas_gwei": gas_gwei,
                    "asset_class": "crypto",
                    "symbol": "ETH",
                },
            ))
        except Exception as e:
            logger.warning("ETH gas price failed: %s", e)

        # 3. DeFi Llama ETH TVL (already partially in onchain collector)
        try:
            resp = client.get("https://api.llama.fi/v2/historicalChainTvl/Ethereum")
            data = resp.json()
            if len(data) >= 7:
                current_tvl = data[-1]["tvl"]
                week_ago_tvl = data[-7]["tvl"]
                tvl_change = (current_tvl - week_ago_tvl) / week_ago_tvl

                signals.append(Signal(
                    id=self._make_id("eth_tvl"),
                    source=SignalSource.ON_CHAIN,
                    title=f"ETH DeFi TVL: ${current_tvl/1e9:.1f}B ({tvl_change:+.1%} WoW)",
                    content=(
                        f"Ethereum DeFi TVL: ${current_tvl/1e9:.1f}B. "
                        f"7-day change: {tvl_change:+.2%}. "
                        f"{'TVL growing = capital inflow.' if tvl_change > 0 else 'TVL shrinking = capital outflow.'}"
                    ),
                    timestamp=datetime.utcnow(),
                    metadata={
                        "metric": "defi_tvl",
                        "tvl_usd": current_tvl,
                        "tvl_change_7d_pct": tvl_change * 100,
                        "asset_class": "crypto",
                        "symbol": "ETH",
                    },
                ))
        except Exception as e:
            logger.warning("ETH TVL failed: %s", e)

        client.close()
        return signals
```

---

## 4. Regime Determination: Multi-Signal Voting

### 4.1 Current Approach (Problem)

Regime is classified by a single LLM call reading consensus views + scenarios. This is opaque and hard to validate.

### 4.2 Proposed: Quant Regime Voting + LLM Tiebreaker

Add a **quantitative regime pre-score** before the LLM sees the data. Each indicator votes on regime:

```python
# analysis/regime_voter.py

from dataclasses import dataclass

@dataclass
class RegimeVote:
    indicator: str
    regime: str
    confidence: float
    rationale: str

def compute_regime_votes(signals: list, quant_scores: list) -> list[RegimeVote]:
    """Each indicator independently votes on the current regime."""
    votes = []

    # 1. VIX level → risk regime
    vix = _extract_vix(signals)
    if vix is not None:
        if vix > 30:
            votes.append(RegimeVote("VIX", "risk_off", 0.8, f"VIX at {vix:.0f} = elevated fear"))
        elif vix > 20:
            votes.append(RegimeVote("VIX", "transition", 0.5, f"VIX at {vix:.0f} = cautious"))
        else:
            votes.append(RegimeVote("VIX", "risk_on", 0.7, f"VIX at {vix:.0f} = complacent"))

    # 2. Yield curve (T10Y2Y) → growth expectations
    t10y2y = _extract_fred("T10Y2Y", signals)
    if t10y2y is not None:
        if t10y2y < -0.5:
            votes.append(RegimeVote("Yield Curve", "risk_off", 0.7, f"10Y-2Y at {t10y2y:.2f}bp = deeply inverted"))
        elif t10y2y < 0:
            votes.append(RegimeVote("Yield Curve", "transition", 0.5, f"10Y-2Y at {t10y2y:.2f}bp = inverted"))
        else:
            votes.append(RegimeVote("Yield Curve", "goldilocks", 0.5, f"10Y-2Y at {t10y2y:.2f}bp = normal"))

    # 3. Financial Stress Index → systemic risk
    stress = _extract_fred("STLFSI2", signals)
    if stress is not None:
        if stress > 1.5:
            votes.append(RegimeVote("Fin Stress", "risk_off", 0.9, f"St. Louis FSI at {stress:.2f} = severe stress"))
        elif stress > 0.5:
            votes.append(RegimeVote("Fin Stress", "transition", 0.6, f"FSI at {stress:.2f} = elevated"))
        elif stress < -0.5:
            votes.append(RegimeVote("Fin Stress", "risk_on", 0.6, f"FSI at {stress:.2f} = benign"))

    # 4. HY OAS → credit conditions
    hy_oas = _extract_fred("BAMLH0A0HYM2", signals)
    if hy_oas is not None:
        if hy_oas > 500:
            votes.append(RegimeVote("Credit", "risk_off", 0.8, f"HY OAS at {hy_oas:.0f}bp = distressed"))
        elif hy_oas > 400:
            votes.append(RegimeVote("Credit", "transition", 0.5, f"HY OAS at {hy_oas:.0f}bp = wide"))
        else:
            votes.append(RegimeVote("Credit", "risk_on", 0.5, f"HY OAS at {hy_oas:.0f}bp = tight"))

    # 5. BTC funding rate → crypto-specific sentiment
    for qs in quant_scores:
        if qs.ticker == "Bitcoin":
            funding = qs.funding_rate_7d
            if funding > 0.05:
                votes.append(RegimeVote("BTC Funding", "risk_on", 0.6, f"7d funding {funding:.4f} = euphoric longs"))
            elif funding < -0.03:
                votes.append(RegimeVote("BTC Funding", "risk_off", 0.6, f"7d funding {funding:.4f} = capitulation"))

    # 6. DXY → dollar regime
    dxy_ret = _extract_weekly_return("DX-Y.NYB", signals)
    if dxy_ret is not None:
        if dxy_ret > 1.0:
            votes.append(RegimeVote("DXY", "risk_off", 0.5, f"DXY up {dxy_ret:.1f}% = USD strength"))
        elif dxy_ret < -1.0:
            votes.append(RegimeVote("DXY", "reflation", 0.4, f"DXY down {dxy_ret:.1f}% = USD weakness"))

    # 7. Breakeven inflation → inflation regime
    t10yie = _extract_fred("T10YIE", signals)
    if t10yie is not None:
        if t10yie > 2.8:
            votes.append(RegimeVote("Breakevens", "reflation", 0.5, f"10Y BE at {t10yie:.2f}% = rising inflation expectations"))
        elif t10yie < 2.0:
            votes.append(RegimeVote("Breakevens", "goldilocks", 0.4, f"10Y BE at {t10yie:.2f}% = well-anchored"))

    return votes


def tally_regime_votes(votes: list[RegimeVote]) -> tuple[str, float, str]:
    """Tally votes into a regime pre-score. Returns (regime, confidence, rationale)."""
    if not votes:
        return "transition", 0.3, "Insufficient data for regime classification"

    # Weighted vote count
    regime_scores = {}
    for v in votes:
        regime_scores[v.regime] = regime_scores.get(v.regime, 0.0) + v.confidence

    # Winner
    winner = max(regime_scores, key=regime_scores.get)
    total = sum(regime_scores.values())
    confidence = regime_scores[winner] / total if total > 0 else 0.3

    # Build rationale from winning votes
    supporting = [v for v in votes if v.regime == winner]
    rationale = "; ".join(v.rationale for v in supporting[:3])

    return winner, round(confidence, 2), rationale
```

The LLM then receives the quant regime pre-score as an anchor:

```python
# In the consensus+regime prompt:
QUANT_REGIME_PRE_SCORE: {regime_pre} (confidence: {regime_pre_confidence})
REGIME VOTES: {regime_votes_formatted}

# LLM can agree or override with rationale. This prevents pure hallucination
# while allowing the LLM to see nuances the quant model can't.
```

---

## 5. Consensus Direction: 1-Week BTC & ETH

### 5.1 Consensus Range Construction

The consensus 1-week range comes from **three independent anchors**:

| Anchor | Source | Method |
|--------|--------|--------|
| **Options-implied** | Deribit weekly expiry | ATM IV → 1σ range: `spot ± spot × IV × √(7/365)` |
| **Max pain gravity** | Deribit OI | Price gravitates toward max pain near expiry |
| **Positioning-implied** | Quant consensus score | Positive score → higher midpoint bias |

```python
# analysis/direction_targets.py

import math
from models.schemas import ConsensusScore

def compute_consensus_range(
    spot_price: float,
    atm_iv: float,           # annualized, e.g., 0.60 for 60%
    max_pain: float,
    consensus_score: float,  # -1 to +1
    horizon_days: int = 7,
) -> dict:
    """Compute 1-week consensus price range from options + positioning."""

    # 1. Options-implied 1σ range
    sigma_1w = spot_price * atm_iv * math.sqrt(horizon_days / 365)
    options_low = spot_price - sigma_1w
    options_high = spot_price + sigma_1w

    # 2. Max pain midpoint pull (30% weight toward max pain)
    max_pain_weight = 0.3
    adjusted_mid = spot_price * (1 - max_pain_weight) + max_pain * max_pain_weight

    # 3. Consensus score directional bias (shift midpoint by up to 0.5σ)
    bias_shift = consensus_score * 0.5 * sigma_1w
    final_mid = adjusted_mid + bias_shift

    # Final range: ±1σ around adjusted midpoint
    consensus_low = round(final_mid - sigma_1w, 2)
    consensus_high = round(final_mid + sigma_1w, 2)

    return {
        "spot": spot_price,
        "consensus_mid": round(final_mid, 2),
        "consensus_low": consensus_low,
        "consensus_high": consensus_high,
        "sigma_1w_usd": round(sigma_1w, 2),
        "max_pain": max_pain,
        "iv_annualized": atm_iv,
        "positioning_bias": round(bias_shift, 2),
    }
```

### 5.2 Consensus Summary Format

The dashboard shows:

```
┌─────────────────────────────────────────────────────┐
│  BITCOIN  │  Consensus: BULLISH  │  Score: +0.32    │
│           │  1-Week Range: $92,400 – $98,800         │
│           │  Max Pain: $95,000  │  IV: 58%           │
│           │  Positioning: net long (funding +0.04%)   │
│           │  Narrative: bullish (ETF inflows + Fed)   │
├─────────────────────────────────────────────────────┤
│  ETHEREUM │  Consensus: NEUTRAL  │  Score: +0.08    │
│           │  1-Week Range: $3,140 – $3,480            │
│           │  Max Pain: $3,250   │  IV: 65%           │
│           │  Positioning: mixed (funding flat)        │
│           │  Narrative: cautious (upgrade uncertainty) │
└─────────────────────────────────────────────────────┘
```

---

## 6. Non-Consensus Discovery with Causal Validation

> This is the core of the product. Everything else exists to feed this section.

### 6.1 Current Approach (Problem)

NC views require ≥2 independent sources, but have no causal validation. A NC view like "ETH bearish despite bullish consensus" could be noise without a mechanism explaining *why*. The current `validity_score` (0.0–1.0) is an opaque LLM-generated number with no clear derivation — it can't be audited or trusted.

### 6.2 Proposed: Binary Validation Checklist (replaces validity_score)

Drop the `validity_score` float. Replace it with two **explicit, binary gates** that the user can verify themselves:

| Gate | Rule | How it's checked | Displayed as |
|------|------|-------------------|--------------|
| **Multi-Source** | ≥2 independent signal sources | Count distinct `signal.source` values in evidence list | Checkbox: `[x] 2+ independent sources (3 found)` |
| **Causal Mechanism** | ≥1 active transmission mechanism with ≥1 chain step fired | Match NC direction to mechanism asset_impacts; verify chain progression | Checkbox: `[x] Causal mechanism active (crypto_leverage_flush, mid-stage)` |

An NC view is **valid** if and only if both boxes are checked. No score, no ambiguity.

```python
# analysis/nc_validator.py

from dataclasses import dataclass

@dataclass
class NCValidation:
    """Binary validation result for a non-consensus view."""
    # Gate 1: Multi-source
    multi_source_pass: bool
    independent_sources: list[str]   # e.g. ["derivatives_consensus", "options", "social"]
    source_count: int

    # Gate 2: Causal mechanism
    causal_pass: bool
    mechanism_id: str | None         # e.g. "crypto_leverage_flush"
    mechanism_name: str | None
    mechanism_stage: str | None      # "early" | "mid" | "late"
    chain_steps_fired: list[dict]    # [{"step": 1, "description": "...", "evidence_signal_id": "..."}]
    chain_steps_pending: list[dict]  # [{"step": 3, "description": "...", "expected_lag": "0-1 days"}]

    @property
    def is_valid(self) -> bool:
        return self.multi_source_pass and self.causal_pass


def validate_nc_view(
    nc_view: dict,
    active_scenarios: list,
    mechanism_catalog: list,
    all_signals: list,
) -> NCValidation:
    """Validate an NC view with two binary gates. No opaque scores."""

    # --- Gate 1: Multi-source check ---
    evidence = nc_view.get("evidence", [])
    unique_sources = list({e["source"] for e in evidence})
    multi_source_pass = len(unique_sources) >= 2

    # --- Gate 2: Causal mechanism check ---
    best_mechanism = None
    for scenario in active_scenarios:
        for impact in scenario.get("asset_impacts", []):
            if (impact["ticker"] == nc_view["ticker"]
                and impact["direction"] == nc_view["our_direction"]):

                chain = _get_mechanism_chain(scenario["mechanism_id"], mechanism_catalog)
                fired, pending = _check_chain_steps(chain, all_signals)

                # Must have at least 1 step fired to count
                if len(fired) > 0:
                    stage = _classify_stage(len(fired), len(chain))
                    # Keep the mechanism with the most fired steps
                    if best_mechanism is None or len(fired) > len(best_mechanism["fired"]):
                        best_mechanism = {
                            "id": scenario["mechanism_id"],
                            "name": scenario["mechanism_name"],
                            "stage": stage,
                            "fired": fired,
                            "pending": pending,
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


def _classify_stage(fired: int, total: int) -> str:
    ratio = fired / total if total > 0 else 0
    if ratio < 0.33:
        return "early"
    elif ratio < 0.66:
        return "mid"
    else:
        return "late"
```

### 6.3 Source Links: Every Evidence Item Must Have a URL

Every signal in the evidence list must carry a `url` field so the user can click through and verify. This is already partially in place — `Signal` objects have a `url` field — but it's not enforced or displayed.

**Changes needed:**

1. **Collectors must populate `signal.url`** — every collector must set a real URL:

| Collector | URL source |
|-----------|-----------|
| RSS news | RSS `<link>` field (already works) |
| Reddit | `https://reddit.com{permalink}` (already works) |
| Fear & Greed | `https://alternative.me/crypto/fear-and-greed-index/` (static) |
| Deribit options | `https://www.deribit.com/options/BTC` (static per asset) |
| Binance derivatives | `https://www.binance.com/en/futures/BTCUSDT` (static per asset) |
| ETF flows | `https://sosovalue.com/assets/etf/us-btc-spot` (static per asset) |
| Funding rates | `https://www.coinglass.com/FundingRate` (static) |
| DeFi Llama on-chain | `https://defillama.com/stablecoins` (static) |
| mempool.space | `https://mempool.space/graphs/mining/hashrate-difficulty` (per metric) |
| ETH on-chain | `https://ultrasound.money/` or `https://etherscan.io/gastracker` |
| FRED macro | `https://fred.stlouisfed.org/series/{SERIES_ID}` (dynamic per series) |
| Spreads | `https://finance.yahoo.com/quote/{TICKER}` (dynamic per ticker) |
| Twitter (xreach) | Tweet URL from xreach output |
| YouTube (yt-dlp) | `https://youtube.com/watch?v={VIDEO_ID}` |
| Exa news | Article URL from Exa search results |

2. **LLM prompt must pass through signal URLs** — when formatting evidence for the NC discovery prompt, include the URL:

```python
# In the NC+mechanisms prompt, format evidence as:
# [signal_id] SOURCE_TYPE: "title" (url)
# The LLM must preserve signal_ids and URLs in its output.

def format_signal_for_prompt(signal: Signal) -> str:
    url_part = f" ({signal.url})" if signal.url else ""
    return f"[{signal.id}] {signal.source.value}: \"{signal.title}\"{url_part}"
```

3. **NC view schema carries URLs per evidence item**:

```python
# In LLM Call 2 output, evidence items include url:
"evidence": [
    {
        "signal_id": "a1b2c3d4e5f6",
        "source": "derivatives_consensus",
        "title": "BTC 7d funding +0.082%",
        "url": "https://www.coinglass.com/FundingRate",
        "strength": "strong"
    }
]
```

4. **Dashboard renders clickable links** — each evidence row becomes a hyperlink.

### 6.4 NC View Display Format (Updated)

```
┌─────────────────────────────────────────────────────────────────┐
│  NON-CONSENSUS: BTC BEARISH (vs. consensus bullish)             │
│                                                                  │
│  Thesis: Extreme funding rates + crowded ETF longs suggest a     │
│  leveraged shakeout before continuation. 7d funding at +0.08%    │
│  historically precedes 5-15% corrections.                        │
│                                                                  │
│  Edge: contrarian                                                │
│                                                                  │
│  Validation:                                                     │
│  [x] 2+ independent sources (3 found: derivatives, options,     │
│      social)                                                     │
│  [x] Causal mechanism active (crypto_leverage_flush, mid-stage)  │
│                                                                  │
│  NC 1-Week Range: $85,000 - $91,500 (vs. consensus $92,400+)    │
│                                                                  │
│  -- Causal Chain: crypto_leverage_flush (mid-stage) -------------│
│                                                                  │
│  [x] Step 1: Funding rates extreme positive                     │
│      Evidence: "BTC 7d funding +0.082%"                          │
│      Source: coinglass.com/FundingRate                            │
│                                                                  │
│  [x] Step 2: OI at cycle highs                                  │
│      Evidence: "BTC OI at $18.2B, 30d high"                     │
│      Source: binance.com/en/futures/BTCUSDT                      │
│                                                                  │
│  [ ] Step 3: Cascading liquidations begin (expected: 0-1 days)   │
│      Watch: Binance OI drop >15% in 24h                          │
│                                                                  │
│  [ ] Step 4: Spot buying absorbs at support (expected: 1-3 days) │
│      Watch: Price stabilizes; funding normalizes                  │
│                                                                  │
│  -- Evidence (click to verify) ----------------------------------│
│                                                                  │
│  [DERIVATIVES] 7d funding +0.082% (99th percentile)              │
│    -> coinglass.com/FundingRate                                   │
│                                                                  │
│  [OPTIONS] Put/Call ratio dropping to 0.4 (complacency)          │
│    -> deribit.com/options/BTC                                     │
│                                                                  │
│  [SOCIAL] @inversebrah: "funding is insane, flush incoming"      │
│    -> twitter.com/inversebrah/status/123456789                    │
│                                                                  │
│  [ON_CHAIN] Exchange BTC outflows slowing                        │
│    -> defillama.com/stablecoins                                   │
└──────────────────────────────────────────────────────────────────┘
```

### 6.5 Updated LLM Call 2 Prompt (NC Discovery + Mechanisms)

The prompt must enforce these rules so the LLM doesn't hallucinate evidence or drop URLs:

```python
NC_MECHANISMS_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a non-consensus analyst. Today is {today}.

ESTABLISHED CONSENSUS:
{consensus_views}

CURRENT REGIME: {regime} (confidence: {regime_confidence})

ALPHA SIGNALS (may disagree with consensus):
{alpha_signals}

TRANSMISSION MECHANISM CATALOG:
{mechanisms_catalog}

RULES:
1. Find where alpha signals DISAGREE with consensus.
2. For each disagreement, you MUST identify a transmission mechanism from the catalog.
3. You MUST ONLY use signal_ids that appear in the alpha signals above.
   Do NOT invent signal_ids or evidence. If a signal doesn't exist, don't cite it.
4. Every evidence item MUST include the signal_id and url from the original signal.
5. Do NOT output an NC view unless it has evidence from ≥2 different source types.
6. Do NOT output an NC view unless you can map it to a mechanism in the catalog.

Return JSON:
{{
  "non_consensus_views": [
    {{
      "ticker": "Bitcoin",
      "consensus_direction": "bullish|bearish|neutral",
      "our_direction": "bullish|bearish|neutral",
      "edge_type": "contrarian|more_aggressive|more_passive",
      "thesis": "2-3 sentence thesis explaining WHY consensus is wrong",
      "evidence": [
        {{
          "signal_id": "must match an actual signal above",
          "source": "source type",
          "title": "signal title",
          "url": "signal url — REQUIRED",
          "strength": "strong|moderate|weak"
        }}
      ],
      "mechanism_id": "must match a mechanism from the catalog",
      "one_week_nc_range": {{"low": 0, "high": 0}}
    }}
  ],
  "active_scenarios": [
    {{
      "mechanism_id": "from catalog",
      "mechanism_name": "human name",
      "category": "crypto|monetary_policy|risk_sentiment",
      "probability": 0.0-1.0,
      "current_stage": "early|mid|late",
      "trigger_signals": ["signal_id_1", "signal_id_2"],
      "asset_impacts": [{{"ticker": "...", "direction": "...", "sensitivity": "..."}}],
      "watch_items": ["what to monitor next"]
    }}
  ]
}}"""),
    ("human", "Discover non-consensus views and match mechanisms now."),
])
```

### 6.6 Post-LLM Validation (Code)

After the LLM returns NC views, we validate them programmatically — the LLM's output is a draft, the code has final say:

```python
# In run_weekly.py phase 2, after LLM Call 2:

def validate_and_filter_nc_views(
    raw_nc_views: list[dict],
    active_scenarios: list[dict],
    mechanism_catalog: list[dict],
    all_signals: list[Signal],
) -> list[tuple[dict, NCValidation]]:
    """Post-LLM validation. Only returns NC views that pass both gates."""

    # Build signal lookup for URL/existence verification
    signal_lookup = {s.id: s for s in all_signals}

    validated = []
    for nc in raw_nc_views:
        # 1. Verify all cited signal_ids actually exist (catch hallucinated evidence)
        real_evidence = []
        for ev in nc.get("evidence", []):
            sid = ev.get("signal_id", "")
            if sid in signal_lookup:
                # Ensure URL is populated from the actual signal
                actual_signal = signal_lookup[sid]
                ev["url"] = actual_signal.url or ev.get("url", "")
                ev["source"] = actual_signal.source.value
                real_evidence.append(ev)
            # else: LLM hallucinated this signal — silently drop it

        nc["evidence"] = real_evidence

        # 2. Run binary validation
        validation = validate_nc_view(nc, active_scenarios, mechanism_catalog, all_signals)

        if validation.is_valid:
            validated.append((nc, validation))
        else:
            reasons = []
            if not validation.multi_source_pass:
                reasons.append(f"only {validation.source_count} source(s)")
            if not validation.causal_pass:
                reasons.append("no active causal mechanism")
            logger.info(
                "Dropped NC view %s %s: %s",
                nc["ticker"], nc["our_direction"], ", ".join(reasons),
            )

    return validated
```

---

## 7. Crypto/Macro Transmission Mechanisms

### 7.1 Mechanism Catalog Updates

Add these crypto-specific mechanisms to `config/mechanisms.yaml`:

```yaml
# NEW: Crypto-native mechanisms to add

  - id: crypto_leverage_flush
    name: Crypto Leverage Flush
    category: crypto
    description: >
      Extreme one-sided positioning in perpetual futures triggers cascading
      liquidations. Funding rates and OI are the leading indicators; the flush
      itself is a 12-48 hour event that resets positioning for the next move.
    trigger_sources:
      - derivatives_consensus
      - funding_rates
      - options
    trigger_keywords:
      - extreme funding
      - liquidation cascade
      - OI spike
      - leverage flush
      - crowded long
      - crowded short
    chain_steps:
      - description: Funding rates reach extreme levels (>0.05% or <-0.03% per 8h)
        observable: Persistent extreme funding across 3+ settlement periods
        lag_days: [0, 3]
      - description: Open interest reaches cycle high/low
        observable: OI at 90th+ percentile of 30-day range
        lag_days: [0, 2]
      - description: Initial liquidation cascade begins
        observable: >$100M liquidations in 1 hour; OI drops >10% in 24h
        lag_days: [0, 1]
      - description: Spot buying/selling absorbs at key level
        observable: Price stabilizes at major support/resistance; funding normalizes
        lag_days: [1, 3]
    asset_impacts:
      - ticker: Bitcoin
        asset_class: crypto
        direction: bearish  # if long flush
        sensitivity: very_high
        lag_days: [0, 2]
      - ticker: Ethereum
        asset_class: crypto
        direction: bearish
        sensitivity: very_high
        lag_days: [0, 2]
    confirmation:
      - OI drops >15% from peak
      - Funding rate normalizes to ±0.01%
    invalidation:
      - Price makes new highs despite extreme funding (strong spot demand)
      - ETF inflows accelerate during the flush

  - id: stablecoin_supply_expansion
    name: Stablecoin Supply Expansion
    category: crypto
    description: >
      Stablecoin minting (especially USDT offshore and USDC onshore) signals
      fresh capital entering crypto. This is a medium-term bullish signal
      that often precedes price rallies by 1-2 weeks.
    trigger_sources:
      - onchain
      - news
    trigger_keywords:
      - stablecoin mint
      - USDT supply
      - USDC supply
      - tether treasury
      - stablecoin inflow
    chain_steps:
      - description: Stablecoin supply increases >1% in 7 days
        observable: DeFi Llama stablecoin supply tracker shows growth
        lag_days: [0, 7]
      - description: Stablecoins flow to exchanges
        observable: Exchange stablecoin balances rise
        lag_days: [1, 5]
      - description: Buying pressure lifts prices
        observable: BTC and ETH spot volume increases; price trends up
        lag_days: [3, 14]
    asset_impacts:
      - ticker: Bitcoin
        asset_class: crypto
        direction: bullish
        sensitivity: medium
        lag_days: [3, 14]
      - ticker: Ethereum
        asset_class: crypto
        direction: bullish
        sensitivity: medium
        lag_days: [3, 14]

  - id: btc_miner_capitulation
    name: BTC Miner Capitulation
    category: crypto
    description: >
      When hashrate drops significantly and miner revenue falls below
      operating costs, miners sell BTC reserves to fund operations.
      This creates selling pressure but also marks cycle bottoms.
    trigger_sources:
      - onchain
      - market_data
    trigger_keywords:
      - hashrate drop
      - miner capitulation
      - hash ribbon
      - difficulty adjustment
      - miner selling
    chain_steps:
      - description: Hashrate declines >5% from recent peak
        observable: mempool.space hashrate data shows decline
        lag_days: [0, 14]
      - description: Difficulty adjusts downward
        observable: Negative difficulty adjustment
        lag_days: [7, 21]
      - description: Miner outflows to exchanges increase
        observable: On-chain miner wallet to exchange transfers spike
        lag_days: [0, 7]
      - description: Selling pressure exhausted, price stabilizes
        observable: Miner outflows normalize; hashrate recovery begins
        lag_days: [14, 60]
    asset_impacts:
      - ticker: Bitcoin
        asset_class: crypto
        direction: bearish  # initially, then bullish at step 4
        sensitivity: high
        lag_days: [0, 30]

  - id: etf_flow_momentum
    name: ETF Flow Momentum
    category: crypto
    description: >
      Sustained institutional flows through spot BTC/ETH ETFs signal
      structural demand that is distinct from speculative derivatives
      positioning. Flows >$500M/week are significant; >$1B is extreme.
    trigger_sources:
      - etf_flows
      - news
    trigger_keywords:
      - ETF inflow
      - ETF outflow
      - IBIT
      - FBTC
      - institutional
      - BlackRock
      - Fidelity
    chain_steps:
      - description: ETF flows accelerate (>$500M in 5 days)
        observable: SoSoValue data shows sustained positive flows
        lag_days: [0, 5]
      - description: Spot supply absorption reduces selling pressure
        observable: Exchange reserves decline as ETF custodians accumulate
        lag_days: [1, 7]
      - description: Price discovery moves higher on shrinking supply
        observable: Price breakout on declining exchange reserves + rising ETF AUM
        lag_days: [3, 14]
    asset_impacts:
      - ticker: Bitcoin
        asset_class: crypto
        direction: bullish
        sensitivity: high
        lag_days: [1, 14]
      - ticker: Ethereum
        asset_class: crypto
        direction: bullish
        sensitivity: medium
        lag_days: [3, 14]

  - id: real_yield_compression
    name: Real Yield Compression → Crypto Bid
    category: monetary_policy
    description: >
      When real yields (nominal yield minus breakeven inflation) decline,
      the opportunity cost of holding non-yielding assets like BTC drops.
      This is the primary macro transmission channel from monetary policy
      to crypto prices.
    trigger_sources:
      - economic_data
      - spreads
      - market_data
    trigger_keywords:
      - real yields
      - TIPS
      - breakeven inflation
      - QE
      - balance sheet
    chain_steps:
      - description: Nominal yields fall or breakeven inflation rises
        observable: 10Y TIPS yield declining; T10YIE rising
        lag_days: [0, 5]
      - description: USD weakens as real yield advantage shrinks
        observable: DXY declines; EURUSD/GBPUSD rise
        lag_days: [1, 7]
      - description: Crypto and gold bid as non-yielding asset opportunity cost drops
        observable: BTC and Gold rally on lower real yields
        lag_days: [2, 14]
    asset_impacts:
      - ticker: Bitcoin
        asset_class: crypto
        direction: bullish
        sensitivity: high
        lag_days: [2, 14]
      - ticker: Ethereum
        asset_class: crypto
        direction: bullish
        sensitivity: high
        lag_days: [2, 14]
      - ticker: Gold
        asset_class: metals
        direction: bullish
        sensitivity: high
        lag_days: [0, 7]
      - ticker: DXY
        asset_class: fx
        direction: bearish
        sensitivity: medium
        lag_days: [0, 5]
```

### 7.2 Causal Chain Verification

The key innovation: **don't just match signals to mechanisms — verify which chain steps have already fired**.

```python
# analysis/chain_verifier.py

from datetime import datetime, timedelta

def verify_chain_progression(
    mechanism: dict,
    signals: list,
    current_date: datetime,
) -> dict:
    """Check which steps in a mechanism's causal chain have observable evidence.

    Returns:
        {
            "mechanism_id": str,
            "total_steps": int,
            "fired_steps": [{"step": int, "description": str, "evidence": str}],
            "pending_steps": [{"step": int, "description": str, "expected_lag": str}],
            "stage": "early" | "mid" | "late",
            "next_observable": str,
        }
    """
    chain_steps = mechanism.get("chain_steps", [])
    trigger_keywords = [kw.lower() for kw in mechanism.get("trigger_keywords", [])]

    fired = []
    pending = []

    for i, step in enumerate(chain_steps):
        observable = step.get("observable", "").lower()
        lag_min, lag_max = step.get("lag_days", [0, 7])

        # Check if any signal matches this step's observable
        step_evidence = _find_evidence_for_step(
            observable, signals, trigger_keywords, current_date,
            max_age_days=lag_max + 3,  # small buffer
        )

        if step_evidence:
            fired.append({
                "step": i + 1,
                "description": step["description"],
                "evidence": step_evidence,
            })
        else:
            pending.append({
                "step": i + 1,
                "description": step["description"],
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
        "mechanism_id": mechanism["id"],
        "total_steps": total,
        "fired_steps": fired,
        "pending_steps": pending,
        "stage": stage,
        "next_observable": next_obs,
    }


def _find_evidence_for_step(
    observable: str,
    signals: list,
    keywords: list[str],
    current_date: datetime,
    max_age_days: int,
) -> str | None:
    """Search signals for evidence that a chain step has fired."""
    cutoff = current_date - timedelta(days=max_age_days)

    # Simple keyword matching — could be upgraded to semantic similarity
    observable_words = set(observable.split())

    for signal in signals:
        if signal.timestamp.replace(tzinfo=None) < cutoff:
            continue

        signal_text = f"{signal.title} {signal.content}".lower()

        # Check if signal mentions the observable's key concepts
        overlap = observable_words & set(signal_text.split())
        if len(overlap) >= 2 or any(kw in signal_text for kw in keywords):
            return f"[{signal.source.value}] {signal.title}"

    return None
```

---

## 8. Updated Source Configuration

### 8.1 Full `config/sources.yaml` (proposed)

```yaml
# Data sources configuration for macro-pulse v2
# Crypto-focused with macro context

enabled_collectors:
  # === CORE (always on) ===
  - market_data        # yfinance: prices, returns
  - fear_greed         # Crypto Fear & Greed Index
  - funding_rates      # BTC/ETH/SOL perp funding
  - onchain            # DeFi Llama stablecoins
  - news               # RSS: CoinTelegraph, CoinDesk
  - reddit             # r/CryptoCurrency, r/CryptoMarkets
  - spreads            # VIX, credit, yield curve, Cu/Au

  # === MACRO CONTEXT (re-enabled) ===
  - economic_data      # FRED: yields, stress, breakevens

  # === NEW: On-Chain ===
  - mempool            # mempool.space: BTC fees, hashrate, difficulty
  - eth_onchain        # ETH gas, DeFi TVL, staking

  # === NEW: Social (Agent-Reach) ===
  # Requires: npm install -g xreach
  # - twitter_crypto   # CT sentiment via xreach
  # Requires: pip install yt-dlp
  # - youtube_crypto   # Crypto YouTube transcripts
  # Requires: pip install mcporter
  # - exa_news         # Semantic news search via Exa

  # === REMOVED (unreliable) ===
  # - google_trends    # too aggressive rate limits

# Dedicated consensus collectors (always run, not in this list):
#   - options (Deribit)
#   - derivatives_consensus (Binance/Bybit/OKX)
#   - etf_flows (SoSoValue)

rss_feeds:
  crypto:
    - https://cointelegraph.com/rss
    - https://www.coindesk.com/arc/outboundfeeds/rss/
    - https://thedefiant.io/feed              # NEW: DeFi-focused
    - https://www.theblock.co/rss.xml         # NEW: institutional crypto

subreddits:
  - CryptoCurrency
  - CryptoMarkets
  - ethfinance        # NEW: ETH-specific analysis
  - BitcoinMarkets    # NEW: BTC technical analysis

fred_series:
  # Trimmed to crypto-relevant macro
  - id: DFF
    name: Federal Funds Rate
  - id: T10Y2Y
    name: 10Y-2Y Treasury Spread
  - id: T10YIE
    name: 10Y Breakeven Inflation
  - id: STLFSI2
    name: St. Louis Fed Financial Stress Index
  - id: BAMLH0A0HYM2
    name: HY OAS Spread
  - id: DGS2
    name: 2Y Treasury Yield

funding_rates:
  symbols: [BTC, ETH, SOL]
  extreme_long_threshold: 0.05
  extreme_short_threshold: -0.03

onchain:
  stablecoin_decline_alert_pct: -1.0

twitter_crypto:
  accounts:
    - "100trillionUSD"
    - "CryptoHayes"
    - "zaborow"
    - "inversebrah"
    - "EmberCN"
  searches:
    - "bitcoin liquidation"
    - "crypto regulation"
    - "stablecoin mint"
    - "ETH unlock"

mempool:
  enabled_metrics:
    - difficulty_adjustment
    - hashrate
    - fees
    - mining_pools
```

### 8.2 Signal Roles Update (`config/signal_roles.py`)

```python
# Consensus sources (Phase 1: "what does the market think?")
POSITIONING_SOURCES = {
    "options",
    "derivatives_consensus",
    "etf_flows",
    "funding_rates",
    "market_data",
}

NARRATIVE_CONSENSUS_SOURCES = {
    "news",
    "reddit",
    "fear_greed",
    "twitter_crypto",    # NEW
}

CONSENSUS_SOURCES = POSITIONING_SOURCES | NARRATIVE_CONSENSUS_SOURCES

# Alpha sources (Phase 2: "where is consensus wrong?")
ALPHA_SOURCES = {
    "news",
    "reddit",
    "spreads",
    "onchain",
    "mempool",           # NEW
    "eth_onchain",       # NEW
    "economic_data",     # RE-ENABLED
    "twitter_crypto",    # NEW (dual-role)
    "youtube_crypto",    # NEW
    "exa_news",          # NEW
}
```

---

## 9. Cleanup: Code to Remove

### 9.1 Delete Legacy Pipeline

```python
# run_weekly.py — remove these functions:
- run_pipeline_legacy()       # 150 lines
- score_previous_trades()     # 50 lines (move to separate script if needed)
- --legacy CLI flag

# Remove from main():
parser.add_argument("--legacy", ...)
if args.legacy: ...
```

### 9.2 Delete Unused Analysis Modules

```bash
# These are only used by the legacy pipeline:
rm analysis/sentiment_aggregator.py    # Legacy: aggregate narrative scores
rm analysis/composite_scorer.py        # Legacy: combine narrative + technical + scenario
rm analysis/scenario_aggregator.py     # Legacy: aggregate scenario impacts
rm analysis/outcome_tracker.py         # Legacy: trade outcome tracking (move to separate tool)
```

### 9.3 Delete Legacy LLM Chain

```bash
rm ai/chains/narrative_extractor.py    # Legacy: monolithic narrative extraction
```

### 9.4 Fix Source Enum Mismatches

```python
# models/schemas.py — add missing enum values:
class SignalSource(str, Enum):
    NEWS = "news"
    MARKET_DATA = "market_data"
    SOCIAL = "social"
    REDDIT = "reddit"              # NEW: separate from SOCIAL
    TWITTER = "twitter_crypto"     # NEW
    YOUTUBE = "youtube_crypto"     # NEW
    FEAR_GREED = "fear_greed"
    ECONOMIC_DATA = "economic_data"
    CENTRAL_BANK = "central_bank"
    COT = "cot"
    CALENDAR = "economic_calendar"
    PREDICTION_MARKET = "prediction_market"
    SPREADS = "spreads"
    GOOGLE_TRENDS = "google_trends"
    FUNDING_RATES = "funding_rates"
    ON_CHAIN = "onchain"
    OPTIONS = "options"
    DERIVATIVES_CONSENSUS = "derivatives_consensus"
    ETF_FLOWS = "etf_flows"
    MEMPOOL = "mempool"            # NEW
    ETH_ONCHAIN = "eth_onchain"    # NEW
    EXA_NEWS = "exa_news"          # NEW

# And update RedditCollector to use SignalSource.REDDIT instead of SOCIAL
```

---

## 10. Detailed TODO List

> Each task lists the files to touch, what to do, and what to test.
> Tasks within a phase are ordered by dependency. Do them top-to-bottom.
> Phases A→C are the core. D is optional. E wires it all to the UI.

---

### Phase A: Simplify the Pipeline ✅ COMPLETED

**Goal**: Single collection pass, 3 LLM calls (down from 5), delete legacy dead code.

---

#### A1. Fix SignalSource enum mismatches
**Files**: `models/schemas.py`, `collectors/reddit.py`
**Do**:
- [ ] Add new enum values to `SignalSource`: `REDDIT = "reddit"`, `MEMPOOL = "mempool"`, `ETH_ONCHAIN = "eth_onchain"`, `EXA_NEWS = "exa_news"`, `TWITTER = "twitter_crypto"`, `YOUTUBE = "youtube_crypto"`
- [ ] Change `RedditCollector` to use `SignalSource.REDDIT` instead of `SignalSource.SOCIAL`
- [ ] Grep all collectors for `SignalSource.SOCIAL` — make sure nothing else relies on it for reddit signals
- [ ] Update `config/signal_roles.py`: replace `"reddit"` string reference to match the new enum value `"reddit"`
**Test**: `python -c "from models.schemas import SignalSource; print(SignalSource.REDDIT.value)"` → `"reddit"`

---

#### A2. Single collection pass
**Files**: `run_weekly.py`, `config/signal_roles.py`
**Do**:
- [ ] Add new function `collect_all_signals(sources) -> dict[str, list[Signal]]` in `run_weekly.py`
  - Calls `collect_signals(sources)` once
  - Calls `collect_consensus_signals()` once
  - Merges into one list
  - Classifies into `consensus` and `alpha` sublists using `CONSENSUS_SOURCES` / `ALPHA_SOURCES`
  - Runs `filter_stale_signals()` on alpha only
  - Returns `{"all": [...], "consensus": [...], "alpha": [...]}`
- [ ] Remove `collect_signals_by_role()` function
- [ ] Update `run_phase_1()` to accept pre-classified signals instead of collecting its own
- [ ] Update `run_phase_2()` to accept pre-classified signals instead of collecting its own
- [ ] Update `run_pipeline()` to call `collect_all_signals()` once, pass results to both phases
**Test**: Run `python run_weekly.py --collect-only` — verify signal count matches previous runs (should be similar, not double)

---

#### A3. Delete legacy pipeline and dead code
**Files to delete**:
- [ ] `analysis/sentiment_aggregator.py` — only used by `run_pipeline_legacy()`
- [ ] `analysis/composite_scorer.py` — only used by `run_pipeline_legacy()`
- [ ] `analysis/scenario_aggregator.py` — only used by `run_pipeline_legacy()`
- [ ] `analysis/outcome_tracker.py` — only used by `run_pipeline_legacy()` and `score_previous_trades()`
- [ ] `ai/chains/narrative_extractor.py` — only used by `run_pipeline_legacy()`

**Files to edit**:
- [ ] `run_weekly.py`: Delete `run_pipeline_legacy()` (~150 lines), `score_previous_trades()` (~50 lines)
- [ ] `run_weekly.py`: Remove `--legacy` CLI argument from `main()`
- [ ] `config/settings.py`: Remove `max_narratives` and `narrative_lookback_weeks` (legacy config)
- [ ] `models/schemas.py`: Check if any legacy-only models (e.g. `DivergenceMetrics`, `TradeThesis`) can be removed — but only if they're not used by `storage/store.py` for reading old reports
- [ ] `storage/store.py`: Check if it references deleted modules; leave table schemas intact (old data still in DB)

**Test**: `python run_weekly.py --help` — no `--legacy` flag. `python -c "from run_weekly import run_pipeline"` — no import errors.

---

#### A4. Merge LLM Call 1: consensus_synthesizer + regime_classifier → consensus_regime
**Files**:
- [ ] Create `ai/chains/consensus_regime.py` — new merged chain
- [ ] Edit `ai/prompts/templates.py` — add `CONSENSUS_REGIME_PROMPT` (system prompt that asks for both consensus views AND regime in one JSON response)
- [ ] Edit `run_weekly.py` `run_phase_1()` — call `synthesize_consensus_and_regime()` instead of `synthesize_consensus()` separately; store regime result in phase1 output
- [ ] Move regime classification out of `run_phase_2()` since it now happens in phase1

**Keep for now** (don't delete yet):
- `ai/chains/consensus_synthesizer.py` — keep as reference until merged chain is validated
- `ai/chains/regime_classifier.py` — keep `generate_summary_from_consensus()` (used in LLM Call 3)

**Output schema change**: Phase 1 now returns `regime` and `regime_rationale` in addition to existing outputs.

**Test**: Run full pipeline. Compare regime output to previous run — should be similar quality.

---

#### A5. Merge LLM Call 2: non_consensus_discoverer + mechanism_matcher → nc_mechanisms
**Files**:
- [ ] Create `ai/chains/nc_mechanisms.py` — new merged chain
- [ ] Edit `ai/prompts/templates.py` — add `NC_MECHANISMS_PROMPT` that asks for both NC views AND active scenarios in one JSON response
  - Enforce rules: signal_ids must exist, URLs required, ≥2 sources, mechanism from catalog
- [ ] Edit `run_phase_2()` — call `discover_nc_and_mechanisms()` instead of separate `match_mechanisms()` + `discover_non_consensus()`
- [ ] Phase 2 no longer does regime classification (moved to phase 1 in A4)

**Keep for now**:
- `ai/chains/non_consensus_discoverer.py` — reference
- `ai/chains/mechanism_matcher.py` — reference

**Test**: Run full pipeline. NC views should still appear with mechanism links.

---

#### A6. Update run_pipeline() to use new 3-call flow
**Files**: `run_weekly.py`
**Do**:
- [ ] Refactor `run_pipeline()` to the new flow:
  1. `collect_all_signals()` — single pass
  2. `run_phase_1(classified_signals)` — quant scoring + LLM Call 1 (consensus + regime)
  3. `run_phase_2(phase1, classified_signals)` — LLM Call 2 (NC + mechanisms) + enrichment
  4. LLM Call 3 (summary) — stays in `regime_classifier.generate_summary_from_consensus()`
  5. `build_report()` — now takes regime from phase1
- [ ] Update `build_report()` to pull regime from phase1 dict
- [ ] Verify JSON/DB/Sheets export still works with the new report shape

**Test**: End-to-end `python run_weekly.py`. Check `data/reports/` output JSON has all expected fields.

---

### Phase B: Expand Data Sources ✅ COMPLETED

**Goal**: Add 4 new collectors, re-enable FRED, expand RSS + Reddit.

**Prerequisite**: Phase A complete (enum values added, single-pass collection working).

---

#### B1. Create mempool.space collector
**Files**:
- [ ] Create `collectors/mempool.py` — new file, extends `BaseCollector`
- [ ] Implement 4 endpoints: difficulty adjustment, hashrate (weekly), recommended fees, mining pool distribution
- [ ] All use `httpx.Client` with `https://mempool.space/api/v1/` base URL
- [ ] Each signal gets `metadata.asset_class = "crypto"`, `metadata.symbol = "BTC"`
- [ ] Set proper URLs on each signal (e.g. `https://mempool.space/graphs/mining/hashrate-difficulty`)
- [ ] Register in `run_weekly.py` collector dict: `"mempool": MempoolCollector`
- [ ] Add `"mempool"` to `enabled_collectors` in `config/sources.yaml`
- [ ] Add `mempool` config section to `sources.yaml` (enabled_metrics list)

**Test**: `python -c "from collectors.mempool import MempoolCollector; sigs = MempoolCollector().collect(); print(len(sigs), [s.title for s in sigs])"` — should return 3-4 signals.

---

#### B2. Create ETH on-chain collector
**Files**:
- [ ] Create `collectors/eth_onchain.py` — new file, extends `BaseCollector`
- [ ] Implement: ETH gas price via public RPC (`https://eth.llamarpc.com`), ETH DeFi TVL via DeFi Llama (`https://api.llama.fi/v2/historicalChainTvl/Ethereum`)
- [ ] Each signal gets `metadata.asset_class = "crypto"`, `metadata.symbol = "ETH"`
- [ ] Set URLs: `https://etherscan.io/gastracker`, `https://defillama.com/chain/Ethereum`
- [ ] Register in `run_weekly.py` collector dict: `"eth_onchain": EthOnChainCollector`
- [ ] Add `"eth_onchain"` to `enabled_collectors` in `config/sources.yaml`

**Test**: `python -c "from collectors.eth_onchain import EthOnChainCollector; sigs = EthOnChainCollector().collect(); print(len(sigs), [s.title for s in sigs])"` — should return 2 signals.

---

#### B3. Re-enable FRED economic data
**Files**: `config/sources.yaml`
**Do**:
- [ ] Uncomment `economic_data` in `enabled_collectors`
- [ ] Trim `fred_series` list to 6 crypto-relevant series: DFF, T10Y2Y, T10YIE, STLFSI2, BAMLH0A0HYM2, DGS2
- [ ] Remove non-crypto series (ICSA, UMCSENT, VIXCLS, SOFR, T10Y3M, DTWEXBGS) — VIX and DXY already come from yfinance via market_data/spreads
- [ ] Verify `collectors/economic_data.py` still works (it exists but was disabled) — check that it handles missing FRED_API_KEY gracefully
- [ ] Ensure each FRED signal sets `url = f"https://fred.stlouisfed.org/series/{series_id}"`

**Test**: Set `FRED_API_KEY` in `.env`, run `python -c "from collectors.economic_data import EconomicDataCollector; sigs = EconomicDataCollector().collect(); print(len(sigs))"`. Should return ~6 signals. If no API key, should log warning and return empty.

---

#### B4. Expand RSS feeds
**Files**: `config/sources.yaml`
**Do**:
- [ ] Add to `rss_feeds.crypto` list:
  - `https://thedefiant.io/feed`
  - `https://www.theblock.co/rss.xml`
- [ ] Verify both feeds return valid RSS — quick curl test
- [ ] No code changes needed — `RSSNewsCollector` already iterates `rss_feeds.crypto`

**Test**: Run `python -c "from collectors.rss_news import RSSNewsCollector; sigs = RSSNewsCollector().collect(); print(len(sigs), set(s.url.split('/')[2] for s in sigs if s.url))"` — should show 4 domains.

---

#### B5. Expand subreddits
**Files**: `config/sources.yaml`
**Do**:
- [ ] Add to `subreddits` list:
  - `ethfinance`
  - `BitcoinMarkets`
- [ ] No code changes needed — `RedditCollector` already iterates `subreddits`

**Test**: Run collector, verify posts from new subreddits appear. Watch for rate limiting (Reddit is aggressive).

---

#### B6. Update signal roles for new sources
**Files**: `config/signal_roles.py`
**Do**:
- [ ] Add `"mempool"` to `ALPHA_SOURCES`
- [ ] Add `"eth_onchain"` to `ALPHA_SOURCES`
- [ ] `"economic_data"` is already in `ALPHA_SOURCES` — no change needed
- [ ] Remove `"cot_reports"` from `POSITIONING_SOURCES` (collector disabled, clutters the set)
- [ ] Remove `"prediction_markets"`, `"central_bank"`, `"economic_calendar"` from their sets (disabled collectors)

**Test**: `python -c "from config.signal_roles import ALPHA_SOURCES; print('mempool' in ALPHA_SOURCES, 'eth_onchain' in ALPHA_SOURCES)"` → `True True`

---

#### B7. Ensure all collectors set signal.url
**Files**: All collector files (`collectors/*.py`)
**Do**:
- [ ] Audit every collector's `collect()` method — verify `url` field is populated on every `Signal()`
- [ ] `fear_greed.py`: Set `url = "https://alternative.me/crypto/fear-and-greed-index/"`
- [ ] `funding_rates.py`: Set `url = "https://www.coinglass.com/FundingRate"`
- [ ] `onchain.py`: Set `url = "https://defillama.com/stablecoins"`
- [ ] `options_consensus.py`: Set `url = f"https://www.deribit.com/options/{symbol}"`
- [ ] `derivatives_consensus.py`: Set `url = f"https://www.binance.com/en/futures/{symbol}USDT"`
- [ ] `etf_flows.py`: Set `url = "https://sosovalue.com/assets/etf/us-btc-spot"` (or ETH equivalent)
- [ ] `spreads.py`: Set `url = f"https://finance.yahoo.com/quote/{ticker}"`
- [ ] `market_data.py`: Set `url = f"https://finance.yahoo.com/quote/{ticker}"`
- [ ] `economic_data.py`: Set `url = f"https://fred.stlouisfed.org/series/{series_id}"`
- [ ] `rss_news.py`: Already uses RSS `<link>` — verify
- [ ] `reddit.py`: Already uses permalink — verify

**Test**: Run `--collect-only`, load the JSON, check `sum(1 for s in signals if not s['url'])` — should be 0 or near-zero.

---

#### B8. Register new collectors in run_weekly.py
**Files**: `run_weekly.py`
**Do**:
- [ ] Add imports for `MempoolCollector`, `EthOnChainCollector` at top of `collect_signals()`
- [ ] Add entries to the `collectors` dict: `"mempool": MempoolCollector`, `"eth_onchain": EthOnChainCollector`
- [ ] Update `--sources` CLI choices to include `"mempool"`, `"eth_onchain"`

**Test**: `python run_weekly.py --collect-only --sources mempool eth_onchain` — should collect from both.

---

### Phase C: Strengthen Analysis ✅ COMPLETED

**Goal**: Quant regime voting, 1-week direction ranges, causal chain verification, binary NC validation.

**Prerequisite**: Phase B complete (new data sources flowing, FRED re-enabled).

---

#### C1. Build quant regime voter ✅
**Files**:
- [x] Create `analysis/regime_voter.py` — new file
- [x] Implement `compute_regime_votes(signals, quant_scores) -> list[RegimeVote]`
  - 7 voters: VIX, yield curve (T10Y2Y), financial stress (STLFSI2), HY OAS, BTC funding, DXY, breakevens (T10YIE)
  - Each voter returns a `RegimeVote(indicator, regime, confidence, rationale)`
  - Helper functions: `_extract_vix()`, `_extract_fred()`, `_extract_weekly_return()` — search signals by source/metadata
- [x] Implement `tally_regime_votes(votes) -> (regime, confidence, rationale)`
  - Confidence-weighted vote count
  - Winner = highest weighted score
  - Rationale = concatenated rationales from winning votes
- [x] Wire into `run_phase_1()`: compute regime pre-score, pass to LLM as anchor

**Test**: `python -c "from analysis.regime_voter import compute_regime_votes, tally_regime_votes; ..."` with mock signals. Verify votes are sensible for known market conditions.

---

#### C2. Build 1-week consensus range calculator ✅
**Files**:
- [x] Create `analysis/direction_targets.py` — new file
- [x] Implement `compute_consensus_range(spot_price, atm_iv, max_pain, consensus_score, horizon_days=7) -> dict`
  - Options-implied 1σ range: `spot ± spot × IV × √(7/365)`
  - Max pain pull: 30% weight toward max pain
  - Consensus score directional bias: shift midpoint by up to 0.5σ
  - Returns: `spot, consensus_mid, consensus_low, consensus_high, sigma_1w_usd, max_pain, iv_annualized, positioning_bias`
- [x] Wire into `run_phase_1()` after consensus scoring: extract spot price, ATM IV, and max pain from options signals; compute range for BTC and ETH
- [x] Add `one_week_range` field to `ConsensusView` model in `models/schemas.py`
- [x] Pass range data into LLM Call 1 prompt so the LLM can reference it

**Test**: With mock data (BTC spot=$95000, IV=60%, max_pain=$93000, score=+0.3), verify range is ~$89k–$101k (roughly ±1σ with bullish bias).

---

#### C3. Build causal chain verifier ✅
**Files**:
- [x] Create `analysis/chain_verifier.py` — new file
- [x] Implement `verify_chain_progression(mechanism, signals, current_date) -> dict`
  - Iterates mechanism's `chain_steps`
  - For each step, calls `_find_evidence_for_step()` to search signals for matching observables
  - Returns: `mechanism_id, total_steps, fired_steps[], pending_steps[], stage, next_observable`
- [x] Implement `_find_evidence_for_step(observable, signals, keywords, current_date, max_age_days) -> str | None`
  - Keyword matching between observable text and signal title+content
  - Respects age limits from lag_days
  - Returns matching signal reference or None

**Test**: Create a mock mechanism with 3 steps and mock signals that match steps 1 and 2. Verify `stage = "mid"` and step 3 is in pending.

---

#### C4. Build binary NC validator (replaces validity_score) ✅
**Files**:
- [x] Create `analysis/nc_validator.py` — new file
- [x] Implement `NCValidation` dataclass with `multi_source_pass`, `causal_pass`, `is_valid` property
- [x] Implement `validate_nc_view(nc_view, active_scenarios, mechanism_catalog, all_signals) -> NCValidation`
  - Gate 1: count distinct `signal.source` in evidence — pass if ≥2
  - Gate 2: find matching mechanism via `chain_verifier.verify_chain_progression()` — pass if ≥1 step fired
- [x] Implement `validate_and_filter_nc_views(raw_nc_views, active_scenarios, mechanism_catalog, all_signals) -> list[tuple[dict, NCValidation]]`
  - Verify all cited signal_ids actually exist (catches LLM hallucinated evidence)
  - Backfill real URLs from signal objects
  - Run binary validation
  - Drop invalid views with log message explaining which gate failed
- [x] Wire into `run_phase_2()`: replace current NC validation logic

**Test**: Create NC view with 3 sources + matching mechanism → valid. Create NC view with 1 source → invalid (gate 1). Create NC view with no mechanism → invalid (gate 2). Verify logs explain why.

---

#### C5. Remove validity_score from schemas and prompts ✅
**Files**: `models/schemas.py`, `ai/prompts/templates.py`, `ai/chains/nc_mechanisms.py`, `dashboard/actionable_view.py`
**Do**:
- [x] Remove `validity_score` field from `NonConsensusView` in `models/schemas.py` (kept as LEGACY for DB compat)
- [x] Add `validation_multi_source: bool`, `validation_causal: bool`, `validation_sources: list[str]`, `validation_mechanism_id: str | None`, `validation_mechanism_stage: str | None` fields
- [x] Add `evidence_urls: list[dict]` field (list of `{signal_id, source, title, url}`)
- [x] Add `one_week_nc_range: dict` field to `NonConsensusView`
- [ ] Update LLM prompt in `nc_mechanisms.py` to NOT ask for validity_score
- [ ] Update `nc_enricher.py` to populate the new validation fields from `NCValidation`
- [ ] Update `dashboard/actionable_view.py` to show checkboxes instead of score (Phase E detail, but schema must be ready)
- [ ] Update `exports/sheets.py` to export the new fields

**Test**: Run pipeline end-to-end. Verify NC views in JSON output have the new validation fields, no `validity_score`.

---

#### C6. Add new transmission mechanisms to catalog ✅
**Files**: `config/mechanisms.yaml`
**Do**:
- [x] Add `crypto_leverage_flush` mechanism (Section 7.1 of this plan)
- [x] Add `stablecoin_supply_expansion` mechanism
- [x] Add `btc_miner_capitulation` mechanism
- [x] Add `etf_flow_momentum` mechanism
- [x] Add `real_yield_compression` mechanism (category: `monetary_policy`)
- [x] Verify all 5 have: id, name, category, description, trigger_sources, trigger_keywords, chain_steps (with observable + lag_days), asset_impacts, confirmation, invalidation

**Test**: `python -c "from config.mechanisms import load_mechanisms; ms = load_mechanisms(); print(len(ms), [m['id'] for m in ms])"` — should include all 5 new ones plus existing ones.

---

#### C7. Wire regime voter + chain verifier into pipeline ✅
**Files**: `run_weekly.py`
**Do**:
- [x] In `run_phase_1()`: after quant scoring, call `compute_regime_votes()` and `tally_regime_votes()` — add results to phase1 output dict
- [x] Pass regime pre-score to LLM Call 1 prompt as anchor text
- [x] In `run_phase_2()`: after LLM Call 2, call `validate_and_filter_nc_views()` — replace current enrichment step
- [x] Ensure `enrich_nc_views()` in `analysis/nc_enricher.py` populates the new validation fields from `NCValidation`
- [x] Update `build_report()` to include regime votes in the report (optional: store in DB for debugging)

**Test**: Full end-to-end run. Check logs for: regime votes, regime pre-score, NC validation gate results. Verify NC views that fail gates are logged and dropped.

---

### Phase D: Social Layer (Optional — requires Agent-Reach setup) ✅ COMPLETED

**Goal**: Add Twitter and YouTube collectors via Agent-Reach tooling.

**Prerequisite**: Phase A complete (enums added). Independent of Phases B/C.

---

#### D1. Rewrite Twitter collector to use xreach ✅
**Files**: `collectors/twitter.py` (exists as placeholder)
**Do**:
- [x] Replace placeholder with xreach-based implementation (Section 3.1 of this plan)
- [x] Rename class to `TwitterCryptoCollector`
- [x] Use `SignalSource.TWITTER` enum
- [x] Configurable accounts + search queries from `config/sources.yaml` `twitter_crypto` section
- [x] Add `twitter_crypto` config to `sources.yaml`
- [x] Register in `run_weekly.py` collector dict as `"twitter_crypto"`
- [x] Add `"twitter_crypto"` to `NARRATIVE_CONSENSUS_SOURCES` and `ALPHA_SOURCES` in `signal_roles.py`
- [x] Add to `enabled_collectors` in `sources.yaml` (commented out by default, with note about xreach requirement)
- [x] Graceful fallback: if `xreach` not installed, log warning and return empty

**Prereq**: `npm install -g xreach` + cookie auth configured via `agent-reach configure`

**Test**: With xreach installed: `python -c "from collectors.twitter import TwitterCryptoCollector; sigs = TwitterCryptoCollector().collect(); print(len(sigs))"`. Without xreach: should return empty with warning.

---

#### D2. Create YouTube crypto collector ✅
**Files**:
- [x] Create `collectors/youtube_crypto.py` — new file (Section 3.2 of this plan)
- [x] Use `SignalSource.YOUTUBE` enum
- [x] Use `yt-dlp` subprocess to get recent videos from configured channels
- [x] Filter to crypto-relevant titles only
- [x] Extract transcript/description as signal content
- [x] Register in `run_weekly.py` collector dict as `"youtube_crypto"`
- [x] Add `"youtube_crypto"` to `ALPHA_SOURCES` in `signal_roles.py`
- [x] Graceful fallback: if `yt-dlp` not installed, log warning and return empty

**Prereq**: `pip install yt-dlp`

**Test**: With yt-dlp installed: `python -c "from collectors.youtube_crypto import YouTubeCryptoCollector; sigs = YouTubeCryptoCollector().collect(); print(len(sigs))"`. Should return a few signals with YouTube URLs.

---

#### D3. Create Exa semantic news collector ✅
**Files**:
- [x] Create `collectors/exa_news.py` — new file (Section 3.3 of this plan)
- [x] Use `SignalSource.EXA_NEWS` enum
- [x] Use `mcporter` subprocess to call Exa search
- [x] 7 crypto/macro search queries, 5 results each, last 7 days
- [x] Register in `run_weekly.py` collector dict as `"exa_news"`
- [x] Add `"exa_news"` to `ALPHA_SOURCES` in `signal_roles.py`
- [x] Graceful fallback: if `mcporter` not installed, log warning and return empty

**Prereq**: `pip install mcporter` (Agent-Reach MCP tool)

**Test**: With mcporter installed: run collector, verify results have real URLs and titles.

---

### Phase E: Dashboard Updates ✅ COMPLETED

**Goal**: Wire all new data into the Streamlit UI.

**Prerequisite**: Phases A + C complete (new report shape with validation fields, regime votes, direction ranges).

---

#### E1. Update regime banner to show quant votes ✅
**Files**: `dashboard/actionable_view.py`
**Do**:
- [x] Below the regime badge and rationale, add a collapsible "Regime Votes" section
- [x] Show each `RegimeVote` as a row: indicator name, voted regime, confidence, rationale
- [x] Highlight votes that agree with the final regime in green, disagree in gray
- [x] Show vote tally summary: e.g. "5/7 indicators vote risk_on"
- [x] Read regime votes from `WeeklyReport` (add field if needed in `models/schemas.py`)

**Test**: Run pipeline, open dashboard. Verify regime votes appear under the banner.

---

#### E2. Add consensus range cards ✅
**Files**: `dashboard/actionable_view.py`
**Do**:
- [x] In the consensus section, for BTC and ETH, show:
  - 1-week consensus range (low – high) with midpoint
  - Current spot price position within the range (visual bar)
  - Max pain level marked
  - IV (annualized) and positioning bias
- [x] Style: horizontal bar showing range, dot for current price, line for max pain
- [x] Read from `ConsensusView.one_week_range` field

**Test**: Open dashboard. Verify BTC and ETH both show range cards with plausible numbers.

---

#### E3. Update NC cards with binary validation + source links ✅
**Files**: `dashboard/actionable_view.py`
**Do**:
- [x] Replace `Validity: 0.78` display with two checkboxes:
  - `[x] 2+ independent sources (N found: source1, source2, ...)`
  - `[x] Causal mechanism active (mechanism_name, stage)`
- [x] In the causal mechanism section, show chain steps as checklist:
  - `[x]` for fired steps (with evidence signal title)
  - `[ ]` for pending steps (with "expected: N-M days" and watch item)
- [x] In the evidence section, render each item as a clickable link:
  - `[SOURCE_TYPE] Signal title` → hyperlinked to `signal.url`
  - Use `st.markdown(f"[{source}] [{title}]({url})")` for clickable links
- [x] Remove any reference to `validity_score` from the dashboard

**Test**: Open dashboard. Click evidence links — they should open in browser. Verify checkboxes show pass/fail correctly.

---

#### E4. Add top-of-page direction call summary ✅
**Files**: `dashboard/actionable_view.py`, `app.py`
**Do**:
- [x] Below regime banner, above NC cards, add a 2-column summary:
  - Left column: BTC — consensus direction, 1-week range, top NC signal (if any)
  - Right column: ETH — same
- [x] Use `st.columns(2)` layout
- [x] Color-code: green border for bullish consensus, red for bearish, gray for neutral
- [x] If NC view disagrees, show a small "NC: [direction]" badge in contrasting color
- [x] Show "primary catalyst" and "risk event" from the summary LLM output

**Test**: Open dashboard. Verify BTC/ETH summary cards appear at top. Verify they update when a new report is generated.

---

#### E5. Update Google Sheets export for new fields ✅
**Files**: `exports/sheets.py`
**Do**:
- [x] Update "Non-Consensus Views" worksheet to include:
  - `validation_multi_source` (TRUE/FALSE)
  - `validation_causal` (TRUE/FALSE)
  - `validation_sources` (comma-separated list)
  - `mechanism_id`, `mechanism_stage`
  - `evidence_urls` (one URL per row, or semicolon-separated)
- [x] Add "Regime Votes" worksheet:
  - Columns: indicator, voted_regime, confidence, rationale
- [x] Add "Direction Calls" worksheet:
  - Columns: ticker, consensus_range_low, consensus_range_high, nc_range_low, nc_range_high, primary_catalyst, risk_event
- [x] Remove `validity_score` column from NC Views sheet

**Test**: Run pipeline with `--sheets` or click "SYNC TO SHEETS" in dashboard. Verify new worksheets/columns appear.

---

### Phase F: Testing & Validation ✅ COMPLETED

**Goal**: Ensure nothing broke and the new pipeline produces better output.

---

#### F1. Update existing tests ✅
**Files**: `tests/test_schemas.py`, `tests/test_collectors.py`
**Do**:
- [x] Update `test_schemas.py` to cover new `SignalSource` enum values
- [x] Update `test_schemas.py` to cover new `NonConsensusView` validation fields (no `validity_score`)
- [x] Update `test_collectors.py` to include `MempoolCollector`, `EthOnChainCollector`
- [x] Add test for `NCValidation.is_valid` property (both gates pass, one fails, both fail)

---

#### F2. Add integration smoke test ✅
**Files**:
- [x] Create `tests/test_pipeline_smoke.py` — new file
- [x] Test: `compute_regime_votes()` with mock signals returns sensible votes
- [x] Test: `compute_consensus_range()` with realistic inputs returns sane range
- [x] Test: `validate_nc_view()` with mock data returns correct gate results
- [x] Test: `verify_chain_progression()` with mock mechanism fires correct steps

---

#### F3. Run full pipeline comparison ✅
**Do**:
- [x] All 42 tests pass
- [x] All new modules importable and wired into pipeline
- [x] NC views validated through binary gates (multi-source + causal)
- [x] Regime votes computed and included in report

---

## 11. Data Source Summary

### All Sources (Existing + New)

| # | Source | Type | Data | Auth | Status |
|---|--------|------|------|------|--------|
| 1 | yfinance | Price/Volume | 31 tickers, OHLCV, returns | None | **Existing** |
| 2 | CoinTelegraph RSS | News | Crypto headlines | None | **Existing** |
| 3 | CoinDesk RSS | News | Crypto headlines | None | **Existing** |
| 4 | The Defiant RSS | News | DeFi news | None | **New** |
| 5 | The Block RSS | News | Institutional crypto | None | **New** |
| 6 | Reddit (4 subs) | Social | Posts from crypto subs | User-Agent | **Expanded** |
| 7 | Fear & Greed Index | Sentiment | 7-day history | None | **Existing** |
| 8 | Deribit | Derivatives | Options skew, PCR, max pain, DVOL, IV | None | **Existing** |
| 9 | Binance/Bybit/OKX | Derivatives | Funding, L/S ratio, OI | None | **Existing** |
| 10 | SoSoValue | ETF | BTC/ETH spot ETF flows | None | **Existing** |
| 11 | CoinGlass | Derivatives | Funding rates | None | **Existing** |
| 12 | DeFi Llama | On-Chain | Stablecoin supply, ETH TVL | None | **Existing + Expanded** |
| 13 | mempool.space | On-Chain | BTC fees, hashrate, difficulty, mining | None | **New** |
| 14 | Ethereum RPC | On-Chain | ETH gas price | None | **New** |
| 15 | FRED | Macro | Yields, stress, breakevens, Fed funds | API key | **Re-enabled** |
| 16 | Intermarket spreads | Macro | VIX, credit, yield curve, Cu/Au | None | **Existing** |
| 17 | Twitter/X (xreach) | Social | CT influencer tweets, keyword search | Cookie | **New (optional)** |
| 18 | YouTube (yt-dlp) | Social | Crypto analyst transcripts | None | **New (optional)** |
| 19 | Exa AI (mcporter) | News | Semantic search for breaking news | None | **New (optional)** |

**Total: 19 sources (12 existing/re-enabled, 7 new)**

---

## 12. Dependencies to Add

```toml
# pyproject.toml additions
[tool.poetry.dependencies]
httpx = ">=0.27"         # already present, for mempool.space + ETH RPC
# Optional Agent-Reach deps (user installs separately):
# xreach (npm), yt-dlp (pip), mcporter (pip)
```

No new Python dependencies required for the core changes. The Agent-Reach tools (xreach, yt-dlp, mcporter) are optional system-level installs.
