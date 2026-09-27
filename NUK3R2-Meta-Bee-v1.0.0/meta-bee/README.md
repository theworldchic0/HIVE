# 📡 NUK3R2 Meta Bee v1.0.0: the nonstop meta hunter

Its job never stops: find the meta people are **trading right now**, and see where it's going on a
**daily, weekly and monthly** view. Hive id `narrative_agent` (the Queen's "Narrative / Meta Bee").

```
python metabee.py run        # forever (started by `python -m hive start`)
python metabee.py once       # every worker once + rollups
python metabee.py status     # the meta board: daily / weekly / monthly score + curve per meta
python metabee.py emerging   # repeated names that match NO meta yet (where new metas are born)
```

## Sub-agents (one per source, each on its own clock, each failing alone)
| Worker | Source (keyless) | Every | Measures |
|---|---|---|---|
| `cg_trending` | CoinGecko trending search (coins + categories) | 30 min | attention (what people look up) |
| `gt_trending` | GeckoTerminal trending pools: Base, Solana, ETH, Robinhood, BSC | 30 min | on-chain trading attention |
| `ds_boosts` | DexScreener boosts (**paid** attention, discounted) + newest token profiles | 15 min | launches and marketing pushes |
| `cg_categories` | CoinGecko categories: market-cap change + volume | 60 min | capital moving into a category |
| `llama_categories` | DefiLlama protocol TVL change by category | 6 h | real capital in DeFi metas |
| `reddit` | Reddit hot posts (off by default: keyless access is unreliable) | 60 min | retail conversation |

Every observation is kept (`hive_data/meta/meta.db`, 400-day retention). Hourly scores roll up into
**daily (24h) / weekly (7d) / monthly (30d)**. Each meta gets a curve per window (declining · flat ·
early rising · rising · accelerating · peaking · fading · revival) by comparing the current window with
the previous two. With fewer than two full windows of history the curve reads `insufficient_data`,
because it's never guessed.

- **Meta shifts** (a meta turning early rising / rising / accelerating / revival on the daily view) are
  published as `meta.shift` on the Hive bus and shown in the UI.
- **Emerging unclassified:** names repeating across sources that match no meta in the taxonomy. Add a
  new meta to `config/meta.json → metas` (name, keywords, CoinGecko categories, DefiLlama categories).
  The running Bee picks it up without a restart.
- **The Research Bee** includes the matching metas' curves in every report as *supporting evidence*
  for the narrative curve (§7). It's evidence, never the score, and never a trade trigger.

## More free sources (researched; not wired until you choose)
Terms change often, so confirm current limits before adding a key.
| Source | Access | What it would add |
|---|---|---|
| CryptoPanic | free developer API key | crypto news aggregation per coin, with community votes (news repetition) |
| Santiment | free tier (limited, delayed) | social volume + dev activity per asset |
| Dune | free tier credits | custom on-chain SQL (e.g. new-token launches per launchpad per day) |
| Birdeye | free API key tier | Solana trending tokens + volume |
| Neynar (Farcaster) | free tier key | Farcaster casts per keyword (crypto-native social) |
| Google Trends | no official API (unofficial libraries break often) | search interest per plain-language keyword (§7C) |
| X API | pay-per-use (already in the key walkthrough) | posts per keyword / founder tracing |
| Elfa | paid credits (already in the key walkthrough) | crypto social signal |
| LunarCrush, Kaito | paid | social / mindshare analytics |

The keyless workers above run today with zero keys. Adding any of these is a new worker function plus
a row in the key walkthrough.
