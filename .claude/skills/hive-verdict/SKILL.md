---
name: hive-verdict
description: Hand a finished CoinPicks research result to the NUK3R2 Hive as a research.verdict event (feeds the Fib Bee watchlist and the Trader Bee). Use after researching a token, or when the beekeeper says "send it to the hive", "publish the verdict", or "add to the watchlist".
---

# Publish a research verdict to the Hive

A verdict is the ONLY way research reaches the Trader Bee. It can cause a real buy of $1–$10 from
the Bee's wallet when armed, so accuracy beats speed.

## 0. Where candidates come from
The Discovery Scout queues Base/Robinhood candidates every 6h:
`python NUK3R2-Discovery-Scout-v1.0.0/discovery-scout/scout.py queue` (add `--json` for details).
A queue entry is NOT verified. Its contract came from a pool listing, so run the full identity check
below. Tokens from the queue get `discovery: true`. `scout.py dismiss <symbol> --reason ".."` drops one.

## 1. Identity first (non-negotiable)
- `chain` must be `base` or `robinhood` to be tradable (other chains are allowed but are never traded).
- `contract` must be verified by **at least two independent sources**: DexScreener token page, the
  chain's explorer (BaseScan for Base), GeckoTerminal/CoinGecko, and/or the project's own link. List
  them in `identity.sources`. A name or ticker search alone is never verification.
- Same-ticker tokens you saw and rejected go in `identity.decoys`.
- If identity can't be resolved, publish `identity.status: "UNRESOLVED"` (or `HARD_STOP`). The Hive then
  records it and nothing trades.

## 2. Fill the verdict (`hive/contracts/research.verdict.schema.json`)
Copy `hive/contracts/examples/research.verdict.example.json` and fill:
`asset_id` (`<chain>:<contract lowercase>`), `symbol`, `researched_at` (UTC now), `gate.result` PASS/FAIL
+ `gate.score` /30, `rank` BUY/WATCH/AVOID/FAIL, `confidence` high/medium/low (your research conviction,
which sets the $10/$5/$1 discovery size), `discovery` (true only if it came from the Base/RH discovery
scan), `scores.core_quality` / `scores.timing` / `scores.narrative_power`, `security.score` (0–100) if
checked, `identity.canonical_pool`, and the Market Direction / Blueprint snapshot ids if known.
**Unverifiable → null. Never guess a number.**

## 3. Show the beekeeper, then publish
Show the verdict (symbol, chain, contract, sources, gate, rank, confidence, and what it will trigger:
"discovery → $10 high-confidence buy if all gates pass" or "watchlist only"). Then:
```
python -m hive validate --type research.verdict --file <file>
python -m hive publish  --type research.verdict --file <file>
```
Re-research = publish a NEW verdict (newer `researched_at` wins). Never edit an old one.
