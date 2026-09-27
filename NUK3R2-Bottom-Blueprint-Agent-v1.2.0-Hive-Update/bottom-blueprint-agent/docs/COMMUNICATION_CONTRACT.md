# Bottom Blueprint Observatory ↔ Hive Contract v2

### Provides
- current Blueprint window state;
- current window day/total days;
- days to bottom center and momentum center;
- published snapshot id;
- candidate cohort membership;
- performance observations;
- timing accuracy observations;
- immutable historical snapshots.

### Receives
- `bottom_blueprint_candidate` events from Research Bee;
- market observations required to evaluate the published condition;
- Narrative/Meta observations when a candidate's family or curve changes.

### Never does
- rewrite the original Blueprint;
- use future performance to change historical labels;
- execute trades;
- declare a model successful/failed before sufficient observations exist.
