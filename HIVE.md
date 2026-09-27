# 🐝 The NUK3R2 Hive: how the pieces fit

> **New here? Read [`START-HERE.md`](START-HERE.md)** — install, the API-key walkthrough, first run.

You're the **Beekeeper**. The Hive is a set of small agents, each one runnable on its own, that pass
typed messages over one shared event bus. The trading terminal (`module/`, `cockpit/`) is still here
and unchanged. The Trader Bee borrowed its execution engine: the 1inch/KyberSwap race, 1inch limit
orders, the fake-pool guard and the registry discipline.

```
                ┌────────────────────── Queen Bee (health, usage, waste, proposals) ──────────────────────┐
                │                         heartbeats · provider usage · failures                           │
  Discovery Scout ─ research.request (queue) ─► Research Bee
  Research Bee ─┼─ research.verdict ─┬──────────────► Fib Bee ── fib.zone.entered/exited ──┐              │
  (Claude Code, │                    │                (structures + zones, no wallet)     │              │
   CoinPicks)   │                    └──────────────────────────────────────────────────► Trader Bee ───┼─► its own wallet
                │                                                                          (bounded     │   (Base + Robinhood)
  Market Direction ─ snapshot (context only) ─────────────────────────────────────────────  auto-buys)  │
  Bottom Blueprint ─ cycle clock (always-visible banner) ─────────────────────────────────────────────  │
                └──────────────────────────── Hive UI  http://127.0.0.1:8790 ─────────────────────────────┘
```

| Agent | Folder | Runs | Can trade? |
|---|---|---|---|
| Queen Bee | `NUK3R2-Queen-Bee-Agent-v1.2.0/` | on demand (`scripts/queen.py audit`) and as telemetry sink | no (may pause/disarm the Trader Bee) |
| **Meta Bee** | `NUK3R2-Meta-Bee-v1.0.0/meta-bee/` | nonstop (workers every 15 min–6 h) | no (meta board: daily / weekly / monthly curves) |
| Discovery Scout | `NUK3R2-Discovery-Scout-v1.0.0/discovery-scout/` | every 6 h | no (queues candidates for research only) |
| **Research Bee** | `NUK3R2-Research-Bee-v1.0.0/research-bee/` + `/nuk3r2 TICKER` in Claude Code | when you research | no (writes the report + verdict; you publish) |
| Market Direction | `NUK3R2-Market-Direction-Agent-v1.1.0-Hive-Update/` | weekly | no |
| Bottom Blueprint Observatory | `NUK3R2-Bottom-Blueprint-Agent-v1.2.0-Hive-Update/` | clock + passer cohort every 6 h | no (tracks every PASS vs BTC until bull end / 5th halving) |
| Fib Bee | `NUK3R2_Fib_Agent_v0.1.0/…` (v0.2.0) | every 15 min | no |
| **Trader Bee** | `NUK3R2-Trader-Bee-Agent-v1.0.0/trader-bee/` | every 60 s | **buys only, own wallet, bounded; paper until you arm it** |

## Run it
```
python -m hive start        # first run: API-key walkthrough, then Scout + Fib Bee + Trader Bee + UI (HIVE.bat / HIVE.command)
python -m hive setup        # the key walkthrough on its own (HIVE-SETUP-KEYS.bat / .command)
python -m hive doctor       # health check: every key tested live, RPCs, executor, agents
python -m hive demo         # offline demo with FAKE tokens in hive_data_demo/ on :8791 (no network, no money)
python -m hive tail -n 30   # what just moved on the bus
```
Requirements: Python 3.10+ (standard library only) and Node.js 20+ for the Trader Bee executor
(`cd NUK3R2-Trader-Bee-Agent-v1.0.0/trader-bee/executor && npm install`).

## Research: paste a ticker
In Claude Code, inside this folder: **`/nuk3r2 PONS`** (or `HOOKR | Robinhood Chain`, or a contract). The
Research Bee runs your full Phase 1 method: facts collected by code, judgments made by Claude with
evidence for every score, math and report by `score.py`. You read the one-page report, then publish.
The Meta Bee's curves are included as supporting evidence.

## How research reaches the Trader Bee
The Research Bee (a Claude Code session running the CoinPicks method) finishes a token and writes a
**verdict** file in the contract format (`hive/contracts/research.verdict.schema.json`; see
`hive/contracts/examples/`). Then:
```
python -m hive validate --type research.verdict --file verdict.json
python -m hive publish  --type research.verdict --file verdict.json
```
Publishing checks the contract first and refuses a bad handoff at the door. After that, everything
downstream is automatic: the Fib Bee starts watching BUY/WATCH tokens, and the Trader Bee sizes
discovery buys and waits for zone entries.

## Where the state lives
`hive_data/` (git-ignored, local): `bus/events.jsonl` (append-only history of every handoff),
`fib_agent/state.json` plus `observations.jsonl`, `trader_bee/trader_bee.db` (every decision with its
reasons), and `trader_bee/exec-journal.jsonl` (every broadcast tx). The Queen keeps its own
`NUK3R2-Queen-Bee-Agent-v1.2.0/queen-bee/data/queen.db`.

## Tests (all offline)
```
python -m pytest -q hive/tests
cd NUK3R2_Fib_Agent_v0.1.0/NUK3R2_Fib_Agent_v0.1.0 && python -m pytest -q tests
cd NUK3R2-Trader-Bee-Agent-v1.0.0/trader-bee && python -m pytest -q tests && (cd executor && npm run selftest)
cd NUK3R2-Bottom-Blueprint-Agent-v1.2.0-Hive-Update/bottom-blueprint-agent && python -m pytest -q tests
cd NUK3R2-Discovery-Scout-v1.0.0/discovery-scout && python -m pytest -q tests
cd NUK3R2-Research-Bee-v1.0.0/research-bee && python -m pytest -q tests
cd NUK3R2-Meta-Bee-v1.0.0/meta-bee && python -m pytest -q tests
```

## Known limits (said plainly)
- **Nothing here has touched a live market yet.** It was built in a sandbox with no internet access to
  DexScreener, GeckoTerminal, 1inch, KyberSwap or the chains. Every path is tested against fakes that
  follow those APIs' documented formats. **Run PAPER mode first.** The first live buy should be a $1
  one you watch.
- **Robinhood Chain router addresses** must be confirmed by you on the chain's explorer before
  arming there (see the Trader Bee README, step 6).
- **Take-profit fills** are read from the 1inch orderbook every few minutes (filled / partial / expired)
  and booked into positions; paper take-profits fill when the price reaches the limit.
- **The Discovery Scout finds candidates, not verdicts.** Scoring (gate, rank, confidence) is still your
  CoinPicks research in Claude Code, published with the `hive-verdict` skill. That's deliberate: nothing
  the Scout finds can trigger a buy until research has passed it.
- **Market Direction** has no published snapshot yet (`status: MISSING`); the UI says so rather than
  inventing one.
