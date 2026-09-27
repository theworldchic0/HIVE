# 🐝 The NUK3R2 Hive: how the pieces fit

You're the **Beekeeper**. The Hive is a set of small agents, each one runnable on its own, that pass
typed messages over one shared event bus. The trading terminal (`module/`, `cockpit/`) is still here
and unchanged. The Trader Bee borrowed its execution engine: the 1inch/KyberSwap race, 1inch limit
orders, the fake-pool guard and the registry discipline.

```
                ┌────────────────────── Queen Bee (health, usage, waste, proposals) ──────────────────────┐
                │                         heartbeats · provider usage · failures                           │
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
| Research Bee | Claude Code + `.claude/skills/hive-verdict/` | when you research | no |
| Market Direction | `NUK3R2-Market-Direction-Agent-v1.1.0-Hive-Update/` | weekly | no |
| Bottom Blueprint Observatory | `NUK3R2-Bottom-Blueprint-Agent-v1.2.0-Hive-Update/` | clock | no |
| Fib Bee | `NUK3R2_Fib_Agent_v0.1.0/…` (v0.2.0) | every 15 min | no |
| **Trader Bee** | `NUK3R2-Trader-Bee-Agent-v1.0.0/trader-bee/` | every 60 s | **buys only, own wallet, bounded; paper until you arm it** |

## Run it
```
python -m hive start        # Fib Bee watcher + Trader Bee loop + UI   (or double-click HIVE.bat / HIVE.command)
python -m hive demo         # offline demo with FAKE tokens in hive_data_demo/ on :8791 (no network, no money)
python -m hive tail -n 30   # what just moved on the bus
```
Requirements: Python 3.10+ (standard library only) and Node.js 20+ for the Trader Bee executor
(`cd NUK3R2-Trader-Bee-Agent-v1.0.0/trader-bee/executor && npm install`).

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
```

## Known limits (said plainly)
- **Nothing here has touched a live market yet.** It was built in a sandbox with no internet access to
  DexScreener, GeckoTerminal, 1inch, KyberSwap or the chains. Every path is tested against fakes that
  follow those APIs' documented formats. **Run PAPER mode first.** The first live buy should be a $1
  one you watch.
- **Robinhood Chain router addresses** must be confirmed by you on the chain's explorer before
  arming there (see the Trader Bee README, step 6).
- **Take-profit fills** placed on the 1inch orderbook are recorded as `PLACED`. Fills are checked with
  the terminal's `node module/check-orders.mjs`; the Bee doesn't book limit fills into P&L yet.
- **The Research Bee has no automated scanner in this repo.** Verdicts come from your CoinPicks research
  sessions via `hive publish`. The 6-hour Base/RH discovery engine from your brief isn't built yet.
- **Market Direction** has no published snapshot yet (`status: MISSING`); the UI says so rather than
  inventing one.
