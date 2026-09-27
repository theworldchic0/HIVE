# 🔬 NUK3R2 Research Bee v1.0.0 (Phase 1, Narrative Intelligence Edition)

Paste a ticker in Claude Code (inside the Hive folder) and get your full Phase 1 research:

```
/nuk3r2 PONS
/nuk3r2 HOOKR | Robinhood Chain
/nuk3r2 0xCONTRACT
```
or just type "research PONS". The `nuk3r2-researcher` subagent runs the method (`METHOD.md`, your
document, preserved in full) step by step and hands you a one-page report.

## How it's split (facts vs judgment)
| Step | Who | File |
|---|---|---|
| Facts: identity, pools, liquidity tier, DefiLlama TVL/fees, Coinbase listing, explorer, official site, GoPlus, BTC cycle context, BTC-benchmark since the halving, Meta Bee context | `collect.py` (deterministic, keyless) | `evidence.json` |
| Judgments: gate, narrative, Shiller /14, stage and curve, constellation, archetype, asset expression, team, smart money, decision | Claude (the subagent), with evidence for every score | `scorecard.json` |
| Math + evidence enforcement + report + Hive verdict | `score.py` | `report.md`, `verdict.json`, `scores.json` |

All three land in `hive_data/research/<TICKER>-<chain>-<time>/`, so every report stays auditable.

## Rules the code enforces
- **Identity = chain + contract.** VERIFIED needs an identity anchor (CoinGecko's platform mapping or
  the contract printed on the official site) plus ≥2 sources. Same-ticker contracts are listed as decoys.
  AMBIGUOUS or UNRESOLVED stops the research until you pick (`--pick N`).
- **The gate is absolute:** under 16/30 the decision must be PASS and the verdict is FAIL.
- **No evidence, no score** (§21). Revival without a named catalyst is refused. Every material team
  claim needs a source; pseudonymous = UNVERIFIABLE (scores 0, flagged).
- **Two audited fixes:** Stage is mapped to timing points (a fading story can no longer out-score an
  early one), and the liquidity tier bands close the $200K–$1M gap (R-10).
- **Opportunity Matrix → Hive confidence:** Exceptional (45/17) → high → **$10** · Priority (40/13) →
  medium → **$5** · anything else → low → **$1** (discovery buys only).
- **Nothing publishes itself.** You read the report; then `python -m hive publish --type research.verdict --file …/verdict.json`
  (or tell Claude "publish it", which uses the `hive-verdict` skill).

## Sources
Keyless: DexScreener, GeckoTerminal, CoinGecko public API (your key when set), DefiLlama, Coinbase
Exchange public data, Blockscout explorers (Base/Ethereum/Arbitrum), GoPlus, official project sites.
Claude adds web research (news, docs, team history) through WebSearch/WebFetch. DefiLlama's MCP
server needs a paid DefiLlama API plan, so it's optional: the free REST endpoints are used by default.

## Tests
`python -m pytest -q tests`: identity + decoy rejection, the no-anchor stop, chain and contract
queries, broken-source reporting, the full score → verdict → report path, the stage-timing fix, evidence
enforcement, gate absoluteness, revival-needs-catalyst, unverified identity blocking.
