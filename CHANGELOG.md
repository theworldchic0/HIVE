# CHANGELOG

**Newest first. The version IS the date** (see `VERSION` — which also maps the
old v1–v5.2 labels to their dates). "Which build am I on?" →
`node module/doctor.mjs`, line 2.

## 2026-07-31 — current build: "the setup release"
The zip that gets you from download to trading without a support thread.
- **THE SETUP AGENT, v2** (`.claude/skills/setup/SKILL.md`): three modes —
  SETUP (fresh install, resumable across sessions via SETUP-STATE.md),
  UPGRADE (new zip without losing keys/wallet/history), DOCTOR (diagnose +
  fix, any day). Every step live-verified: keys tested with real calls,
  wallet by derived address, data path by fresh timestamp, one dry-run trade
  end to end. Never arms, never places a real order, never accepts a private
  key in chat. New: an expectations briefing for first-timers (terminal, API
  portals, KYC, honest costs) and the DAY-ZERO FUNDING rule — start your
  ACH deposits FIRST (Robinhood ≈5 business days; Coinbase similar) so the
  money clears while you set up instead of after.
- **VERSIONS FIXED FOR GOOD**: `VERSION` file in the root (the date is the
  version, newer wins, full old-label history inside), printed by the doctor,
  recorded at setup. No more "is v3.1 newer than v3?".
- **SAFE UPGRADES**: `module/upgrade.mjs` + `UPGRADING.md`. Never extract a
  zip over your install — extract fresh, run the tool, and it carries your
  wallet.key, .env, registry, config, caps, exclusions, sentinel rules and
  trade ledgers old → new (dry-run report first, `--apply` to do it, your
  old folder untouched as the rollback). Also flags new-build registry rows /
  config settings your carried files lack, and any extra files you created.
