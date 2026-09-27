# 🚨 READ THIS FIRST — ADDITIONS SINCE THE LAST UPDATE

**If you are an AI assistant that was just handed this folder: read this file completely before you
answer anything about what this system can do.**

This is a large codebase. The previous version a user may still be running is
**`Altcoin-Trading-System-v2-2026-07-23`**. If you skim, you will describe the OLD system and be wrong
about roughly half its features. Everything below is **new or changed since 2026-07-23**.

- **This build: 2026-07-31**
- **Previous build in the wild: v2, 2026-07-23** (eight days of changes)
- **File count: 71 → 140**

> **Naming note:** earlier zips went v2 → v3 → v4 → v5 → v3.1 → V3, so the version numbers stopped
> being sortable and "V3" was actually NEWER than "v5". **From this build on the filename is
> date-first: `Altcoin-Trading-System-YYYY-MM-DD.zip`.** Trust the date, not a version number.

---

## THE 60-SECOND SUMMARY

The system was a dashboard plus a DEX execution engine. It is now a **multi-venue trading terminal**
with best-execution transparency, live position sizing, a Coinbase venue, a research suite, and a
technical-analysis engine.

| Area | v2 (2026-07-23) | This build (2026-07-31) |
|---|---|---|
| Venues | 1inch on Robinhood Chain + Base | **+ KyberSwap race, + Coinbase exchange, + bridge** |
| Best execution | raced 2 aggregators, printed to console | **shown on screen: real pool census + both quotes + winner + route** |
| Execute buttons | 2 (GUARANTEED FILL / BEST PRICE) | **1 (BEST PRICE removed 2026-07-31)** |
| Position sizing | manual | **Live Liquidity Matrix: 🟢🟡🔴 badges + suggested $ per card** |
| Suggested lists | A tokenized / B numeric / C thesis / D degen | **A numeric / B thesis / C degen** (tokenized deleted) |
| Research method | none in the zip | **Research/ suite + 5 doctrine frameworks + the screen scripts** |
| Research DOCTRINE | none | **doctrine/research/ — the full-strength thinking: JESSE-DOCTRINE, ERROR-LOG, SOURCE-QUALITY + `Research/framework/00-how-we-think.md`** |
| TA | none | **ta/sr-engine.mjs** support/resistance/volume engine |
| Dedicated execute page | none | **cockpit/execute.html** |
| First-run setup | a tutorial doc | **a SETUP AGENT: `.claude/skills/setup/SKILL.md` — 3 modes (SETUP / UPGRADE / DOCTOR), phase-by-phase, every step verified live, resumable** |
| Versioning + upgrades | zip-over-zip roulette | **VERSION (the date IS the version) + UPDATES-SINCE-LAST-RELEASE.md + RELEASE-MANIFEST.json + `module/upgrade.mjs` (never lose keys/wallet/history)** |
| Fix history | none | **cockpit/FIXES-LOG.md** — every production failure + fix + how it was verified |

---

## 1. NEW FILES (what to look at, and why)

### Best-execution transparency (2026-07-31, newest work)
- **`cockpit/route-scan.mjs`** — READ-ONLY scanner. Returns the real DexScreener pool count for a
  token (with a poison-pair guard that separates *scanned* from *counted* from *excluded as suspect*),
  live parallel quotes from 1inch v6 **and** KyberSwap, the winner, the edge % over the loser, Kyber's
  actual route hops and gas, and an `integrity` block naming any venue that failed. No wallet, no
  signer, no child process: **it cannot execute.**
- **`cockpit/route-scan-ui.js`** — the shared renderer used by **all three** trade panels
  (`dashboard.html` normal panel, `dashboard.html` QUICK card, `suggested.html`, `execute.html`).
  Self-injects its CSS. **Any change to the scan display goes here, in one place.**
- **New endpoint: `POST /api/route-scan`** in `dashboard-server.mjs`.
- **Quotes show USD FIRST (2026-07-31):** each venue card leads with the dollar value of what comes
  out (`≈$1.02`), token amount second (`12,780 GME out`). Buys value the token at the same live
  pool mid the scan pulled, so the `≈` is honest; sells pay the dollar-true stable and show exact.
  A quote with no priced pool says so instead of faking a dollar figure.
