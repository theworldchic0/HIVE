# SETUP: the guided tutorial (Claude drives, you approve)

> **Claude: the preferred path is the SETUP AGENT — `.claude/skills/setup/SKILL.md`**
> (three modes: fresh SETUP, safe UPGRADE, DOCTOR repair; every step live-verified).
> This file is the human-readable step list behind it and the fallback when skills
> can't load. Same laws apply either way, especially the CONSCIOUS-SKIP LAW below.

Claude: take these steps ONE AT A TIME. For each: do the action, run the verify
command, show the human the real output, and only advance when the verify passes.

**THE CONSCIOUS-SKIP LAW (never bend it):** some steps are optional, but no step is
ever passed silently. To skip a step the human must type the literal word **SKIP**
after being told, in one sentence, exactly what stops working. Claude records every
completion and every skip in `SETUP-STATE.md` (one line each, with the date). If a
line for a step is missing from SETUP-STATE.md, the step is NOT done — no matter
what anyone remembers.

Human: you paste secrets into files yourself; never into the chat.
Total time: about 30-40 minutes plus funding transfers.

---

## Step 0: Run the doctor first (and after every step)

Double-click `CHECK-SETUP.command` (or run `cd module && node doctor.mjs`).
On a fresh install most lines are red — that is the point: the doctor is your
live checklist. Re-run it after every step below and watch it turn green.
It makes REAL calls (1inch, Alchemy, both chains) so a wrong key is caught here,
not during a trade. It never prints a secret.

---

## Step 1: Prerequisites

**Action:** confirm Node.js LTS (v20+) is installed. If not: download from
https://nodejs.org, install, reopen Terminal.

**Verify:**
```bash
node --version
```
Expected: `v20.x` or newer. Then install the engine's dependencies:
```bash
cd "<this folder>/module" && npm install
```
**Gate check (no network, no keys needed):**
```bash
node offline-selftest.mjs
```
Expected last line: `OFFLINE SELFTEST PASS — build + sign path works for both chains. No network was touched.`
Record in SETUP-STATE.md: `step 1 done`.

---

## Step 2: The wallet wizard — EVERY place you hold crypto

**Action:**
```bash
cd module && node setup-wallets.mjs
```
The wizard walks you through: your TRADING wallet (import your own key into
`module/wallet.key` yourself, or generate a fresh one locally — the key is never
displayed and never typed into chat), then **every other wallet you own** — it
keeps asking "do you have any more wallets? anywhere else you hold crypto?"
until you consciously answer no (old MetaMask accounts, phone wallets, Solana
wallets — all watch-only by public address, the system can never spend from
them), then Coinbase balances (optional view-only key).

Every answer, including every skip, lands in `SETUP-STATE.md` automatically.

**Verify:**
```bash
node verify-wallet.mjs
```
Expected: your trading wallet's ADDRESS, matching `cockpit/wallets.public.json`.
The dashboard tracks every wallet you added. Treat `wallet.key` like cash.

---

## Step 3: 1inch API key (free, REQUIRED — nothing trades without it)

One key powers market swaps AND resting limit orders on both chains.

**Action:** open https://portal.1inch.dev, sign in, create an application, copy the
API key, paste it into `module/.env` replacing `PASTE_YOUR_1INCH_API_KEY_HERE`.

**Verify (uses the key live, dry-run, nothing signs):**
```bash
cd module && node swap.mjs --src USDC --dst WETH --usd 1
```
Expected: an ORDER PREVIEW with venue quotes and the DRY RUN line. A 401 means
the key is wrong or not yet active (portal keys can take a minute).
This step cannot be skipped — without it the system is a viewer, not a trader.

---

## Step 4: Alchemy key (free, REQUIRED — the ledger's eyes on Base)

Without it the Base ledger is BLIND: cost basis and realized P&L will be wrong,
and the dashboard will keep reminding you until the key exists. Not skippable.

**Action:** https://dashboard.alchemy.com → create an app on **Base Mainnet** →
copy the API key → paste into `module/.env` as `ALCHEMY_API_KEY=...`.

**Verify:** re-run the doctor; the Alchemy line goes green with a live block number.

