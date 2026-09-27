"""One HTTP helper for every Python agent: timeouts, per-host pacing, a small TTL cache,
one retry on 429/5xx, and Queen usage telemetry.

Pacing exists because the Aug-24 scan proved it: GeckoTerminal rate-limits after ~4 rapid
calls, and 2.6 s spacing kept it clean. Rate limits — not token cost — are the binding
constraint on a multi-chain scan, so they are enforced here, once, for everybody.

A failed call raises NetError. Callers must treat that as "source broken", never as
"the data is missing" (API failure is not genuine missing information).
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from . import queen_client

MIN_INTERVAL_S = {
    "api.geckoterminal.com": 2.6,
    "api.coingecko.com": 2.6,
    "pro-api.coingecko.com": 0.3,
    "api.dexscreener.com": 0.25,
    "api.gopluslabs.io": 1.0,
    "api.llama.fi": 0.5,
    "coins.llama.fi": 0.5,
    "api.exchange.coinbase.com": 0.35,
}
USER_AGENT = "NUK3R2-Hive/1.0 (+local)"

_last_call: dict[str, float] = {}
_cache: dict[str, tuple[float, object]] = {}
_lock = threading.Lock()

# Tests (and offline replays) swap this for a fake: transport(url, headers, body, timeout) -> (status, bytes)
transport = None


class NetError(RuntimeError):
    def __init__(self, msg: str, status: int | None = None):
        super().__init__(msg)
        self.status = status


def _pace(host: str):
    gap = MIN_INTERVAL_S.get(host, 0.0)
    with _lock:
        wait = _last_call.get(host, 0) + gap - time.monotonic()
        _last_call[host] = max(time.monotonic(), _last_call.get(host, 0) + gap)
    if wait > 0:
        time.sleep(wait)


def _do(url, headers, body, timeout):
    if transport is not None:
        return transport(url, headers, body, timeout)
    req = urllib.request.Request(url, data=body, headers=headers, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() if hasattr(e, "read") else b""


def fetch_json(url: str, *, headers: dict | None = None, body: dict | None = None, ttl_s: float = 0,
               timeout: float = 15, agent: str = "hive", operation: str = ""):
    host = urlparse(url).netloc
    key = hashlib.sha1((url + json.dumps(body, sort_keys=True) if body else url).encode()).hexdigest()
    if ttl_s > 0:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < ttl_s:
            # no query_hash on a cache hit: the Queen's duplicate-search audit must count real provider calls only
            queen_client.usage(agent, host, operation, calls=0, cache_hits=1)
            return hit[1]
    h = {"Accept": "application/json", "User-Agent": USER_AGENT, **(headers or {})}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    last_err: NetError | None = None
    for attempt in range(2):
        _pace(host)
        t0 = time.monotonic()
        try:
            status, raw = _do(url, h, data, timeout)
        except Exception as e:  # noqa: BLE001 — network layer: DNS, TLS, timeouts
            last_err = NetError(f"{host}: {type(e).__name__}: {e}")
            status, raw = None, b""
        ms = (time.monotonic() - t0) * 1000
        if status == 200:
            try:
                out = json.loads(raw or b"null")
            except json.JSONDecodeError as e:
                queen_client.usage(agent, host, operation, latency_ms=ms, failures_=1, query_hash=key)
                raise NetError(f"{host}: invalid JSON ({e})", status) from e
            queen_client.usage(agent, host, operation, latency_ms=ms, query_hash=key)
            if ttl_s > 0:
                _cache[key] = (time.time(), out)
            return out
        queen_client.usage(agent, host, operation, latency_ms=ms, failures_=1, query_hash=key)
        if status is not None:
            last_err = NetError(f"{host}: HTTP {status}: {raw[:160]!r}", status)
        if status in (429, 500, 502, 503, 504) or status is None:
            time.sleep(3 if status == 429 else 1)
            continue
        break
    raise last_err or NetError(f"{host}: request failed")


def fetch_text(url: str, *, timeout: float = 12, max_bytes: int = 2_000_000, agent: str = "hive", operation: str = "") -> str:
    """Plain GET for HTML/text (official project sites). Raises NetError on failure."""
    host = urlparse(url).netloc
    _pace(host)
    t0 = time.monotonic()
    try:
        status, raw = _do(url, {"User-Agent": "Mozilla/5.0 (NUK3R2-Hive research)", "Accept": "text/html,*/*"}, None, timeout)
    except Exception as e:  # noqa: BLE001
        queen_client.usage(agent, host, operation, failures_=1)
        raise NetError(f"{host}: {type(e).__name__}: {e}") from e
    queen_client.usage(agent, host, operation, latency_ms=(time.monotonic() - t0) * 1000, failures_=0 if status == 200 else 1)
    if status != 200:
        raise NetError(f"{host}: HTTP {status}", status)
    return (raw or b"")[:max_bytes].decode("utf-8", errors="ignore")
