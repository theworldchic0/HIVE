"""Telemetry into the Queen Bee (heartbeats, provider usage, handoff/failure events).

Loads the Queen's own queen.py so its schema and severity logic stay the single source of
truth. Telemetry is best-effort by design: a Queen problem must never block an agent's work,
but it is never silent either — failures are printed to stderr and counted.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from types import SimpleNamespace

from .paths import QUEEN_DIR

_queen = None
failures = 0


def _load():
    global _queen
    if _queen is None:
        spec = importlib.util.spec_from_file_location("hive_queen", QUEEN_DIR / "scripts" / "queen.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        _queen = mod
    return _queen


def _safe(fn, *a):
    global failures
    try:
        fn(*a)
        return True
    except Exception as e:  # noqa: BLE001 — telemetry must not crash an agent
        failures += 1
        print(f"[hive.queen_client] telemetry failed: {e}", file=sys.stderr)
        return False


def heartbeat(agent: str, status: str = "healthy", message: str = "") -> bool:
    return _safe(lambda: _load().heartbeat(agent, status, message))


def usage(agent: str, provider: str, operation: str = "", calls: int = 1, latency_ms: float = 0,
          cache_hits: int = 0, failures_: int = 0, query_hash: str = "", metadata: dict | None = None) -> bool:
    ns = SimpleNamespace(agent=agent, provider=provider, operation=operation, calls=calls, input_tokens=0,
                         output_tokens=0, cost=None, latency_ms=latency_ms, cache_hits=cache_hits,
                         failures=failures_, query_hash=query_hash, metadata=json.dumps(metadata or {}))
    return _safe(lambda: _load().usage(ns))


def event(agent: str, event_type: str, success: bool, target: str = "", correlation_id: str = "",
          message: str = "", metadata: dict | None = None) -> bool:
    ns = SimpleNamespace(agent=agent, event_type=event_type, success=success, target=target,
                         correlation_id=correlation_id, message=message[:500], metadata=json.dumps(metadata or {}))
    return _safe(lambda: _load().event(ns))


def snapshot() -> dict:
    """The Queen's latest audit (agents' green/yellow/red, usage, open recommendations)."""
    try:
        return _load().audit()
    except Exception as e:  # noqa: BLE001
        return {"error": f"queen unavailable: {e}", "agents": []}
