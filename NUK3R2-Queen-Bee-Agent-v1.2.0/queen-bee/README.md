# NUK3R2 Queen Bee Agent v1.0.0

The Queen Bee is the Hive's autonomous operations, observability, and optimization supervisor.

**Human role:** The user is the **Beekeeper**. The Queen is an agent inside the Hive. The Queen does not replace the Beekeeper, make trading decisions, or auto-buy.

## Mission

1. Monitor every registered agent and sub-agent.
2. Verify each agent is performing its assigned job.
3. Monitor agent-to-agent communication and handoffs.
4. Track research/API/search usage and identify waste.
5. Detect stale data, repeated searches, provider failures, queue stalls, and schema drift.
6. Produce optimization recommendations and safe operational actions.
7. Protect the Lifetime Master List as the central research memory.
8. Maintain a live Hive health state for the UI.

## Important boundary

The Queen is an **operations supervisor**, not an investment decision-maker. It may stop/retry/re-route jobs and recommend research optimizations, but it cannot turn an operational health signal into a BUY order.

## Usage

```bash
python3 scripts/queen.py status
python3 scripts/queen.py audit
python3 scripts/queen.py optimize
python3 scripts/queen.py heartbeat research_agent --status healthy
python3 scripts/queen.py usage --agent research_agent --provider coingecko --calls 4 --input-tokens 1200 --output-tokens 340
python3 scripts/queen.py event --agent research_agent --event-type handoff --success true
```

The agent uses SQLite for operational state and can export a UI-friendly JSON snapshot.

## Token usage

The Queen cannot magically observe tokens consumed by an external model/runtime. Agents must emit usage telemetry through the usage endpoint/CLI. The schema supports provider calls, estimated/actual input and output tokens, latency, cache hits, failures, and cost when available.

This makes optimization measurable without pretending that unavailable telemetry exists.
