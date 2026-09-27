> ## 🐝 NUK3R2 HIVE: new users start at [`START-HERE.md`](START-HERE.md)
> Double-click `HIVE.bat` (Windows) / `HIVE.command` (Mac). The first start walks you through every API key.
> How the agents fit: [`HIVE.md`](HIVE.md).

# Altcoin Trading System — the CoinPicks Research Engine + Trading Terminal, in one zip

> ## 🚨 IF YOU ARE AN AI READING THIS FOLDER FOR THE FIRST TIME
> **Setting someone up, upgrading, or fixing? Run the setup agent: [`.claude/skills/setup/SKILL.md`](.claude/skills/setup/SKILL.md).**
> Otherwise **read [`00-READ-THIS-FIRST-ADDITIONS.md`](00-READ-THIS-FIRST-ADDITIONS.md) before anything else.**
> The build you are in is stamped in [`VERSION`](VERSION) (the version IS the date; the doctor prints
> it). Many users run older builds, and roughly half of what this system does today did not exist
> then. That file is the complete list of what is new, what changed, what ships blank on purpose,
> and what is NOT built yet. Skipping it will make you describe the old system.


## What this is: TWO systems in one folder

This zip is **one big AI system you can plug anything into** — venues, chains, tokens,
data sources. It has two faces, and you use both:

### 🖥 1. THE TRADING TERMINAL — the interface that pops up
Double-click `TRADING-DASHBOARD.command` and a live trading terminal opens in your
browser: your whole portfolio valued in dollars across every wallet and Coinbase,
candle charts, open orders, suggested-play lists, and a box where you **type a trade
in plain English** ("buy $50 of TOSHI", "sell 25% at 0.026") and get a plain-English
confirmation card with a live best-execution route scan before any button. This is
the **trade-execution side**: market buys and sells raced across 1inch + KyberSwap,
resting limit ladders that fill 24/7 while your computer is off, take-profit
automation, fear-exit buttons, and an honest ledger underneath. Out of the box it
trades **Robinhood Chain + Base** (on-chain DEX) and **Coinbase** (the exchange,
official API).

### 📚 2. THE RESEARCH ENGINE — the Claude Code side (it's files)
There is no interface for this half, on purpose: **the files ARE the system, and
Claude Code is how you drive them.** Open this folder in Claude Code and you have
the CoinPicks research method as a working machine: the 5-system framework
(`Research/framework/` — core strategy, product exclusivity, liquidity analysis,
narrative, team credibility), the full research doctrine (`doctrine/research/` —
how the author actually thinks, the error log of every mistake already paid for,
which data sources lie and how), a live market-data MCP server (`Research/mcp-server/`),
momentum screens (`screens/`), a support/resistance engine (`ta/`), and the
paste-and-vet gate that stops you buying scam clones. You research a coin by
*talking to Claude in this folder*; the output is a verdict you can defend.

### 🔁 How the two halves connect
Research earns a token its registry row → **the registry is the only door to the
execution engine** (it refuses anything unvetted) → the terminal executes with hard
safety gates → the ledger records the truth → your results feed back into the
research. One loop: **research → vet → trade → track.**

Tell Claude what you want in plain English on either side — "research $TICKER" or
"buy $50 of TICKER" — and it drives the machinery with your press on every trigger.

> "Buy $50 of TOSHI" → Claude previews the trade, you say GO, it executes on-chain
> and reports exactly what you paid and received.
> "Buy $30 of WETH at 0.002 and $50 at 0.0015"   (and once you hold a bag: "sell 20% at 0.026")
> → a resting ladder, filled server-side 24/7 while your computer is off.

The plug-in points, when you outgrow the defaults: `module/venues/` for new
exchanges, `registry.json` for tokens, `module/.env` for data sources, and more
chains are a recipe away (CLAUDE.md → "Adding a new chain").

## What's in the box

