# 🔭 NUK3R2 Discovery Scout v1.0.0

The automated front of the Research Bee: the 6-hour Base + Robinhood Chain discovery scan.

```
python scout.py run | watch | queue [--all] [--json] | dismiss <symbol|asset_id> [--reason ".."]
```

**Every 6h:** GeckoTerminal (or CoinGecko on-chain with your key) **trending + new pools** on Base and
Robinhood → keep the token side that isn't WETH/USDC/USDG/cbBTC/DAI/USDT → filters (config/scout.json):
liquidity ≥ $50K, 24h volume ≥ $25K, pool 24h–120d old, ≥50 buys/24h, buy/sell ratio ≥ 0.6, no zero-sell
tokens, 24h move ≤ ±400% → deepest pool per token → new ones published as `research.request` + queued.

- Ordered by `scout_score` (turnover + buyer share + depth). That's **queue order only, not quality**.
- Same-ticker tokens surfacing together are flagged (the VEX/DRB/WOOD clone lesson).
- When research publishes a verdict for a queued token, it moves to RESEARCHED automatically. It can
  resurface after 30 days if still active.
- **Never** verifies identity, scores, publishes verdicts or trades. Nothing it finds reaches the
  Trader Bee until your research PASSes it.
- A source failure is reported (Queen event + `errors` in the run summary), never read as "nothing found".