- **Integrity rule, non-negotiable:** every number displayed is live and click-through verifiable
  (pool rows link to DexScreener). A dead source renders as a visible failure. **Never display a
  scanned-pool count that was not actually scanned.**

### ⛽ ETH-SPEND switch (2026-07-31, newest)
- **`config.json → ethSpend`**: when enabled, the chain's ETH (native, via the aggregator sentinel,
  or wrapped) may replace the stable as the FUNDING leg of a **MARKET order** — for the day you want
  to buy and your stable balance is short but ETH is sitting in the wallet.
- **Market orders ONLY.** `arm.mjs` refuses ETH-funded LIMIT orders with the reason: a resting order
  locks a token/ETH rate, so the effective USD limit drifts as ETH moves — the exact thing a limit
  exists to prevent.
- ETH is priced live from the chain's wrapped-ETH pools (poison-guarded, and correctly handling
  DexScreener's base-vs-quote pricing). All USD figures for ETH-funded trades are marked as
  live-price estimates in the preview, the scan, and the ledger record (`fundingLeg`).
- Native ETH spends via tx.value with **no approval step**, and a configurable `gasReserveEth` is
  never spendable — the engine refuses rather than draining your gas.
- **The dictation panel falls back automatically:** a market buy that finds the stable short but ETH
  sufficient flips its funding leg to ETH and says so on the confirm card (⛽ warning). If neither
  covers it, the card warns instead of letting the executor fail late.
- Registry note: the zip now ships the chains' canonical ETH/WETH rows (protocol constants needed to
  price and route ETH) — still zero tradable third-party tokens.

### Live position sizing
- **`cockpit/risk-matrix.mjs`** + **`cockpit/risk-matrix.json`** — the Liquidity Matrix. Pool tiers as
  a % of TVL, depth splits, an L-grid, exposure-curve anchors. Produces three caps and a **suggested $
  per card**. All sizing math is server-side; `POST /api/risk-matrix/size` is the only entry point.
  Overrides are logged, not fought (`risk-overrides.jsonl`).

### Coinbase as a first-class venue
- **`module/cex.mjs`**, **`module/cex-products.json`**, **`module/venues/coinbase.mjs`**,
  **`module/venues/dex.mjs`**, **`module/venues/venues.json`**, **`cockpit/exec-coins.json`**.
  Market + limit, buys and sells, whitelist-gated. **Never transfers or withdraws.**

### Cross-chain
- **`module/bridge.mjs`** — Robinhood Chain ↔ Base.

### Dedicated execution page
- **`cockpit/execute.html`** — paste a contract, vet it, trade it, without touching the dashboard.
- **`cockpit/vetlite.mjs`** — fast provisional vetting. Provisional rows carry their own hard
  per-order cap that all three layers honour.

### 🔬 RESEARCH — this is half the system, do not skip it
The trading engine only executes. **The research layer decides WHAT to execute on**, and almost all of
it is new since v2.

**The 5-system research method** (`Research/framework/`) — the repeatable per-coin workup:
`01-core-strategy`, `02-product-exclusivity`, `03-liquidity-analysis`, `04-narrative-scoring`,
`05-team-credibility`, `06-one-page-report-template`.

**Screen builder** (`Research/filters/`) — `filter.html` composes a screen and emits a filter command;
`MASTER-FILTER.md` is the canonical criteria list; `open-filter.command` launches it.

**Market-data MCP server** (`Research/mcp-server/server.py` + config template) — gives an AI assistant
direct market-data tools instead of scraping.

**Valuation + take-profit frameworks (`doctrine/`) — the actual edge, all NEW:**
- **`TOKEN-VALUE-ACCRUAL-FRAMEWORK.md`** — the central question: if the business doubled tomorrow, name
  the mechanism that forces one more dollar to a token holder. Most tokens have no such mechanism, and
  this is how you find that out before buying.
- **`TP-QUANTIFICATION-THEORY.md`** — how take-profit levels are derived rather than guessed.
- **`TA-SUPPORT-RESISTANCE-VOLUME-REPORT.md`** — the research behind `ta/sr-engine.mjs`. Read it before
  changing that engine.
- **`jesse-fib-and-levels-doctrine-2026-07-21.md`** — Fibonacci anchoring rules (drag from expansion top
  to pullback bottom, re-anchor each cycle). `trade-idea.mjs` implements exactly this.