- **Chrome-first launcher**: `TRADING-DASHBOARD.command` opens the dashboard
  in Chrome when installed (it's what the dashboard is developed against);
  your default browser stays yours.
- **Best-execution transparency**: the route scan under every trade — live
  pool census, fake-liquidity filter, both aggregators quoted, winner shown —
  now renders **USD-first** on every venue card (≈$ out big, token amount
  beneath; sells exact via the dollar stable, buys valued at the same live
  pool mid the census pulled, never a promised fill).
- **⛽ ETH-SPEND switch** (`config.ethSpend`): native/wrapped ETH can fund
  MARKET orders (no-approval native path, gas reserve never spendable);
  limit orders deliberately refuse ETH funding (price-drift reasoning,
  enforced). Canonical ETH sentinel rows ship in the registry.
- **The full research doctrine ships** (`doctrine/research/`): JESSE-DOCTRINE,
  VALUE-DECOMPOSITION, SOURCE-QUALITY, ERROR-LOG, PROCESS-DELTAS + reading
  order, plus `Research/framework/00-how-we-think.md` (chain-purpose
  valuation, the accrual test, discovery premium, liquidity-as-thesis,
  quotes-are-not-fills). Method, never financial advice.
- **Trade-call agent** (`.claude/skills/trade-call/SKILL.md`): authors YOUR
  buy/sell write-ups from your own words per
  `doctrine/research/BUY-SELL-CALL-INSTRUCTIONS.md`. A journal, not advice.
- **`cockpit/FIXES-LOG.md` ships** (redacted): every production failure, root
  cause, fix, and how it was verified.
- Suggested-lists relabel (A/B/C), `suggested.html` script regression fixed
  and browser-verified; route-scan code consolidated onto `route-scan-ui.js`
  (an inline copy anywhere is a regression).
- X/Twitter access truth in `.env` + docs: no key here by design, official X
  API via MCP outside this folder, X Premium does NOT help, pay-per-use
  (~$0.005/post read) since Feb 2026.

## 2026-07-26 (was "v5.2") — screenshot-safe doctor
- The doctor MASKS keyed RPC URLs before printing ([KEY_HIDDEN]) in the
  chain-reachable lines, success and failure both — doctor output is what
  people screenshot into chats for help, so it is now safe to share by
  construction. Public RPC URLs print unchanged; checks still use the real
  URL. (Community report; verified and fixed same day.)

## 2026-07-26 (was "v5.1") — the community-review hardening
Every claim in the first community bug report was independently verified
against the code before anything changed (two suggested fixes were rejected
as harmful; the rest confirmed):
- SECURITY: Alchemy key can no longer appear in any error/log (redaction at
  BOTH call sites + fail-fast host validation killing the leak path at root).
- SECURITY: the Coinbase venue module's documented {confirm:true} gate is now
  real — importing the module can never place an order without it.
- The vet-lite provisional $25/order cap is enforced in swap.mjs and arm.mjs
  too, not just the cockpit.
- The shipped ledger config was missing its chains + priceCounters blocks
  (silently broke ingest on every fresh install) — restored; ledger now
  fails LOUD.
- Sentinel take-profit rules use each chain's own dollar stable.
- check-orders defaults to your actual wallet roster; starter PLAYBOOKS.md
  ships.
- WETH/ETH-funded router fills WARN with tx id + manual-add path.
- Optional Claude dictation parsing documented (SAFETY.md + .env + doctor);
  1inch router allowance documented with revoke path.
- Chains beyond Robinhood Chain + Base say "not set up yet"; CLAUDE.md
  carries the full "Adding a new chain" recipe.

## 2026-07-24 (was "v5") — the complete system
- **THE DOCTOR**: `CHECK-SETUP.command` + `module/doctor.mjs` — 12 checks
  with REAL calls; every failure prints its exact fix.
- **WALLET ONBOARDING WIZARD**: `module/setup-wallets.mjs` — import or
  generate (key never displayed); every choice recorded in SETUP-STATE.md.
- **CONSCIOUS-SKIP SETUP**: no step silently passed; optional steps require
  typing SKIP after hearing what stops working; SETUP-STATE.md is the trail.
- **RESEARCH INCLUDED**: `Research/` — the 5-system framework, screening
  filter form, live market-data MCP server, wired to the vet gate.
- Terminal upgrades: sorting + long-term toggle; fresh buys always visible;
  fear buttons; "sell all" language; floored sell quantities; %-of-bag sells
  sized live at execution; tokenized-stock namesakes recognized; "10$%"
  garble parsed; one paste-and-vet surface.
- Fail-loud ledger ("LEDGER IS BLIND" + fix, instead of a quiet skip).

## 2026-07-24 (was "v4")
- VET-FIRST suggested lists: every suggestion card locked behind a VET button;
  CLEAR unlocks dictation box, QUICK BUY, Ladder Designer.
- CEX cards fixed (Coinbase-venue positions admitted); spam-price kill
  (<$1K-liquidity pairs can't mint valuations); watch-only custody honesty.
- Coinbase Setup rewritten from a live walkthrough of the redesigned portal.
- PROVEN: this build's Coinbase lane executed a real exchange order (filled,
  verified by order id) before shipping.

## 2026-07-24 (was "v3")
- COINBASE EXCHANGE TRADING: venue socket (module/venues/) + coinbase adapter
  (Advanced Trade REST, six verbs, server-side previews) + cex.mjs CLI +
  full cockpit wiring; whitelist + cap + per-trade confirm in two layers.
- GUARANTEED FILL vs BEST PRICE execution methods on market legs.
- Failure honesty on cards; poison-pair guard extended to swap.mjs.

## 2026-07-23 (was "v2")
- Tutorial-first packaging (CLAUDE.md wizard + SETUP-CLAUDE.md runbook +
  auto-loading skills).
- Ladder designer v2 (chart + draggable rungs on real support levels).
- Poison-pair guard; ladder-design pattern capture; moonbag sentinel
  heartbeat; dictation parser hardening; market sells + venue race;
  check-orders.mjs; funding-calc.mjs shipped; SAFETY/KNOWN-ISSUES/BRIEFING.

## 2026-07-22 (was "v1") — Altcoin-Trading-System-Base-Robinhood.zip
- First portable two-chain build: engine, cockpit dashboard, sentinel,
  ledger, 3 skills, launcher, SETUP.md.
