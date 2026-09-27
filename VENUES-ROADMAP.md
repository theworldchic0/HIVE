# VENUES ROADMAP — one execution layer, pluggable venues
_Created 2026-07-24 from Jesse's dictation (doctrine/jesse-verbatim-2026-07-24-venues-plugin-vision.md). This activates ROADMAP.md Phase 2. Living file: check boxes as phases land._

## >>> EXECUTING-CLAUDE BRIEF (second account) — read this first
You are building Phases 1, 2, and 4 ONLY. You have no memory of this system: read
`SYSTEM.md` (the tool registry — NEVER optional for a build session), `STATE-OF-PLAY.md`,
project `CLAUDE.md`, `Trading-Engine/cockpit/DASHBOARD-NOTES.md`, `module/swap.mjs`,
`module/arm.mjs`, and `ONBOARDING.md` in full before writing code.
Ground rules:
1. The live system is ARMED on port 8789 with real resting orders. NEVER restart that
   server, NEVER touch `module/.env` or any `.key`/key file, NEVER place, cancel, or
   preview-with-GO any order without Jesse's explicit per-trade OK in chat.
2. COLLISION RULE: file claims are LIVE in `.cowork/COWORK-LOG.md`, not frozen in
   this document — check the latest CLAIM/RELEASE lines there before touching anything.
   As of 2026-07-24 the main session holds `cockpit/trade-idea.mjs`,
   `cockpit/dashboard.html`, and `module/swap.mjs`. You do NOT edit claimed files
   (your dex adapter SHELLS OUT to swap.mjs/arm.mjs; it never edits them). Your Phase 1 socket lives entirely in NEW files
   (`module/venues/*`, `module/venues.json`, `module/cex.mjs`); the thin routing hook
   into trade-idea.mjs is Phase 3, which is CLAIMED by the main session and out of your
   scope. If you believe you must touch a claimed file, write a CLAIM line in
   `.cowork/COWORK-LOG.md` and STOP for coordination.
3. Test against a DISARMED server on a spare port (DASH_PORT env), never 8789.
4. Registry/whitelist writes and any live canary order are proposed to Jesse, never
   self-approved. Precision rules apply: verify against the API/chain, label guesses,
   log to COWORK-LOG with dated entries, no em dashes.
Phase 0 decisions below are Jesse's; if unanswered when you start, build everything
that does not depend on them (the socket, the adapter against Coinbase's sandbox/
preview endpoints, the CLI, the skill skeleton) and stop at the first blocked step.

## The shape (why this is plug-and-play forever)
One rule makes every future venue a bolt-on: **every venue is one adapter file
speaking the same six verbs, and nothing above the adapter knows which venue is
underneath.** The parser, the confirmation card, the ARMED gate, the confirm
token, the per-order cap, the logs: all venue-agnostic, all already built.

    Trade Idea panel / skills / ladder designer
                 v
    trade-idea.mjs (parse -> route by token row -> confirm card)
                 v
    module/venues/<name>.mjs  <- the ONLY venue-specific code
      six verbs: marketBuy, marketSell, limitBuy, limitSell, cancel, status
                 v
    orders-log.jsonl -> ledger -> dashboard P&L (already venue-tolerant)

Adding PONS-native, Binance, Hyperliquid later = write ONE adapter file + one
row in venues.json + a key in .env. Zero changes anywhere else. (Same thin-
integration law that wrapped 1inch: if a venue dies, delete its file.)

## THE COINBASE PATH THAT ALREADY EXISTS (read before building anything)
Added 2026-07-24 after review: the first draft of this roadmap MISSED this entirely.
Two facts that must never be read apart:
1. **The Coinbase EXCHANGE is already driven today**: the `buy-ladder` skill
   (`~/.claude/skills/buy-ladder/`, account-level) + the `coinbase` MCP connector
   (`~/.claude.json`, Ed25519 key in the keychain) place, edit, and cancel REAL
   resting limit orders on Coinbase right now (SYSTEM.md Section 4, status LIVE;
   a real limit buy has rested there since 7/09). A separate-account Claude
   cannot see those stores — that is WHY the first draft missed it, and why this
   section exists in a project file.
2. **The Coinbase in-app DEX wallet can NEVER be driven** (permanent finding,
   doctrine/coinbase-dex-wallet-finding-2026-07-23.md). Do not confuse the two:
   exchange = driveable and already driven; in-app DEX wallet = watch-only forever.
   The cockpit UI must not imply in-app-wallet bags (e.g. REPLY) are tradeable here.

**Why the REST adapter is still the right build:** the dashboard server and fire
scripts are plain Node processes with no MCP client — they physically cannot call
the coinbase MCP. Cockpit-driven CEX trading requires the direct Advanced Trade
REST adapter this roadmap builds.

**End-state reconciliation (one execution layer, no drift):** once
`venues/coinbase.mjs` is live and verified, the venue adapter becomes THE ONLY
code that talks to Coinbase orders. The `buy-ladder` skill is then rescoped as a
laddering front-end that routes through the venue (or subsumed into the venue
skill) — Jesse rules on which at Phase 4; a second drifting Coinbase-order
implementation is not an acceptable end state. Phase 4's new skill must state
its boundary against buy-ladder explicitly.

