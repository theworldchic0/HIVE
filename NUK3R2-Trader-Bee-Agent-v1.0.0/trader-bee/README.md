# 🐝 NUK3R2 Trader Bee v1.0.0

The Hive's trading agent, with **partial automation**. It has its own wallet that you fund, and it
spends from that wallet by itself under two rules you set:

| Trigger | Where it comes from | Size |
|---|---|---|
| **Discovery, high confidence** | Research Bee verdict: `discovery: true`, gate PASS, rank BUY/WATCH | **$10** |
| **Discovery, medium confidence** | same | **$5** |
| **Discovery, low confidence** | same | **$1** |
| **NUK3R2 buy-zone entry** | Fib Bee: a gate-PASS, BUY- or WATCH-ranked token **enters** the buy zone | **$1** |

"Partial" means the Bee does the small, repeatable buys itself and hands everything else to you:

- **Automatic (no click):** discovery-tier and zone-entry **buys** that pass every hard gate and stay
  inside the budget.
- **Waits for your approval:** a buy that trips a *soft* gate (thin liquidity, pair < 24h old, security
  unverifiable, unexplained same-ticker clone), and **every sell / take-profit**.
- **Never:** trading from any wallet but its own, trading an unverified contract, going over budget, or
  arming itself.

---

## How one buy happens

```
Research Bee ──research.verdict──►┐
                                  ├─► Trader Bee ─► intent (one per trigger, crash-safe)
Fib Bee ────fib.zone.entered─────►┘          │
                                             ▼
   1 control   paused? circuit breaker?
   2 research  VERIFIED contract (≥2 sources) · gate PASS · rank BUY/WATCH · not a decoy
   3 budget    $/24h · $/7d · buys/24h · $/asset
   4 market    live DexScreener: liquidity floor, pair age, same-ticker clones (fake-pool guard on)
   5 security  research score ≥ 75 · GoPlus honeypot / blacklist / tax flags
   6 zone      (zone buys) live price STILL inside the buy zone, structure not broken
   7 route     1inch vs KyberSwap race: price impact vs pool mid, round-trip sell quote
   8 funds     (live) stable balance + gas
                                             │
             PASS → execute   ·   SOFT → your approval queue   ·   HARD → rejected (with the reason)
```

