# Market Direction Hive Runbook

## Weekly
1. Run the original engine's `run.py quant`.
2. Perform the original qualitative research cycle under its existing runbook.
3. Run `run.py blend`.
4. Run `run.py selfcheck`.
5. Build and publish the normalized Hive snapshot.
6. Archive the prior snapshot.

## Daily
Run `python hive_market_direction.py check`.

If the result is `NO_CHANGE`, consumers continue using the current snapshot. If it is `REFRESH_REQUIRED` or `STALE`, perform a full update rather than patching the direction score.

## Consumer contract
Research calls `python hive_market_direction.py context` and records the snapshot ID, timestamp, age, regime/calls, and health state. It does not request a full macro run for every token.