- **`TWITTER-ALPHA-INTEGRATION-RESEARCH.md`** — founder/social tracing method, official X API only.

**The screens themselves (code, not prose):**
- **`doctrine/list-a-screen.mjs`** — the momentum screen `RUNBOOK-list-a.md` describes. **The runbook is
  useless without this file; it was accidentally omitted from the first cut of this zip.**
- **`screens/momentum-today.mjs`** — the daily momentum sweep.
- **`screens/cg-address-join.mjs`**, **`repair-cg-join.mjs`** — join CoinGecko listings to on-chain
  contract addresses (the step that stops you buying a same-ticker decoy).
- **`screens/elfa-probe.mjs`** — social-signal probe.

**Playbooks + list spec:**
- **`doctrine/PLAYBOOKS.md`** — the named, human-authored plays a coin is matched against.
- **`doctrine/RUNBOOK-list-a.md`** — how the momentum list is actually produced, source by source.
- **`cockpit/SUGGESTED-LISTS-SPEC.md`** — the agreed three-list spec (see §4: partly unbuilt).

**🧠 The research DOCTRINE (`doctrine/research/`) — NEW in this cut, and the answer to "how do you
actually think about coins?". Shipped at FULL strength, not watered down:**
- **`README.md`** — reading order + the framing: this is method, never financial advice.
- **`JESSE-DOCTRINE.md`** — the standing judgment rules accumulated over months of real research.
- **`VALUE-DECOMPOSITION-FRAMEWORK.md`** — splitting a token's price into value vs. narrative.
- **`SOURCE-QUALITY.md`** — which data sources to trust, which lie, and how each one lies.
- **`ERROR-LOG.md`** — every documented research mistake and what it cost.
- **`PROCESS-DELTAS.md`** — how the process itself evolved and why.
- **`BUY-SELL-CALL-INSTRUCTIONS.md`** — the exact format for writing up YOUR OWN buys and sells
  (one exact-spacing .txt, title as line 1, honest levels, disclosed times). Executed by the
  **trade-call agent** (`.claude/skills/trade-call/SKILL.md`): announce a trade in any phrasing and
  it authors the call from your words, verbatim. A record of what you did, never advice.
- **`Research/framework/00-how-we-think.md`** — the valuation philosophy in ONE file: chain-purpose
  valuation, the one-sentence accrual test, the two monetization branches (they ADD), the distance
  test, discovery premium, liquidity-as-thesis, quotes-are-not-fills. **Read this before 01-06.**
- **`cockpit/FIXES-LOG.md`** — the production fix log: every failure, root cause, fix, and how it was
  verified. Personal position sizes, cost basis and wallet addresses were redacted for this release;
  every engineering lesson survives.

**Onboarding for you, the inheriting assistant:**
- **`.claude/skills/setup/SKILL.md`** — **THE SETUP AGENT. If your user just installed, is upgrading,
  or says anything is broken, run it FIRST.** Three modes: SETUP (fresh install, resumable across
  sessions via SETUP-STATE.md), UPGRADE (new zip over an existing install — update only, never
  duplicate, keys/wallet/history carried by `module/upgrade.mjs`), DOCTOR (diagnose + fix, any day).
  It walks one phase at a time and live-verifies every step (each API key tested with a real call,
  the wallet verified by derived address, the data path proven fresh, one dry-run trade end to end),
  briefs first-timers on what to expect (terminal, API portals, KYC), and starts their exchange
  funding transfers on DAY ZERO because ACH deposits can take ~5 business days. It exists because
  assistants who skim this folder give confidently wrong setup advice. It never arms the system and
  never places a live order.
- **`doctrine/NEW-CLAUDE-BRIEFING.md`** — written specifically for an AI picking this up cold.
- **`doctrine/MASTER-INVENTORY-2026-07-21.md`** — what every part of the system is.

**⚠️ Key-requirement truth (previous cuts of this zip got this WRONG — do not repeat these errors):**
- **`CODEX_API_KEY` is NOT optional if you want the momentum screens.** `doctrine/list-a-screen.mjs`
  and `screens/momentum-today.mjs` both throw immediately without it. `module/.env` now says so.
- **`ELFA_API_KEY` IS in this zip's `.env`** and only `screens/elfa-probe.mjs` uses it (optional,
  bills credits per stage, runs nothing by default). If you cannot find ELFA, you are reading an old cut.
