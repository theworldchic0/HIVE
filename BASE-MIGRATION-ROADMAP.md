# BASE MIGRATION ROADMAP — "all my tokens under the engine" (born 2026-07-23)

**Jesse's why (his words):** "I'm going to get to go through all my coins, which I already
should have TP levels for as well as different buy levels. Two, I'm going to get to build out
this system with you. Three, it's all going to be set up skill-wise for a zip folder that I
can zip up and send to my boss so we can use it for the hedge fund as well."

**SESSION HANDOFF PROTOCOL:** any session picking this up reads `STATE-OF-PLAY.md` first,
then this file. The checkboxes below ARE the state — update them the moment a step lands,
and stamp the "last touched" line. If this file and reality disagree, fix the file.

_Last touched: 2026-07-24 ~17:30Z (Fable, main). Phase 0: address traced + watch-only ADDED; inventory live-pulled; Phase 1 walkthrough started with Jesse._

---

## THE DESTINATION WALLET (never guess this)

**wallet-2 = `0xYOUR_TRADING_WALLET`** — the engine's
execution wallet on BOTH Robinhood Chain (4663) and Base (8453). Confirm it is YOURS by a
holding only you would recognize before any migration send.
Its key lives in `module/` key files; MetaMask is just a UI onto it.

## STANDING FACTS THIS PLAN RESTS ON (all verified 2026-07-23, sources in doctrine/)

- The Coinbase in-app DEX wallet can NEVER be engine-driven (no API, no key export, key in
  phone secure enclave). Watch-only is possible once Jesse supplies the address. Escape:
  plain SEND per asset, or Settings→Eject (irreversible, last resort).
  → `doctrine/coinbase-dex-wallet-finding-2026-07-23.md`
- MetaMask/wallet-2 hot-wallet risk is really MAC + key-file risk; hygiene rules in the same
  doctrine file (FileVault, no synced key folders, approval revokes, sweep profits off the
  engine key).
- Engine Base support is BUILT (arm/swap/registry/cockpit/sentinel all chain-aware);
  ⚠️ **first LIVE Base order still needs Jesse's one-time explicit OK** — not yet given.
- Claude STAGES trades; JESSE fires them (hard rule).

---

## PHASE 0 — unblockers (in progress)

- [ ] Jesse sends the Mr. Rickey VIP-concierge message (drafted in chat 2026-07-23) — if
      Rickey reveals an official automation path we missed, STOP and re-plan before migrating.
- [x] DEX wallet address resolved WITHOUT waiting on the app: the 2026-07-21 trace
      (`0xYOUR_COINBASE_DEX_WALLET`, REPLY qty matched the app buys to
      the digit) — ADDED to `cockpit/wallets.public.json` watch-only 2026-07-24. Jesse
      can still eyeball-confirm the address in the app's explorer links.
- [ ] REPLY registry row: vetter CLEAR 2026-07-23, row PROPOSED (contract
      `0x05B1266DDCeE093cE060DBF697e230EA9B453633`, main pool REPLY/VIRTUAL uni-v2
      `0x68b34fd640ee48e93b9d81eaf4cbd4e489d5d17f`, POOL HAZARD: never route the stale
      REPLY/USDC v3 `0xd382d910...`). AWAITING JESSE'S OK TO WRITE to registry.json.
- [ ] Jesse's one-time FIRST-LIVE-BASE OK (can be given per-trade at the first Base confirm).

## PHASE 1 — migrate the tokens (Jesse's hands, one token at a time)

Per token, in this order — do NOT batch-send everything at once:
1. [ ] Send a SMALL TEST amount from the Coinbase app to your trading wallet,
       waits for it to appear on the dashboard (auto-scan ≤60s, or "refresh now").
2. [ ] Verify the received contract byte-matches the vetted registry contract (guards
       against Coinbase listing a different bridge/wrapper of the same name).
3. [ ] Jesse sends the remainder.
4. [ ] **Cost-basis capture at transfer time** (the AI-consolidation lesson): transfers
       arrive basis-less. Jesse reports what he PAID on Coinbase (buys from the app's
       activity screen — screenshots fine) → ledger rows added transfer-at-cost →
       coverage back to 100%. The durable datasource self-transfer fix is still a pending
       chip; until it lands this step is manual and MANDATORY per token.
