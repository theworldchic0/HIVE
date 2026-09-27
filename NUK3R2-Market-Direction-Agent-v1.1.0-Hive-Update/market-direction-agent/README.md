# NUK3R2 Market Direction Agent v1.1.0

Independent macro context provider.

## Cadence
Default scheduled refresh is **weekly**. A material trigger can force an early refresh. Research requests do not automatically rerun the entire macro model; they retrieve the latest cached snapshot and only refresh if it is stale or a material trigger is active.

This keeps the Hive fast and avoids burning provider calls/tokens while still giving the Research Bee current market context.

## Handoff
Research Bee consumes the latest `snapshot_id`, timestamp and freshness state on every deep research event. Narrative Bee may read the context for interpretation. Bottom Blueprint Observatory may use it as contextual evidence but does not rewrite Blueprint dates.

The agent remains independently runnable.
