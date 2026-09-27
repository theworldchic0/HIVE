# Hive Consumer Contract

## Research Agent
Read Market Direction context before research. Record `snapshot_id`. Do not request a full refresh merely because a token entered the queue. If the snapshot is stale, follow Hive refresh policy. Use macro direction as context, never as an automatic BUY trigger.

## Narrative Agent
Use Market Direction as cycle context. Independent narrative evidence remains authoritative for narrative scoring.

## Position Manager
Use the snapshot as context alongside live position/market signals. It is not an execution trigger.

## UI
Show: agent status, snapshot age, regime, final signal/call, 1M/3M/6M/1Y/3Y calls, next refresh, last trigger, source health, communication health.
Green=healthy/current; yellow=degraded/stale warning; red=missing/failed/stale beyond fail-closed window.