In **paper** mode "execute" records a fill at the live best quote and spends nothing. In **live** mode
the executor (Node, adapted from the trading terminal's engine) signs from the Bee's wallet, then
confirms the result from the chain receipt and the wallet balance change, not from the quote.

Take-profit outcomes are tracked from the 1inch orderbook (filled / partial / expired) and booked into
positions. Paper take-profits fill when the price reaches the limit.

After a fill, the Bee **proposes** a take-profit: a resting 1inch limit sell of half the position at
the NSZ edge (21.4% level of the body-high structure). It sits in your approval queue and nothing is
placed until you approve it.

---

## Setup (about 10 minutes)

All commands run inside this folder: `NUK3R2-Trader-Bee-Agent-v1.0.0/trader-bee/`.

1. **Install the executor** (needs Node.js 20+):
   ```
   cd executor && npm install && npm run selftest && cd ..
   ```
   The self-test is offline and should end with `EXECUTOR OFFLINE SELFTEST PASS`.

2. **API keys:** run the walkthrough, `python -m hive setup` from the Hive folder (or double-click
   `HIVE-SETUP-KEYS`). It asks for each key, hides it while you paste, tests it live and saves it to
   `module/.env`. The Bee needs `ONEINCH_API_KEY`; `COINGECKO_API_KEY` and an Alchemy-built
   `BASE_RPC_URL` are recommended. Never paste keys into a chat.

3. **Run in PAPER first** (the default). From the Hive folder, double-click `HIVE.bat` (Windows) or
   `HIVE.command` (Mac), or run `python -m hive start`. Watch the UI at http://127.0.0.1:8790 for
   a few days and check that what it *would* buy matches what you want.

4. **Create the Bee's wallet:**
   ```
   python trader.py wallet-new
   ```
   The key is generated on your machine and written only to `secrets/agent_wallet.key`. Back that file
   up offline. Only the public address is printed.

5. **Fund it** with only what you're willing to let it spend:
   - Base: **USDC** plus about $1–2 of **ETH** for gas
   - Robinhood Chain: **USDG** plus a little **ETH** for gas

   It's the same address on both chains. Check with `python trader.py wallet`.

6. **Verify the pinned routers** in `config/trader_bee.json → execution.allowed_spenders` on each
   chain's explorer. This matters most on Robinhood Chain, where 1inch is deployed at a different
   address. Remove any address you can't confirm; the executor will refuse to use it.

7. **Go live (your act, never Claude's):**
   - edit `config/trader_bee.json`: `"mode": "live"`
   - `python trader.py arm` and type the arm phrase exactly

   To stop instantly: `python trader.py disarm` or the **DISARM** button in the UI. To stop all
   buying without disarming, use `python trader.py pause` or **Pause (kill switch)**.

---

## Daily use

| You want to… | Do this |
|---|---|
| See everything | UI → http://127.0.0.1:8790 · or `python trader.py status` |
| Approve / decline a parked buy or take-profit | UI buttons · or `python trader.py approve <id>` / `decline <id>` |
| Stop buying now | UI **Pause** · `python trader.py pause --reason "..."` |
| Stop live trading | UI **DISARM** · `python trader.py disarm` |
| Sell a position from the Bee wallet | `python trader.py sell --asset SYMBOL --pct 100` (preview) then add `--confirm GO` |
| List decisions | `python trader.py intents` (add `--state REJECTED` etc.) |

Every decision is kept with its reason and the checks behind it: liquidity, pair age, impact,
round-trip loss, and which venue won.

---

## Settings you own (`config/trader_bee.json`)

The Bee never edits this file. Every number is yours.

| Setting | Default | Meaning |
|---|---|---|
| `strategies.discovery_tier.sizes_usd` | high 10 · medium 5 · low 1 | tier sizes |
| `strategies.zone_entry.size_usd` | 1 | buy-zone entry size |
| `…eligible_ranks` | BUY, WATCH | ranks that can trigger |
| `strategies.zone_entry.cooldown_hours` | 24 | minimum gap between zone buys on one token |
| `confidence_bands` | high = Exceptional (Core 45+ / Timing 17+) · medium = Priority Opportunity (40+ / 13+) · else low | your Opportunity Matrix; used only when a verdict has no `confidence` (the Research Bee always sets it) |
| `budget.daily_usd / weekly_usd` | 40 / 150 | rolling 24h / 7d spend caps |
| `budget.max_buys_per_day` | 20 | |
| `budget.max_exposure_per_asset_usd` | 25 | lifetime cap per token |
| `gates.min_security_score` | 75 | your number (operator setting, not a sourced constant) |
| `gates.hard_min_liquidity_usd / soft_min_liquidity_usd` | 25k / 50k | below hard = reject, between = your approval |
| `gates.max_price_impact_pct` | 3 | quote vs pool mid |
| `gates.max_roundtrip_loss_pct` | 12 | buy-then-sell quote loss; catches taxes and honeypots |
| `execution.slippage_pct` | 2 (clamped 0.5–8) | |
| `execution.approval_mode` | exact | token approvals for the exact amount, never unlimited |
| `safety.circuit_breaker_consecutive_failures` | 3 | auto-pause after 3 failed live trades in a row |

**The NUK3R2 buy zone** is set in the Fib Bee's `config/defaults.json → buy_zone`. The default is
**NEZ + NDCAZ**: price has retraced at least 78.6% of the ATL → structural-high move without breaking
the bottom, on **both** the wick-high and body-high structures. Change it there if your strategy defines
the zone differently.

---

## Crash safety (why it can't double-buy)

- Every trigger becomes exactly one intent with a unique key (`discovery:<token>` /
  `zone:<token>:<structure>`). Replays and restarts can't create a second one.
- `SUBMITTING` is written to disk **before** the executor runs. Every broadcast transaction is
  journaled before the Bee waits on it.
- If anything dies mid-trade, the intent becomes `UNKNOWN` and is **reconciled against the chain**
  (receipt plus Transfer logs). It is never re-sent.
- A failure before anything reached the chain is recorded as "not sent" and retried later. A revert
  counts toward the circuit breaker.

## Tests

```
python -m pytest -q tests          # 39 offline tests: every gate, both triggers, budgets, approvals, live + reconcile
cd executor && npm run selftest    # 21 offline checks: units, venue race, pinned spenders, wallet, limit-order signing
```

Not investment advice. The Bee executes your rules. You decide the rules and what it's allowed to spend.