---

## Step 5: Both chains reachable

**Verify Robinhood Chain, then Base:**
```bash
curl -s -X POST https://rpc.mainnet.chain.robinhood.com -H "Content-Type: application/json" --data '{"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]}'
curl -s -X POST https://mainnet.base.org -H "Content-Type: application/json" --data '{"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]}'
```
Expected for both: `{"jsonrpc":"2.0","id":1,"result":"0x..."}`.

---

## Step 6: Boot the dashboard (DISARMED)

**Action:** double-click `TRADING-DASHBOARD.command` (or run it in Terminal).

**Verify:** it prints `server is DISARMED (dry-run only ...)` and opens
http://127.0.0.1:8789 — your wallet cards (empty is fine), a red DISARMED strip,
no errors. First scan takes ~30 seconds. Every wallet from Step 2 appears.

---

## Step 7: Fund the trading wallet

Send funds to YOUR trading address (Step 2), per chain:
- **Robinhood Chain (4663):** ETH for gas (a few dollars) + USDG (the dollar-true
  stable there; verified contract ships in `module/registry.json`).
- **Base (8453):** ETH for gas + USDC (the real Base USDC; also in the registry).

**Verify:** balances appear on the dashboard as transfers land.

---

## Step 8: The registry lesson (why your money is still alive next year)

Nothing trades unless the token has a row in `module/registry.json`. The shipped
registry holds only verified plumbing: USDG (Robinhood Chain), USDC (Base), WETH.
To add a token: verify the contract on DexScreener AND the chain explorer AND
ideally the project's own site, then add the row with chainId and decimals.
Claude does the verification legwork and shows you the evidence; you approve the
row. The dashboard's paste-and-vet (⚡ Execute Now tab) automates the mechanical
checks and caps unvetted tokens at $25/order. Fake clones of hot tickers are
COMMON. If price, volume, and holders don't all agree across sources, walk away.

---

## Step 9: Your trade journal (your numbers, not anyone else's)

This kit ships with EMPTY books on purpose: `module/orders-log.jsonl`,
`ledger/trades-ledger.jsonl`, and the dashboard history all start blank and fill
with YOUR trades automatically. Two conscious choices to record in SETUP-STATE.md:
1. **In-system journal (default, already on):** the ledger + dashboard are the
   journal; `node ledger/ingest.mjs` refreshes it any time.