5. [ ] token-vetter pass if the token isn't already vetted → registry row → Jesse OK.

Token inventory: live-pull YOURS at migration time (Alchemy + DexScreener,
median-filtered) and list it here as checkboxes — token, quantity, ≈USD, contract, pool
liquidity. Move the biggest position first AFTER the small test lands. Expect most contracts
in an old wallet to be spam/dust: ABANDON those deliberately — never interact with spam
tokens, not even to send them away. If wallet native ETH = 0, sends rely on Coinbase's
sponsored/fee-in-asset gas (4337 wallet); if the app asks for ETH gas, add a tiny ETH send
step first.

## PHASE 2 — levels + ladders per migrated token (the practice loop Jesse wants)

Per token, the loop is:
1. [ ] Claude finds technical levels (OHLCV supports/resistances; candidate: formalize the
       volume-candle bottom method — see ⏰ reminder in STATE-OF-PLAY).
2. [ ] Jesse opens the 🪜 Ladder designer on the token's card → sets the risk slider
       (5/4/3 rungs, 0.01%–10% allocation, escalating sizes; thin-pool tokens auto-default
       defensive) → drags Claude-suggested lines where he wants them.
3. [ ] Stage → "So you want to do this?" card → JESSE fires.
4. [ ] TP ladder dictated (compounding-remainder doctrine, moonbag stated) → fired by Jesse.
5. [ ] Sentinel top-up rule added for the token (sells-only, Jesse pre-approves the exact
       fractions per rule) → `cockpit/sentinel-rules.json`.
Progress: (none yet — starts after first Phase-1 token lands)

## PHASE 3 — venue-race upgrade (fallback depth)

- [x] Research delivered 2026-07-23: **verdict = direct 0x Swap API v2 for BOTH chains,
      skip CDP Trade API.** Decisive facts (all sourced, full report in COWORK-LOG/chat):
      CDP does NOT support Robinhood Chain 4663 at all (Beta, 5 chains, unpublished
      limits/fees, renamed once, demonstrably lags 0x on chain additions); 0x direct
      supports Base AND 4663 and is the DOMINANT aggregator on 4663 (~$46.5M/day verified
      via DefiLlama, day-one Robinhood Chain launch partner, 8+ yrs old, published pricing
      + status page). Coinbase's product is a thin wrapper ON 0x — under the "pick the
      people doing it best" doctrine, that's 0x itself. Fee note: 0.15% on SELECT pairs
      only, returned inside the quote (race stays apples-to-apples). Limit orders: dead at
      0x (v1 orderbook sunset 2025), none at CDP → 1inch keeps the orderbook job.
- [ ] Jesse creates a free 0x API key (0x.org dashboard, email signup — bring-your-own-key
      per portability law) → drop in `module/.env` as `ZEROX_API_KEY`.
- [ ] Wire `quote0x()` as lane #3 in the market-swap race on BOTH chains (same
      quote-returns-calldata shape as 1inch/Kyber; one extra AllowanceHolder spender
      approval per token; watch free-tier RPS ~5-10/s across 3 lanes). Est. half a day.
- [ ] Dry-run race on small size; verify zeroExFee-inclusive amounts compare honestly.
- BACKLOG (parked by Jesse, raw words in
  `doctrine/jesse-verbatim-2026-07-23-holdings-page-and-cex-backlog.md`):
  CEX/Coinbase order integration; HOLDINGS page (4th nav page, %-of-portfolio breakdown).

## PHASE 4 — hedge-fund zip for the boss

- [ ] Refresh the portable system zip with everything since 2026-07-23 morning (ladder
      designer, card search/pin, live-only strips, confirmation cards, loading bars,
      sentinel, venue upgrades, this roadmap as a doc) — secrets-swept, boot-tested, same
      standard as `~/Desktop/Altcoin-Trading-System-Base-Robinhood.zip`.
- [ ] Boss-facing README updates (the designer + confirm flow are the demo).

---

## WHERE WE LEFT OFF (update every session)

2026-07-23 ~16:45Z: Phase 0 — Rickey draft delivered to Jesse; waiting on the DEX wallet
address + REPLY registry OK + Jesse starting transfers. CDP-vs-0x research agent running.
Nothing migrated yet.