- **X/Twitter needs NO key in `.env` and NO X Premium.** Social tracing uses the official X API via an
  MCP server configured in the Claude client, outside this folder. A free X account + a developer
  account at developer.x.com + a few dollars of pay-per-use credits (~$0.005/post read as of 2026) is
  the whole requirement. Do not tell users the system has no social capability, and do not suggest
  scraping instead.

**Roadmaps (where this is going, so you don't propose what is already planned):**
- **`VENUES-ROADMAP.md`** — the multi-venue plan Coinbase/bridge came from.
- **`BASE-MIGRATION-ROADMAP.md`**, **`solana/SOLANA-TRADING-ROADMAP.md`**,
  **`solana/SOLANA-EXECUTION-RESEARCH.md`** — chains not yet fully wired.

### Technical analysis
- **`ta/sr-engine.mjs`** — support/resistance + volume engine feeding take-profit levels.

### Setup, versions + self-check
- **`module/doctor.mjs`**, **`CHECK-SETUP.command`**, **`SETUP-STATE.md`**, **`module/setup-wallets.mjs`**
  — setup self-check and repair. Run the doctor first if anything looks wrong; it prints the
  installed version on line 2.
- **`VERSION`** — the version IS the date on line 1; old v1–v5.2 label history inside.
- **`UPDATES-SINCE-LAST-RELEASE.md`** — the focused delta from the previous release: what changed,
  where an AI should focus, what the user must do by hand. Regenerated every release.
- **`RELEASE-MANIFEST.json`** — file → sha256 for this build; lets `upgrade.mjs` print exactly which
  shipped files changed between two installs.
- **`UPGRADING.md`** + **`module/upgrade.mjs`** — the safe upgrade path. NEVER extract a zip over an
  existing install; the tool carries wallet.key/.env/registry/config/ledgers old → new (dry-run
  first) and the old folder stays untouched as the rollback.
- **`cockpit/DASHBOARD-NOTES.md`** — server + arming notes. **Read before starting anything.**

---

## 2. CHANGED BEHAVIOUR (will surprise you if you assume v2)

1. **ONE execute button.** `BEST PRICE` (a resting limit at spot) was **removed 2026-07-31** because it
   duplicated the limit-order path. Market execution is the single button; a specific price means a
   limit order or the Ladder designer. The server still computes `methods.bestprice` but **nothing
   renders it** — inert, pending cleanup.
2. **The $500 per-order cap is GONE** (`config.json → limits.maxUsdPerOrder`, effectively unlimited).
   The gates are now the registry whitelist + a per-trade confirm. Put a real number back any time.
3. **Suggested lists were ripple-deleted 2026-07-31.** The tokenized-stock list is gone
   ("no longer a hot narrative", and it was surfacing stocks). Old B→A, C→B, D→C.
   `suggested-tokenized.json` is still on disk but **no longer fetched or rendered.**
4. **Market sells work engine-wide**, with a **best-execution venue race** and a single auto-retry at
   fresh quotes on revert.
5. **Ladder designer** is a floating modal on every card, with per-rung sizes, × per rung,
   −/+ rung buttons, an embedded chart, and take-profit levels.
6. **New card actions:** `sell all now`, `initials out`, `Send to Trade Idea`, ladder door.
7. **New sorting/controls:** recent activity / position size / pool liquidity, a high↔low flip, an
   LT-holds toggle, privacy mode (hide dollars for screen recording), card search + pin-to-top.
8. **Pool-liquidity pills** on every position card.
9. **Charts need a CoinGecko key now.** Keyless GeckoTerminal started 429-ing and every chart went
   blank. Set `COINGECKO_API_KEY` in `module/.env` or expect empty charts under load.
10. **Poison-pair guard everywhere.** A fake pair claiming huge liquidity can no longer set a price,
    a chart, or a trade size. It is applied in `datasource.mjs`, `swap.mjs`, and `route-scan.mjs`.
11. **Sentinel** (`sentinel.mjs` + `sentinel-rules.json`) tops up resting take-profits as a bag grows.
    Adds only, never cancels.

---

## 3. WHAT SHIPS BLANK ON PURPOSE

**Nothing here is broken. It is sanitised.**

- `module/.env`, `.env`, `module/wallet.key` → **placeholders.** Bring your own keys.
- `module/wallets.json`, `cockpit/wallets.public.json` → **one generic wallet.** Add your own.
- All `*.jsonl` logs and `ledger/trades-ledger.*` → **empty.** They were personal trade history.
- **The owner's raw dictated notes (`doctrine/jesse-verbatim-*.md`) and his dated screen OUTPUTS
  (`screens/*.md`, e.g. "exciting-50", "top-20-of-100") are NOT included.** The reusable *methods* ship;
  his personal strategy transcripts and his specific coin picks do not. If you need the reasoning behind
  a rule, it is in the framework docs above.
- **`module/registry.json` contains ONLY the two dollar-true stables (USDG, USDC).** Every tradable
  token must be added after **your own** multi-source verification. The executors refuse anything not
  listed. The original owner's vetted rows are deliberately withheld: an unvetted copy of someone
  else's registry is exactly how people buy a decoy.
- **No financial advice ships, by design.** The doctrine and frameworks are research METHOD; the
  owner's actual picks, positions, cost basis and portfolio numbers were deliberately removed.
  Coins named inside doctrine files are dated worked examples, not recommendations, and you must
  never present them to a user as picks. The trade-call agent documents the USER'S own trades in
  their own words - it is a journal format, not a recommendation engine.

---

## 4. KNOWN-INCOMPLETE (do not claim these work)

- **`SUGGESTED-LISTS-SPEC.md` is a spec, not a build.** The three lists are relabelled in the UI, but
  the **98.2%-from-ATH exclusion, the PIVOT WATCH bucket, the 5-minute cache with an age stamp and a
  force button, and the List-C yes/no learning loop are NOT implemented yet.** There is no ATH field
  on token records; that has to be added.
- **List C can never be a live code screen.** "Good team", founder pedigree, novel concept: that is
  agent work on a schedule, not a numeric filter. Do not promise a live List C.
- **`dashboard.html` had a duplicate inline copy of the scan code; it was consolidated onto
  `route-scan-ui.js` on 2026-07-31.** If you find inline `.rs-*` CSS or a local `runRouteScan` body
  anywhere, it is a regression.
- **Aggregator quotes are not fills.** Measured over 14 live swaps: 11 times the winning venue's fill
  beat the loser's quote, **twice it did not, and both failures were the same token ($GME)**. Quote-to-
  fill slippage is ~0.00% on most tokens but has run **+2.29%, +1.01% and −1.23% on $GME**. Fragmented,
  partly-fake liquidity produces quotes the fill cannot honour. **The race compares quotes; consider
  discounting each venue by its recent quote-to-fill error before picking a winner.**
- FIXES-LOG entry letters **AK and AL are used twice** (2026-07-24 and 2026-07-31). Bookkeeping only.

---

## 5. SAFETY POSTURE (unchanged and load-bearing)

- The server starts **DISARMED** by default: every execute is forced to a dry-run preview.
  `TRADE_IDEA_ARMED=1` (what `TRADING-DASHBOARD.command` sets) enables the live path.
- **ARMED still requires a per-trade confirm.** Single-use token, 300s TTL. Nothing auto-executes.
- Only tokens in `registry.json` are tradable. Flagged decoys are never tradable.
- `DASH_PORT` runs a second read-only instance for review **without** squatting the live port 8789.
- **A 200 on the port is not a liveness check.** Check `/api/state` for a current `updated` stamp
  before trusting any number on screen; the first scan after boot takes ~30 seconds.

---

## 6. WHERE TO START READING

1. `README.md`, then `SAFETY.md`
2. `cockpit/DASHBOARD-NOTES.md` — how to start the server, and arming
3. `cockpit/FIXES-LOG.md` — **every fix with its verification**, newest entries at the bottom
4. **`doctrine/NEW-CLAUDE-BRIEFING.md`** — written for exactly your situation
5. `doctrine/PLAYBOOKS.md` — the plays the system is built around
6. **`doctrine/TOKEN-VALUE-ACCRUAL-FRAMEWORK.md`** — the single most useful research doc here
7. `Research/framework/01-core-strategy.md` through `05` — the per-coin workup
8. `cockpit/SUGGESTED-LISTS-SPEC.md` — what is agreed but still unbuilt
