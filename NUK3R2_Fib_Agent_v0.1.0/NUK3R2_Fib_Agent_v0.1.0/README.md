# NUK3R2 Fib Agent v0.2.0

Independent Hive agent for NUK3R2 market-structure research.

It activates when a token becomes a watchlist candidate, creates both Wick and Body anchor Fib structures, tracks reactions, and stores observations for lifetime learning.

It is a research/learning agent only: no trading or wallet execution permissions.

Core NUK3R2 orientation:
- 100% = bottom
- 0% = top
- Levels: 82.6, 78.6, 61.8, 21.4, 17.4
- Mature tokens: ATL -> validated structural high
- Young tokens: meaningful breakout/repricing structure rather than blindly using lifetime ATH/ATL

Every structure preserves both Wick High and Body High. The agent never silently changes methodology. Learning produces recommendations for Queen Bee review and beekeeper approval.

## v0.2.0 — the live zone watcher (Hive integration)

`src/zones.py` (zone classification), `src/structure.py` (deterministic Wick + Body structures, rules
in `config/defaults.json → structure_rules`), `src/watcher.py` (live loop), `fib_agent.py` (CLI).

```
python fib_agent.py watch            # every 15 min: research verdicts -> structures -> zones -> events
python fib_agent.py tick | status
python fib_agent.py structure --candles candles.json --price 0.012   # offline check
```

- **Watchlist** = newest `research.verdict` per asset with gate PASS, identity VERIFIED, rank BUY/WATCH.
- **Structure** = ATL (lowest low) → highest wick high / highest body high AFTER the ATL, needing at
  least a 2x expansion. Otherwise it's NEEDS_REVIEW or DATA_ERROR, and those never trigger anything.
- **Buy zone** (beekeeper setting `buy_zone`): NEZ + NDCAZ on BOTH structures. Price under the bottom
  means BROKEN (a new ATL), never a buy.
- **Events:** `fib.zone.entered` on the move INTO the buy zone (once per structure), `fib.zone.exited` on
  the way out. Transitions are appended to `hive_data/fib_agent/observations.jsonl` (immutable).
- **Data:** CoinGecko on-chain API when `COINGECKO_API_KEY` is set, otherwise keyless GeckoTerminal paced
  at 2.6s per call. A source failure is DATA_ERROR plus a Queen event, never "no data".
- Still no wallet and no trading permission. The Trader Bee decides what to do with a zone entry.