| Piece | Side | What it does |
|---|---|---|
| `TRADING-DASHBOARD.command` | 🖥 Terminal | Double-click launcher for the interface. DISARMED (preview-only) by default; `ARM=1` enables live placement. |
| `cockpit/` | 🖥 Terminal | The dashboard web app: live portfolio, charts, open orders, suggested lists, and the **Trade Idea panel** — dictate a trade in plain English, get a confirmation card + live route scan, one button executes. |
| `module/` | 🖥 Terminal | The execution engine (Node.js + ethers + 1inch SDK). Market buys/sells raced across 1inch + KyberSwap; resting limit orders via the 1inch orderbook; Coinbase venue; ETH-gas switch; the registry gate. |
| `cockpit/sentinel.mjs` | 🖥 Terminal | The **moonbag sentinel**: when a pre-approved resting buy fills, it places your take-profit sells automatically. Sells only, your rules, armed only. |
| `ledger/` | 🖥 Terminal | All-venue trade ledger: your fills, cost basis, and P&L in one honest CSV/JSONL. |
| `Research/` | 📚 Research | The 5-system CoinPicks framework (`framework/00`–`05`), the screening filter form, and the live market-data MCP server. Start at `framework/00-how-we-think.md`. |
| `doctrine/` | 📚 Research | The thinking: `research/` (JESSE-DOCTRINE, ERROR-LOG, SOURCE-QUALITY, VALUE-DECOMPOSITION, buy/sell call format), `PLAYBOOKS.md` (named plays), TA doctrine. |
| `screens/` | 📚 Research | Momentum screens (Codex full-universe sweep) + social-attention probe. |
| `ta/` | 📚 Research | Support/resistance + volume engine feeding ladder levels. |
| `.claude/skills/` | Both | Claude Code skills, auto-loaded when you open this folder: **setup** (the setup agent: install, upgrade, doctor), market-buy, limit-order, limit-take-profit, coinbase-trade, **trade-call** (journal your own buys/sells). |
| `SETUP-CLAUDE.md` + `CHECK-SETUP.command` | Both | The human-readable setup runbook + the double-click doctor (12 live checks, prints your version). |
| `VERSION` · `CHANGELOG.md` · `UPDATES-SINCE-LAST-RELEASE.md` · `UPGRADING.md` | Both | The version is the date. The delta file shows exactly what changed since the last release; `module/upgrade.mjs` upgrades without losing your keys, wallet, or history. |

## The four trade primitives (all verified)

- **Instant market buy**: `swap.mjs`, quotes 1inch AND KyberSwap, executes the winner.
- **Instant market sell**: same venue race, token → dollar-true stable.
- **Resting limit buy**: `arm.mjs`, rests on 1inch's orderbook, fills 24/7.
- **Resting limit sell / take-profit ladders**: same, sized by $, qty, or % of bag.

Plain-English parsing is loose by design: "buy $10 at market price", "Buy $2 right
now.", "buy right now $20", "ten dollars at market", multi-leg ladder dictations with
"Actually…" corrections: all parse. Nothing executes without your explicit confirm.

## The safety gates (built into the engine, not optional)

- **Registry gate:** the engine refuses any token not in `module/registry.json` with a
  verified contract. This is what stops scam clones and decoy contracts.
- **Preview always:** every command is a dry run until the explicit confirm flag.
- **Per-order cap:** `module/config.json` → `limits.maxUsdPerOrder`. **Ships effectively
  UNLIMITED — set a real number before arming** (the setup agent walks you to the line).
  All three layers (trade-idea, arm.mjs, swap.mjs) enforce whatever you set.
- **Armed/disarmed:** the dashboard server can only place real orders when started
  with `TRADE_IDEA_ARMED=1`, and even then each trade needs a per-trade confirm.
- **Dollar-true settlement:** USDC on Base, USDG on Robinhood Chain: limits are set
  and filled in dollars, no ETH drift.
- **Sentinel is sell-only** and acts only on rules you pre-approved in
  `cockpit/sentinel-rules.json` (ships empty).
- **Your keys stay local:** the private key lives in `module/wallet.key` on your
  machine, is read only at signing time, and never leaves except as a signature.

## Install (one time)

1. Unzip to your Desktop so it lives at `~/Desktop/Altcoin-Trading-System`.
2. Nothing to copy — the `.claude/skills/` folder auto-loads when you open this folder in Claude Code.
3. Open the folder in Claude Code and say: **"set me up"** — the setup agent takes it
   from there, one verified step at a time (upgrading from an older build? say that
   instead — it carries your keys and history over, never overwrites them).
   Do NOT paste your private key or API key into the chat; the agent shows where each
   one goes on your own disk.
4. Double-click `TRADING-DASHBOARD.command` to see the terminal (starts preview-only).

Not financial advice. This is a tool that executes YOUR decisions.