## Phase 0 — Jesse's calls (blocking, ~10 min of his time)
- [ ] **API key:** mint a FRESH Coinbase Advanced Trade key for the cockpit,
      permissions: view + trade, NO transfer, spot only (recommended), saved as
      `module/coinbase-trade.json`. (Alternative: reuse the MCP's CDP key; not
      recommended, blast-radius separation is worth 5 minutes.)
- [ ] **Product whitelist:** which Coinbase products can trade at launch (the
      CEX equivalent of registry.json). Suggest: current Coinbase holdings + an
      explicit list he names. Fat-finger protection, same law as DEX.
- [ ] **CEX per-order cap:** DEX maxUsdPerOrder is currently 1000000 (cap removed
      per Jesse 2026-07-23). A CEX account holding real USD is a different blast
      radius: same no-cap, or a dedicated CEX number? (Recommend starting capped.)
- [ ] **Zip delivery:** skill-only add-on folder for the hedge fund, or re-cut
      a full v3 zip? (Skill-only is faster; v3 keeps one artifact.)

## Phase 1 — the venue socket [STARTED 2026-07-24 by MAIN session per Jesse's direct order — second account: your scope is now Phase 4 only, after Phase 2 verifies live]
- [x] `module/venues/` + `venues.json` (installed venues, routing rules). BUILT 2026-07-24.
- [x] `venues/dex.mjs`: wraps the EXISTING swap.mjs/arm.mjs as the first
      adapter (shells out; internals untouched). BUILT 2026-07-24, syntax-checked.
- [ ] trade-idea.mjs routes by token row (registry rows gain optional
      `venue`; default dex = zero behavior change).
- [ ] REGRESSION GATE: all 4 DEX primitives dry-run + full parser suite pass
      IDENTICALLY before anything CEX lands.

## Phase 2 — the Coinbase adapter (~1 day)
- [x] `venues/coinbase.mjs`: six verbs on Advanced Trade REST — BUILT 2026-07-24; view verbs VERIFIED LIVE (live quote, open orders found a real resting buy, server preview returned real fees w/ the read-only key); order verbs refuse until the trade key lands. (JWT, same auth
      pattern as the read-only balances module). Preview-first is NATIVE
      (Coinbase has a preview endpoint) -> DISARMED = preview, same as DEX.
- [x] `cex.mjs` CLI twin of swap/arm — BUILT 2026-07-24; whitelist gate + cap + view-only refusal all verified live (same flags, same preview + GO contract)
      so terminal + fire-script workflows work identically.
- [ ] Same gates, same config: per-order cap (see Phase 0 CEX-cap decision),
      whitelist, ARMED, per-trade confirm token. orders-log rows carry
      venue: "coinbase".
- [ ] **P&L wiring is REAL work (corrected 2026-07-24, was overstated as free):**
      ledger/sources/coinbase.mjs does ingest raw Coinbase fills (916 rows), BUT
      the cockpit's realized/closed-position pipeline excludes Coinbase by design
      (history.mjs has zero Coinbase handling; the closed-positions table says
      "on-chain venues; Coinbase not included"; cost basis uses a fragile
      symbol+quantity-window heuristic in datasource.mjs). Budget the wiring —
      and claim the upgrade: cockpit-placed CEX orders carry their own order id,
      so the fill join becomes clean id-linked instead of the heuristic.
- [ ] Verify: preview both sides both order types; then ONE tiny live limit
      far from market, verified via orders_list + cancel, with Jesse's GO.

## Phase 3 — cockpit wiring (~1 day)
- [ ] Coinbase holdings become TRADEABLE cards (they already render read-only):
      Trade Idea panel + QUICK route to the coinbase venue automatically.
- [ ] Dictation unchanged: "buy $50 of TOKEN at 8.50" just works; the card shows
      the venue ("on Coinbase" / "on-chain via 1inch race").
- [ ] Open CEX orders on cards + Levels chart lines; check-orders.mjs gains
      coinbase status; candles for CEX symbols from Coinbase (GT fallback).
- [ ] Ladder designer on CEX symbols (stage -> N coinbase limit orders).
- [ ] Sentinel stays DEX-only in v1 (CEX TP top-ups = later, deliberate).

## Phase 4 — the skill + hedge-fund package (~half day)
- [ ] `coinbase-trade` skill (same contract as the 3 DEX skills: whitelist
      gate, preview verbatim, explicit GO, report the true fill from the API).
- [ ] Package per Phase 0 decision (skill add-on folder w/ its own SETUP
      appendix: key creation walkthrough, permissions, whitelist; or v3 zip).
- [ ] Stranger-test the setup doc; secrets sweep; ship.

## Phase 5 — future venues (PARKED until a venue is real; birth-rule pattern)
- Each candidate gets a one-page intake before code: auth model, preview
  support, order types, cancel semantics, rate limits, ToS check (official
  APIs only, always). Then: one adapter file + one venues.json row.
- Named candidates from Jesse: PONS-style native interface (if they ship a
  plugin/API), Binance, Hyperliquid. Build NONE until he points at one.

**Total estimate: ~3 focused days across sessions. Money-now check: Jesse
trades Coinbase today (a resting exchange order, idle USDC, the boss kit audience);
this closes the loop between both halves of his real trading.**
