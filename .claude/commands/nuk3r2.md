---
description: Run the full NUK3R2 Phase 1 research on a ticker or contract (e.g. /nuk3r2 PONS · /nuk3r2 HOOKR | Robinhood Chain · /nuk3r2 0x…)
argument-hint: TICKER | chain   or   CONTRACT
---
Research `$ARGUMENTS` with the NUK3R2 Phase 1 method. Hand the whole job to the `nuk3r2-researcher`
subagent with the exact query `$ARGUMENTS`, then show the beekeeper the finished one-page report (the
report.md it wrote), the gate/Core/Timing numbers and what publishing would trigger in the Hive. Do NOT
publish the verdict until the beekeeper explicitly says to (then use the `hive-verdict` skill).
