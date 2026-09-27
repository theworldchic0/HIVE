# Trader Bee — Agent Contract v1.0.0

**Mission:** turn two beekeeper-defined signals into small, bounded, verified buys from the Bee's own
wallet, and hand everything else to the beekeeper.

## Consumes (Hive bus)
| Event | From | Used for |
|---|---|---|
| `research.verdict` | Research Bee | asset record (newest verdict wins) + discovery-tier trigger |
| `fib.zone.entered` | Fib Bee | $1 zone-entry trigger (once per structure) |
| `fib.zone.exited` | Fib Bee | expires waiting zone intents |
| `hive.control` (target `trader_bee`) | Queen / beekeeper | pause · resume · disarm |

## Publishes
`trader.intent.created`, `trader.intent.rejected`, `trader.approval.requested`, `trader.trade.executed`,
`trader.trade.failed`, `trader.paused`, `trader.resumed`. Plus Queen heartbeats, provider usage and
failure events.

## Authority
| Action | Allowed |
|---|---|
| BUY discovery tier ($10/$5/$1) / zone entry ($1) from its own wallet, all gates passing, inside budget, while ARMED | **yes, automatically** |
| BUY with a soft finding | only after beekeeper approval (hard gates re-run) |
| SELL / take-profit | only after beekeeper approval, or the beekeeper's own `sell --confirm GO` |
| Arm itself, change config, change budgets/sizes/gates, touch another wallet, trade an unverified contract | **never** |

## Hard rules
1. Identity is CHAIN + VERIFIED CONTRACT (≥2 independent sources). A ticker is never an identity.
2. A broken data source is a reject (retryable), never a pass.
3. Verify against reality: fills are the chain receipt + balance delta; zone buys re-check the live price.
4. One intent per trigger (unique key). Nothing is ever re-sent after a broadcast; unknown outcomes are reconciled.
5. Paper unless config `mode: live` AND the human-made arm file exists AND the Bee's key exists.
6. Circuit breaker: N consecutive live failures → auto-pause.

## States
`PLANNED → REJECTED | NEEDS_APPROVAL → APPROVED | DECLINED → READY → SUBMITTING → CONFIRMED | FAILED | UNKNOWN`,
paper: `READY → PAPER_FILLED`; take-profit: `NEEDS_APPROVAL → PLACED | PAPER_PLACED`; any waiting intent → `EXPIRED`
(zone exit, research downgrade, verdict aged out).
