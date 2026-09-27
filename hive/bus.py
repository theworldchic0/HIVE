"""The Hive event bus: one append-only JSONL file plus a byte-offset cursor per consumer.

Why a file and not a broker: every agent here is a small independently runnable program on
one machine. A JSONL log is durable across crashes, trivially inspectable ("what did the
Research Bee hand the Trader Bee at 03:12?" is a text search), and needs no service to
be running. Events are never edited or deleted — history is the audit trail.

Delivery is at-least-once: a consumer acks the offset after it has durably handled an
event. Consumers MUST be idempotent (the Trader Bee is: every intent has a unique key).
"""
from __future__ import annotations

import json
import os
import secrets
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from . import contracts
from .paths import sub

if os.name == "nt":  # Windows
    import msvcrt

    def _lock(f):
        f.seek(0)
        while True:
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
                return
            except OSError:
                time.sleep(0.05)

    def _unlock(f):
        f.seek(0)
        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
else:
    import fcntl

    def _lock(f):
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)

    def _unlock(f):
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _bus_dir() -> Path:
    return sub("bus")


def events_file() -> Path:
    return _bus_dir() / "events.jsonl"


@contextmanager
def _locked():
    lock_path = _bus_dir() / ".lock"
    with open(lock_path, "a+b") as f:
        _lock(f)
        try:
            yield
        finally:
            _unlock(f)


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_id(prefix: str = "EV") -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}-{secrets.token_hex(3)}"


def publish(event_type: str, source: str, payload: dict, correlation_id: str = "") -> dict:
    """Validate against the contract, then append atomically. Raises ContractError on bad payloads —
    a malformed handoff is refused at the door rather than discovered downstream."""
    contracts.validate(event_type, payload)
    ev = {
        "id": new_id(),
        "ts": utcnow(),
        "type": event_type,
        "source": source,
        "correlation_id": correlation_id or "",
        "payload": payload,
    }
    line = json.dumps(ev, separators=(",", ":"), sort_keys=True) + "\n"
    with _locked():
        with open(events_file(), "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
    return ev


def _cursor_file(consumer: str) -> Path:
    safe = "".join(c for c in consumer if c.isalnum() or c in "-_")
    return sub("bus", "cursors") / f"{safe}.json"


def cursor(consumer: str) -> int:
    p = _cursor_file(consumer)
    if not p.exists():
        return 0
    try:
        return int(json.loads(p.read_text())["offset"])
    except Exception:
        return 0


def ack(consumer: str, offset: int) -> None:
    p = _cursor_file(consumer)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"offset": offset, "acked_at": utcnow()}))
    os.replace(tmp, p)


def read_from(offset: int, types: set[str] | None = None) -> Iterator[tuple[int, dict]]:
    """Yield (end_offset, event) for complete lines after `offset`. A torn trailing line (writer
    mid-append) is left for the next read, never half-parsed."""
    f_path = events_file()
    if not f_path.exists():
        return
    with open(f_path, "rb") as f:
        f.seek(offset)
        while True:
            line = f.readline()
            if not line or not line.endswith(b"\n"):
                return
            end = f.tell()
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue  # corrupt line: skipped, still visible in the file for audit
            if types is None or ev.get("type") in types:
                yield end, ev


def consume(consumer: str, types: set[str] | None = None, limit: int = 500) -> list[tuple[int, dict]]:
    """Events this consumer has not acked yet (oldest first). Call ack(consumer, end_offset) after
    each is durably handled."""
    out = []
    for end, ev in read_from(cursor(consumer), types):
        out.append((end, ev))
        if len(out) >= limit:
            break
    return out


def advance_past_unmatched(consumer: str, types: set[str]) -> None:
    """Move the cursor to the end of the file when nothing pending matches (keeps reads short)."""
    start = last = cursor(consumer)
    for end, ev in read_from(last):
        if ev.get("type") in types:
            break
        last = end
    if last != start:
        ack(consumer, last)


def tail(n: int = 50, types: set[str] | None = None) -> list[dict]:
    evs = [ev for _, ev in read_from(0, types)]
    return evs[-n:]
