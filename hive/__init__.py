"""NUK3R2 Hive core: shared paths, the event bus, Queen telemetry and data contracts.

Every Hive agent (Queen, Research, Market Direction, Bottom Blueprint, Fib, Trader) stays
independently runnable. This package is only the shared plumbing between them:

  bus.py           append-only JSONL event bus with per-consumer cursors (durable, inspectable)
  contracts.py     the typed event contracts agents hand each other (validated on publish)
  queen_client.py  heartbeats / usage / events into the Queen Bee's SQLite (never raises)
  net.py           one HTTP helper: timeouts, per-host pacing, small TTL cache, telemetry
"""
__version__ = "1.0.0"
