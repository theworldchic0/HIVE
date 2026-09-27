# TRADING DASHBOARD — build notes (2026-07-21)

**Open it:** double-click `~/Desktop/TRADING-DASHBOARD.command` (starts `dashboard-server.mjs` on `http://127.0.0.1:8789/` if not already up, then opens the page). READ-ONLY end to end — nothing here can place, sign, edit, or cancel an order.

**Files:** `dashboard.html` (the page) · `dashboard-server.mjs` (localhost server, holds keys server-side) · `datasource.mjs` (aggregator) · `wallets.public.json` (address roster, no keys) · `feedback-log.jsonl` (feedback box intake). The original per-trade cockpit (`index.html` + `trades.js` + `serve.js` on 8788) is untouched and linked from the header ("old cockpit →"); `trades.js` is also consumed by the dashboard for curated per-trade notes.

## LIVE (verified in browser 2026-07-21)

- **Everything in one spot:** open orders (both wallets, live from 1inch orderbook v4.0 on **4663 AND 8453**), positions, portfolio value, charts. Solana watch address scanned too.
- **Balances:** Robinhood Chain via Blockscout token-balances + RPC native; Base via Alchemy (`ALCHEMY_API_KEY` from `module/.env`, never sent to the browser); Solana via Alchemy for qjmg…SsSU (watch-only).
- **Prices:** Blockscout `exchange_rate` → DexScreener per-contract fallback (the batch endpoint silently drops pairs past ~30, so the fallback queries one contract at a time) → CoinGecko for ETH/SOL. The step-6 enrichment batch got the same treatment 2026-07-22 (FIXES-LOG E): contracts the batch returns no pairs for are re-queried one at a time.
- **Coinbase (added 2026-07-22, FIXES-LOG E):** `coinbase-balances.mjs` pulls the exchange account LIVE via the read-only Advanced Trade JWT (same key file as the ledger source) using the portfolios-breakdown valuations (Coinbase's own numbers). 120s lane. Shows as a card in the wallets row and is included in the headline portfolio value; a failed fetch shows an explicit ⚠ and is excluded, never silently $0.
- **GeckoTerminal chart embedded per token** (default tab) + **Levels chart** (canvas): dashed lines where each resting order sits (underfunded/blocked orders drawn red), dots where fills executed, 15m/1h/4h/1d, live 20s candle refresh while visible.
- **Click a position → full history:** every market buy (tx link, exec-vs-mid %), every fill (order hash, chain-verified tx where known), every resting order (status/filled %/expiry) + curated notes from `trades.js`.
- **Per-position P&L:** realized proceeds from sells + realized P&L where basis known, remaining bag × live price, avg cost across multi-buys, unrealized $ and % — handles buy-then-sell sequences from `module/orders-log.jsonl`.
- **Fill detection:** 1inch keeps filled orders on the book with `orderInvalidReason: "order filled"` (BASTION canary verified: tx 0x8aee863e…, +4.2817 USDG). Orders that later drop OFF the book entirely are *inferred* filled (we never cancel; expiries are ~100 days out).
- **Funding strip:** server execs `module/funding-calc.mjs --json` (cached 2 min) → headline per wallet, e.g. "wallet-2: LOAD $50.00 MORE USDG (best $0 / worst $50 · first dry buy: WOOD $50)".
- **Feedback box** ("why are we changing this") → POST `/api/feedback` → `feedback-log.jsonl` (+ Copy fallback). Route entries into lesson logs/doctrine per ROADMAP principle 12.
- **Registry badges:** AUTHORIZED (in `module/registry.json`) / UNVERIFIED / DECOY (fake-USDG airdrops flagged, never priced or charted).
- Server caches state 25s (single-flight, serves stale while refreshing); page auto-polls 30s. First scan after boot takes ~30s.

## STUBBED / KNOWN LIMITS

1. **Pre-system bags have unknown cost basis** (wallet-2's RAXOL/STONKBROKER/VEX/MLY/WOOD, wallet-1's BASTION were bought before the module existed) → realized P&L shows "basis unknown" (proceeds still tracked). Session B's Trade DNA study could backfill basis from chain history.
2. **Orders not in `orders-log.jsonl`** (e.g. placed by hand in the 1inch UI) count in the wallet chips but don't appear in a position's history. None exist today.
3. **Solana is balances-only** — no orderbook (1inch isn't on Solana), no execution path (by design, watch-only).
4. **Sub-$1 Base dust is hidden** by the datasource (DUST_USD=1). The CARD GRID additionally hides
   any bag under **$9** (`DUST_FLOOR_USD`, Jesse's DB dust rule; kept only if it holds a live resting
   order) and any contract in a registry token's decoys[] — a "N hidden (dust + decoys) show" line
   under the grid reveals dust as cards (decoys never chart). Totals and /api/state stay complete.
5. **Chart on the Levels tab needs a GT-known pool** — tokens whose pool only DexScreener knows may show "no candle data" (GT iframe tab still has the DS/GT links).
6. **Partial fills**: shown as "partial" with filled-% on the order; the filled fraction is not yet split into realized P&L (no partial has occurred yet).
7. `CONFIRMED_FILLS` (chain-verified fill txs) is a hand-pinned map in `datasource.mjs` — next fill needs its tx added there for the ✓ tx link (fills still auto-detected without it).

## OPEN QUESTIONS FOR JESSE

- Backfill cost basis for the pre-system bags (chain-history scan), or leave "basis unknown"?
- Should feedback-log.jsonl entries auto-route to a specific lesson log file, and which one?
- Keep old cockpit (8788) alive or retire it once this replaces it?
- When base-dex-trade-executor goes live, Base orders will appear automatically (orderbook 8453 already wired) — no action needed, just noting it.

---

# TRADE-IDEA ENGINE — added 2026-07-21 (in-server execution path)

> **POSTURE CHANGE — read this first.** The four routes above (`/api/state`, `/api/funding`,
> `/api/feedback`, static) are the **read-only viewer** and remain strictly read-only. The
> trade-idea engine below adds a **real execution path** (it can sign & submit orders through
> `module/arm.mjs` / `module/swap.mjs`). It is **DISARMED by default** — see the ARMED section.
> LAUNCHER UPDATE (2026-07-21, Jesse: "one, arm it"): `~/Desktop/TRADING-DASHBOARD.command` now
> starts the server with `TRADE_IDEA_ARMED=1`, so the double-click path is ARMED (live-capable,
> per-trade confirm still required). A bare `node dashboard-server.mjs` with no env stays
> disarmed. Since 2026-07-22 the startup banner prints the real armed state and the page shows
> a red top strip whenever the running instance is disarmed.
> **FLAG for Jesse (raised by dashboard-finisher, echoed here):** decide whether the read-only
> viewer and the executor should share ONE server + ONE launcher, or run as separate
> processes/ports. approve-before-spend is a Jesse-set principle; this is a deliberate decision.

**Files I added:** `trade-idea.mjs` (the whole engine — parser, scenario math, executor spawner,
confirm-token store) + a `#tradeIdea` panel and a trailing `<script>` IIFE in `dashboard.html`
(both delimited by `TRADE-IDEA ENGINE` HTML-comment fences; self-contained, reads `sel`/`S`
defensively AND self-fetches `/api/state`, so it survives the positions-grid rewrite) + three
namespaced routes in `dashboard-server.mjs`.

## Endpoints (namespaced `/api/trade-idea/*`)

- `GET  /api/trade-idea/config` → `{armed, maxUsdPerOrder, defaultExpiryHours, note}`. Is the live path on?
- `POST /api/trade-idea/analyze` → body `{positionKey, text, mode}`. Parses Jesse's free-text intent
  into buy/sell legs, runs full scenario analysis, derives the exact `arm.mjs`/`swap.mjs` argv, and
  (if fully specified) mints a single-use **confirm token** bound to that exact plan. Returns
  `{position, costBasis, projection, legs, takeProfit, scenarios, warnings, blockers, ready,
  quickReady, quickBlockers, confirmToken, callTime}`.
- `POST /api/trade-idea/execute` → body `{confirmToken, dryRun}`. Looks up the token (single-use,
  5-min TTL), then runs each leg's executor via child_process and streams stdout/stderr back. Returns
  `logId` + echoed `ticker`/`contract` so the card can attach post-trade context to the exact log row.
- `POST /api/trade-idea/context` → body `{logRef,context}` (added 2026-07-22, CW-cockpit-round3).
  WRITE-LIMITED: attaches the post-trade "why did we make this trade" onto the matching
  trade-idea-log.jsonl row (by `id` or `call_time`+`ticker`), preserving its auto snapshot;
  appends a companion row if the target is gone. No analyze/token/execute side effects.
- `POST /api/play-candidate` → append-only to `doctrine/play-candidates.jsonl` a Jesse-described
  candidate play (`one_liner`, or a `detail` row). Agents research these into PLAYBOOKS.md drafts.
- `GET /api/registry-decoys` → flattened lowercased decoy contracts (the card grid hides them).

## The two modes (Jesse's on/off clicker)

Both modes do analysis + execution through the SAME executor; the toggle only changes the ORDER of
(execute vs review). Neither removes Jesse's explicit yes.
- **NORMAL** — Analyze first → panel shows the whole scenario → Jesse clicks **✓ Confirm & Execute** →
  execute (two clicks; detail before the yes).
- **QUICK** — one **⚡ Execute now** click = analyze + immediately execute the minted token, THEN show
  the full detail + result. QUICK **refuses** unless the idea is fully specified (explicit $ amount,
  explicit price, no `~`/percent-of-position sizing) — `quickBlockers` explains why; nothing executes
  ambiguously.
  - **FROM A POSITION CARD (2026-07-22, CW-cockpit-round3):** with QUICK selected the card's button
    becomes "Execute now" and fires the whole flow INLINE at the card (no scroll, no panel jump),
    bound to that card's EXACT positionKey. Quick analyze no longer requires the trade-context fields
    pre-trade — the click IS the confirm (Jesse's standing decision) and context ("why did we make
    this trade") is captured AFTER the fill via a small form at the card → `POST /api/trade-idea/context`.
    Dry-run when the global preview checkbox is checked (and always when disarmed). `planned_exit_map`
    is now OPTIONAL everywhere; only `playbook_tag` + `thesis_oneliner` + `conviction` gate a NORMAL trade.

## SAFETY (server-side, defence-in-depth)

1. **Confirm token** — the server refuses to execute without a valid token from the UI; the token is
   minted only after analysis passes all gates, is bound to the exact derived plan, is single-use, and
   expires in 5 min.
2. **ARMED flag** — live execution requires the server started with `TRADE_IDEA_ARMED=1`. If unset
   (the default, incl. the Desktop launcher), every execute is **forced to dry-run** (runs the executor
   WITHOUT `--confirm GO` → preview only), no matter what the client sends. Verified: client sending
   `dryRun:false` while disarmed still returns `live:false`.
3. **Registry + caps** — analysis blocks non-registry tokens and anything over `module/config.json`
   `limits.maxUsdPerOrder`; `arm.mjs`/`swap.mjs` independently re-enforce the same registry match +
   cap + `--confirm` gate. Two layers. (2026-07-23: the $500 cap value was REMOVED per Jesse —
   set to 1000000, effectively none; put a real number back in config.json to restore.)
4. **Full-spec for QUICK** — no ambiguous immediate execution (see above).
5. **Keys never exposed** — the engine only spawns the module's scripts, which read their own key files.

## call_time (Jesse's rule) vs order_time / fill_time

`call_time` is stamped at the VERY FIRST line of `analyzeIdea` (before any network call) = the moment
Jesse issued the "buy call" / "sell call". It's carried in the plan → confirm token → recorded
separately from `order_time` (stamped when execution is triggered). Every execute (live OR dry-run)
appends a call record to **`trade-idea-log.jsonl`** with `call_time`, `order_time`, per-leg
`call_type` ("buy call"/"sell call"), the command, and (on live) the resulting `orderHash`/`txHash`.
On LIVE fills, `arm.mjs`/`swap.mjs` also append their own row to `module/orders-log.jsonl`, which the
ledger ingester (`ledger/ingest.mjs`) picks up. **TODO handed to ledger-finisher:** join `call_time`
from `trade-idea-log.jsonl` into the ledger by order hash + add a `call_time` column (ledger schema is
their domain — I did not touch it).

## UNOWNED / UNREVIEWED (flag for Jesse) — RESOLVED 2026-07-21/22, queue retired

`dashboard-server.mjs` used to contain a **file-queue handoff** added by a THIRD session:
`POST /api/trade-request` wrote pending rows to `trade-requests.jsonl` for a Claude-side watcher
that was expected to answer via `trade-responses.jsonl`. That consumer was never reviewed and was
NOT gated by `TRADE_IDEA_ARMED`.

**RESOLUTION:** Jesse picked the trade-idea engine ("one, arm it", 2026-07-21). The queue routes
all answer **410** since the armed-server hardening. On 2026-07-22 the client side caught up:
the per-card trade boxes now PREFILL the Trade Idea panel (no POST, nothing runs until Jesse
confirms in the panel), the per-card threads render recent call history for that ticker from
`trade-idea-log.jsonl` via the read-only `GET /api/trade-idea/log` route, and no UI copy promises
a Claude-side watcher anymore. `trade-requests.jsonl` rows were marked stale by the main session;
the file stays on disk as history only.

## Verified 2026-07-21 (DRY-RUN only — no real order placed)

Worked example, real WOOD ledger data (`wallet-2`), idea
*"buy more WOOD at 0.011, increase position ~40%, take initials out at 0.034"*:
- cost basis pulled **from the ledger** (blended avg over the 2 filled buys) — the
  dashboard state shows WOOD avgCost `null` because its buys are ledger-only, not in orders-log; this is
  exactly why req #2 says "from the ledger." Unknown-basis portion (~4,006 WOOD from a STONKBROKER→WOOD
  swap) is surfaced honestly, not hidden.
- buy leg → `arm.mjs` resting limit buy $ (40% of position value, flagged approximate → QUICK-blocked);
  sell leg → `arm.mjs` resting limit sell, "initials" = recover the invested dollars, converted to
  tokens at the named price — verified against the real resting sell it reproduced.
- new blended avg cost, new bag, new %-of-portfolio all computed and shown.
- Fib extensions (anchors 0.0175→0.0054) reproduce Jesse's doctrine numbers: 1.618=0.024978,
  2.618=0.037078, 3.618=0.049178, 4.236=0.056656. Level scenario "runs to 0.03 → bag $; pulls back to
  prior-resistance-now-support 0.021 → bag $" rendered. TP auto-derivation uses GT daily OHLCV (subject
  to GT free-tier rate limits; explicit `fib from X to Y` in the text is the reliable fallback).
- execute (disarmed) streamed the real `arm.mjs` ORDER PREVIEW for both legs and ended in "DRY RUN —
  nothing signed." Safety: no-token→400, bogus-token→reject, reused-token→reject, disarmed forces
  dry-run. Panel verified in-browser: DISARMED badge, NORMAL/QUICK toggle, 9-position dropdown,
  scenario cards, TP proposals, BUY CALL/SELL CALL pills, confirm button.

**To arm for real trading (Jesse only):** `TRADE_IDEA_ARMED=1 node dashboard-server.mjs`. Even armed,
every trade still needs the confirm token + Jesse's button press, and respects the config per-order
cap (removed per Jesse 2026-07-23 — see the safety section above).