2. **External journal (optional):** if you keep a Notion/Sheets journal, create
   YOUR OWN database for it (this kit never connects to anyone else's) and tell
   Claude the columns you want; it can format entries for you after each trade.
Type your choice (1, 2, or both) so it is recorded — not assumed.

---

## Step 10: Research keys (optional, each its own conscious choice)

The research side works with free sources out of the box (DexScreener,
GeckoTerminal public APIs). Two optional keys deepen it. For EACH one, either
complete it or type SKIP so the choice is recorded:

- **Codex key** (`module/.env` → `CODEX_API_KEY=`): powers market discovery /
  suggestion screening. Skip = the Suggested Plays generators have one less
  source; the shipped lists start empty either way and fill from your own runs.
  Get one: https://www.codex.io
- **X (Twitter) bearer token** (root `.env` → `X_BEARER_TOKEN=`): founder and
  social tracing during token research. Skip = social checks are skipped and
  research reports say so. Get one: https://developer.x.com (pay-per-use).

See `Research/README.md` for how the research method plugs into the terminal.

---

## Step 11: Graduation matrix (all dry-run, tick every box)

Everything below is a preview; nothing signs. Run each on BOTH chains (taker =
USDG on Robinhood Chain, USDC on Base). Ask Claude to drive; check the boxes:

- [ ] Market buy preview: `node swap.mjs --src USDC --dst WETH --usd 5`
- [ ] Market sell preview: `node swap.mjs --src WETH --dst USDC --usd 5`
- [ ] Resting limit buy preview: `node arm.mjs --token WETH --side buy --usd 5 --limit-usd <20% below market> --taker USDC --expiry-hours 336`
- [ ] Limit take-profit preview: `node arm.mjs --token WETH --side sell --qty-pct 10 --price-above-pct 50 --taker USDC --expiry-hours 336`
- [ ] Dashboard Trade Idea panel: type "buy $5 of WETH at market" and reach the
      "So you want to do this?" card (do NOT press it, this is the drill)
- [ ] Fast-exit language: type "sell all" on a card and reach the readback
      showing 100% of bag at MARKET (do NOT press it)
- [ ] Ladder designer: open from a card, drag a rung, edit a rung's $, Stage,
      reach the confirmation card (do NOT press it)
- [ ] Doctor: fully green except items you consciously skipped

---

## Step 12: The ARMED ceremony

DISARMED = every execute becomes a preview, no matter who clicks what.
ARMED = the live path is unlocked, and every order STILL requires your per-trade
confirm press plus the registry gate plus whatever per-order cap you set
(`module/config.json` limits.maxUsdPerOrder — **ships effectively unlimited;
set a number you would shrug at BEFORE arming**).

To arm, you (the human) start the launcher with:
```bash
ARM=1 ./TRADING-DASHBOARD.command
```
Arming is your deliberate act each time; Claude never arms for you.

**Optional live graduation:** one tiny market buy ($1-5) of a registry token, then
one tiny take-profit. Confirm the fill on the dashboard and the chain explorer.
Congratulations — the system is yours.

---

## Step 13 (optional): Coinbase exchange trading, the CEX lane

This kit trades on-chain DEXes by default. It can ALSO trade the Coinbase
exchange (spot market + limit orders) through the same cockpit, same
confirmation cards, same laws. Type SKIP to record skipping it.

1. **Mint your trade key.** Go DIRECTLY to
   **https://portal.cdp.coinbase.com/api-keys/secret** (the portal's redesigned
   sidebar buries this page — the direct link skips the maze). Click **Create API
   key**: nickname anything; expand **API restrictions**; permissions **View +
   Trade ON, Transfer OFF** (a stolen key must never be able to withdraw);
   **signature algorithm: ECDSA** (Ed25519 is not supported for these APIs).
   Create → **Download API key** → save the JSON as `module/coinbase-trade.json`.
   Never paste it into chat.
   NOTE: ignore anything called "Wallet Secret" in that portal — different
   Coinbase product, never needed, never create it.
   ALREADY HAVE A KEY? Ask Claude to call `GET /api/v3/brokerage/key_permissions`
   with it; `can_trade: true, can_transfer: false` means just save that file.
2. **Whitelist your products:** edit `module/cex-products.json`, add each product
   you intend to trade, e.g. `"BTC-USD": {"note": "core position"}`. The venue
   refuses anything not listed — same law as the DEX registry.
3. **Set your CEX cap (recommended):** `module/config.json` limits →
   `"cexMaxUsdPerOrder": 500` (or your number).
4. **Verify:**
```bash
cd module && node cex.mjs --quote BTC-USD
node cex.mjs --product BTC-USD --side buy --type limit --usd 10 --limit-usd <far below market>
```
   Expected: `key mode: TRADE`, a live quote, then a preview ending in `DRY RUN`.
5. **Balances-only alternative (“Step 13.5” — the wallet wizard points here):** a VIEW-only key saved
   as `cockpit/coinbase.json` shows Coinbase balances on the dashboard with no
   trading ability at all. Both files can coexist.

Honest limit: realized/closed P&L for CEX fills is not wired into the closed-
positions table yet (see KNOWN-ISSUES); order truth via `node cex.mjs --orders`.

---

## Troubleshooting quick table
- `REFUSED: ... not in the verified registry` = the gate working; see Step 8.
- 401 from 1inch = bad/inactive key in `module/.env` (Step 3).
- "⚠ BASE LEDGER IS BLIND" at ingest = no Alchemy key (Step 4 was skipped).
- Empty dashboard = first scan still running (~30s), wrong address in
  `cockpit/wallets.public.json` (Step 2), or no funds yet (Step 7).
- Balances but no candles on a token = its pool is not on GeckoTerminal; the
  card's DexScreener link still works.
- Anything else: run the doctor first, then ask Claude to read the server log
  (`~/Library/Logs/trading-dashboard.log`) and report what it actually finds.
