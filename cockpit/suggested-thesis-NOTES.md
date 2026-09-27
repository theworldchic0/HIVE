# Suggested Plays — List B (Thesis Discovery) — sourcing logic + honest flags

**File:** `cockpit/suggested-thesis.json` · **Built:** 2026-07-21 by trade-idea-engine (List B) · **Read-only, data-only, no trades.**

## What List B is
20 NEW ideas (Jesse's current holdings excluded) that lean HARD into his stated "tokens I'd love" thesis
(`doctrine/jesse-what-i-love-thesis-2026-07-21.md`): Robinhood Chain + AI-finance/agentic + RWA + Virtuals
ecosystem + decentralized-AI, weighted UP for proven founders / prior-token-pumped / builders who switched to
Robinhood. This is explicitly the "what he WANTS to be shown" list, so it leans into the thesis rather than
away from his biases. Ordered by conviction (top = strongest fit).

## Excluded (his holdings, per the task): RAXOL, AI, BASTION, STONKBROKER, VEX, MLY, WOOD, KARMA, VIRTUAL
These were used only as thesis anchors (e.g. AI/NVDA = the AI+RWA template; WOOD = Sherwood cluster;
StonkBroker = meme-mixed-with-RWA; the held VEX/KARMA/MLY confirm the Virtuals-on-Robinhood meta).

## How each bucket was sourced
- **Robinhood Virtuals-ecosystem agent tokens (11 of 20):** enumerated by pulling every pool quoted against
  VIRTUAL on Robinhood Chain (`get_pools_for_token robinhood 0xc691...9c31`). VIRTUAL-quoted = the Virtuals
  agent-token meta Jesse called "very well positioned." Picks: ROBVIS, AGENTIQ, IN, NOVA, KAIRUNE, BOWYER,
  VIM, PRIZE, RYFT, PHOOD, HAN.
- **Robinhood agentic / AI-agent infra (AGENTOS):** found via a DexScreener sweep that surfaced a live cluster
  of Robinhood-Chain "Agent/Trading-Agent" tokens (XHOOD, WISP, Agent RH, Dregwise "Robinhood Trading Agent",
  AGENTOS, AGENTIQ, RHAGENT, AgenticHood, ZARDOZ). Most are <$25K liquidity / possible wash volume — I took
  only AGENTOS ($130K liq, deepest of the pure-agentic cluster). See honorable mentions below.
- **Robinhood meme-mixed-with-RWA / retail-culture / infra (PONS, TENDIES, CASHCAT, WALLET):** from GT robinhood
  trending. PONS = the pons.family launchpad/DEX token (infra/builder-on-Robinhood). TENDIES/CASHCAT/WALLET =
  the StonkBroker-style retail-trading-culture meme angle, chosen for deepest liquidity among RH memes.
- **Base proven-founder AI-finance + decentralized-AI (MAMO, TIG, aixbt, BNKR):** the heavy hitters for his #1
  driver (proven founder / prior pump). Sourced via DexScreener + CoinGecko ai-agents category. Base is welcome
  per the thesis ("Base/other-chain tokens that fit AI+RWA+proven-founder are welcome too").

## Decoy sanity pass (RAXOL/KARMA fake-liquidity signature) — RUN, and it mattered a lot
The signature: a token shows a large HEADLINE liquidity number but near-zero 24h volume, usually on a
duplicate/bridged contract, because the pool is imbalanced/dead (the RAXOL decoy = fake $2M liq/~$0 vol; the
KARMA clone = $185K headline vs ~$7 real backing). This pass changed which CONTRACT each Base name uses:

| Token | REAL contract used (live volume) | Decoys EXCLUDED (high liq / ~0 vol) |
|---|---|---|
| MAMO | Base `0x7300…19fE` ($460K liq / real vol) | Solana `2Cyw…pR4X` $153M liq / **$199** vol · ETH `0x68D0…1c61` $16.5M / **$0.01** |
| TIG | Base `0x0C03Ce…9F7B` ($1.16M / $319K) | Robinhood `0xa3EB…D21d` $26.7M / **$0.01** · ETH `0xa133…63Fe` $485M / **$0.01** · ETH `0xD15B…807c` $9.9M / $0.01 |
| AIXBT | Base `0x4F9F…A825` ($859K / $25K) | Robinhood `0xf616…245d` $1.9M / **$0.01** · Solana `9UGY…AYqd` $115M / **$199** · RH knockoff `0x3CfA…9BA3` |
| BNKR | Base `0x22aF…6F3b` ($1.84M / $328K) | Robinhood `0x2Eb4…F760` $19.3M / **$0.01** |

Every Robinhood suggestion was checked against the same signature; none of them show it (all have healthy
volume relative to liquidity). **HAN** is the one to watch: $701K liquidity but only ~$36K/24h volume (~0.05x
velocity) — that is LOW/faded, not the decoy pattern (the pool is real and two-sided), but flagged in the JSON.
**AGENTOS** and **Dregwise** each have a byte-similar squatter contract on-chain (classic RH pattern) — I used
the higher-liquidity live one for AGENTOS and left Dregwise out; token-vetter must confirm the exact address.

## Founder signals — what I could verify vs guessed (honest split)
Per the task I did NOT do deep team research (that's a future agent). Signals are readily-evident only:
- **reputation (4):** MAMO (Moonwell / Luke Youngblood / Sherwood cluster — from CoinPicks memory context, not
  fresh diligence), TIG (established decentralized-AI-innovation protocol Jesse named himself), BNKR (established
  Base agentic product), PONS (a shipped, working DEX/launchpad on Robinhood = proven-builder-on-hot-chain).
- **prior-token-pumped (1):** AIXBT — the aixbt token itself had a large prior run; this is the same-token pump,
  the clearest instance of Jesse's "founder's past token went up a lot" signal on the list.
- **unknown (15):** every Robinhood Virtuals/agent token + the 3 memes. Founders were NOT verifiable in this
  read-only pass. Do not treat "unknown" as negative — several are Virtuals-launchpad-native (ROBVIS, AGENTIQ,
  IN, NOVA…) which is a mild positive; it just means the founder-credibility work is still owed.

**Reliability caveat:** the MAMO founder-cluster claim leans on prior CoinPicks memory, and the aixbt "prior
pump" is well-known-but-not-re-verified-here. token-vetter/coinpicks-research should confirm both before any
conviction is assigned. All 4 "reputation" tags are directional, not audited.

## Other honest flags
- **ageDays:** exact for GT-sourced Robinhood tokens (from pool_created_at, relative to 2026-07-21). NULL for
  the 4 Base names + AGENTOS/AGENTIQ (DexScreener search didn't return pairCreatedAt; all are established or
  their age wasn't captured this pass). Several Robinhood picks are 0-1 days old (NOVA is hours old) = HIGH RUG
  RISK, surfaced anyway because they ARE the meta — vet before touching.
- **liquidity/volume for the 4 Base tokens:** liquidityUsd = deepest single pool; vol24hUsd = sum of the DEX
  pairs observed (token-level), so it is approximate. Robinhood entries use the single main-pool figures from GT.
- **Not a buy list.** No prices verified for slippage, no team diligence, no chart/level analysis. This is an
  ideas funnel; token-vetter resolves/greenlights contracts and coinpicks-research does fundamentals before
  anything is tradeable.

## Honorable mentions (thesis-strong but left off for data reasons)
- **KITE (Kite AI, agentic payments)** — strong AI-finance/agentic narrative and hot ($281M mcap on CoinGecko),
  but no clean canonical DEX contract: Solana `95qL…UtNm` shows $102M liq / only $55K vol (decoy-like low
  velocity), plus separate OP/BSC contracts. Too ambiguous to list cleanly; worth adding once a real market is
  resolved.
- **RECALL (decentralized-AI agent competitions, TIG-adjacent)** — fits the decentralized-AI love but no clean
  DEX pair surfaced this pass.
- **Robinhood agentic cluster: XHOOD, AgentWisp (WISP), Agent RH, Dregwise "Robinhood Trading Agent"** — dead-on
  the agentic-trading-ON-Robinhood thesis and very high velocity, but $3K-$25K liquidity and duplicate-contract
  patterns = too rug-prone / unverifiable for the curated 20. Strong watch-list once liquidity builds.
