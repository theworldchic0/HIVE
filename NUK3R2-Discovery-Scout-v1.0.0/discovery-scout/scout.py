#!/usr/bin/env python3
"""NUK3R2 Discovery Scout — the automated front of the Research Bee (Base + Robinhood Chain).

  python scout.py run                 one scan now
  python scout.py watch               scan every `interval_hours` (default 6h)
  python scout.py queue [--all]       the research queue, best-first
  python scout.py dismiss <asset_id|symbol> [--reason ".."]

What it does: pulls trending + new pools from GeckoTerminal (or CoinGecko on-chain when your key is
set), keeps the ones that pass the filters in config/scout.json, and publishes each NEW candidate
as a `research.request` on the Hive bus + the queue file. The Research Bee (your CoinPicks research
in Claude Code) works that queue and publishes verdicts with `discovery: true`.

What it never does: score quality, verify identity, publish a verdict, or touch a wallet. The
scout_score only orders the queue (activity + liquidity) — it is not a buy signal.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1]))

from hive import bus, chains, marketdata, net, queen_client  # noqa: E402
from hive.paths import sub  # noqa: E402

AGENT = "discovery_scout"
CONSUMER = "discovery_scout.verdicts"


def load_config() -> dict:
    return json.loads((ROOT / "config" / "scout.json").read_text(encoding="utf-8"))


def _qfile() -> Path:
    return sub("scout") / "queue.json"


def load_queue() -> dict:
    try:
        return json.loads(_qfile().read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_queue(q: dict) -> None:
    tmp = _qfile().with_suffix(".tmp")
    tmp.write_text(json.dumps(q, indent=1), encoding="utf-8")
    os.replace(tmp, _qfile())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _addr(gid: str | None) -> str:
    return (gid or "").split("_", 1)[-1].lower()


def parse_pool(d: dict, network: str, quotes: set[str]) -> dict | None:
    """One GT pool row → a candidate record (the non-quote side), or None if both sides are quote assets."""
    a = d.get("attributes") or {}
    rel = d.get("relationships") or {}
    base = _addr(((rel.get("base_token") or {}).get("data") or {}).get("id"))
    quote = _addr(((rel.get("quote_token") or {}).get("data") or {}).get("id"))
    names = [x.strip() for x in str(a.get("name") or "").split("/")]
    if base and base not in quotes:
        token, sym, px = base, names[0] if names else "?", a.get("base_token_price_usd")
    elif quote and quote not in quotes:
        token, sym, px = quote, names[1].split(" ")[0] if len(names) > 1 else "?", a.get("quote_token_price_usd")
    else:
        return None
    tx = ((a.get("transactions") or {}).get("h24") or {})
    created = a.get("pool_created_at")
    age_h = None
    if created:
        try:
            age_h = (_now() - datetime.fromisoformat(created.replace("Z", "+00:00"))).total_seconds() / 3600
        except ValueError:
            age_h = None
    return {"chain": network, "contract": token, "symbol": (sym or "?")[:24], "pool": (a.get("address") or "").lower(),
            "pool_name": a.get("name"), "price_usd": float(px) if px else None,
            "liquidity_usd": float(a.get("reserve_in_usd") or 0), "volume_24h_usd": float((a.get("volume_usd") or {}).get("h24") or 0),
            "buys_24h": int(tx.get("buys") or 0), "sells_24h": int(tx.get("sells") or 0),
            "change_24h_pct": float((a.get("price_change_percentage") or {}).get("h24") or 0), "pool_age_hours": age_h}


def filter_reasons(c: dict, f: dict) -> list[str]:
    """Empty list = passes. Otherwise the reasons it was filtered out (kept for transparency)."""
    why = []
    if c["liquidity_usd"] < f["min_liquidity_usd"]:
        why.append(f"liquidity ${c['liquidity_usd']:,.0f} < ${f['min_liquidity_usd']:,}")
    if c["volume_24h_usd"] < f["min_volume_24h_usd"]:
        why.append(f"24h volume ${c['volume_24h_usd']:,.0f} < ${f['min_volume_24h_usd']:,}")
    if c["pool_age_hours"] is None:
        why.append("pool age unknown")
    else:
        if c["pool_age_hours"] < f["min_pool_age_hours"]:
            why.append(f"pool only {c['pool_age_hours']:.0f}h old")
        if c["pool_age_hours"] > f["max_pool_age_days"] * 24:
            why.append(f"pool older than {f['max_pool_age_days']}d (not a discovery)")
    if c["buys_24h"] < f["min_buys_24h"]:
        why.append(f"only {c['buys_24h']} buys in 24h")
    if c["sells_24h"] and c["buys_24h"] / c["sells_24h"] < f["min_buy_sell_ratio"]:
        why.append(f"buy/sell ratio {c['buys_24h'] / c['sells_24h']:.2f} < {f['min_buy_sell_ratio']}")
    if c["sells_24h"] == 0 and c["buys_24h"] > 0:
        why.append("zero sells in 24h (possible sell restriction)")
    if abs(c["change_24h_pct"]) > f["max_abs_change_24h_pct"]:
        why.append(f"24h change {c['change_24h_pct']:+.0f}% (too extreme to read)")
    return why


def score(c: dict) -> float:
    """Queue ORDER only: activity relative to depth + buyer share + depth. Not a quality signal."""
    turnover = min(1.0, c["volume_24h_usd"] / max(c["liquidity_usd"], 1))
    buy_share = c["buys_24h"] / max(c["buys_24h"] + c["sells_24h"], 1)
    depth = math.log10(max(c["liquidity_usd"], 1) / 50_000 + 1)
    return round(10 * turnover + 6 * buy_share + 3 * depth, 2)


def mark_researched(q: dict) -> int:
    n = 0
    for end, ev in bus.consume(CONSUMER, {"research.verdict"}):
        aid = ev["payload"]["asset_id"]
        if aid in q and q[aid]["status"] == "QUEUED":
            q[aid].update(status="RESEARCHED", researched_at=ev["payload"]["researched_at"], verdict_rank=ev["payload"]["rank"],
                          verdict_gate=ev["payload"]["gate"]["result"])
            n += 1
        bus.ack(CONSUMER, end)
    return n


def run_once(cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    q = load_queue()
    summary = {"at": _iso(_now()), "scanned": 0, "passed": 0, "new": 0, "researched": mark_researched(q), "errors": []}
    seen_now: dict[str, dict] = {}
    for network in cfg["networks"]:
        c = chains.get(network)
        if not c:
            summary["errors"].append(f"{network}: unknown chain")
            continue
        quotes = {x.lower() for x in cfg["quote_assets"].get(network, [])} | {c["stable"]["contract"].lower()}
        for source in cfg["sources"]:
            for page in range(1, cfg["pages_per_source"] + 1):
                try:
                    j = marketdata._onchain(f"/networks/{c['gt_network']}/{source}?page={page}", AGENT, source, ttl_s=300)
                except net.NetError as e:
                    summary["errors"].append(f"{network}/{source} p{page}: {str(e)[:120]}")
                    queen_client.event(AGENT, "scan", False, message=f"{network}/{source}: {e}")
                    break
                for d in (j or {}).get("data") or []:
                    cand = parse_pool(d, network, quotes)
                    if not cand:
                        continue
                    summary["scanned"] += 1
                    aid = f"{network}:{cand['contract']}"
                    if filter_reasons(cand, cfg["filters"]):  # any reason = filtered out
                        continue
                    best = seen_now.get(aid)
                    if not best or cand["liquidity_usd"] > best["liquidity_usd"]:  # keep the deepest pool per token
                        seen_now[aid] = {**cand, "source": source}
    summary["passed"] = len(seen_now)
    # same-ticker collisions inside this scan are flagged for research (the VEX/DRB/WOOD lesson)
    by_sym: dict[tuple, int] = {}
    for c_ in seen_now.values():
        by_sym[(c_["chain"], c_["symbol"].upper())] = by_sym.get((c_["chain"], c_["symbol"].upper()), 0) + 1
    fresh = []
    now = _now()
    for aid, c_ in seen_now.items():
        prev = q.get(aid)
        if prev:
            prev["last_seen"] = _iso(now)
            prev["times_seen"] = prev.get("times_seen", 1) + 1
            last = datetime.fromisoformat(prev.get("requested_at", prev["first_seen"]).replace("Z", "+00:00"))
            if prev["status"] != "DISMISSED" and prev["status"] != "QUEUED" and (now - last).days >= cfg["requeue_after_days"]:
                prev["status"] = "QUEUED"  # re-surface a long-researched token that is active again
                fresh.append((aid, c_))
            continue
        fresh.append((aid, c_))
    fresh.sort(key=lambda x: -score(x[1]))
    for aid, c_ in fresh[: cfg["max_new_per_run"]]:
        reasons = [f"{c_['source'].replace('_', ' ')} on {c_['chain']}", f"liq ${c_['liquidity_usd']:,.0f}",
                   f"24h vol ${c_['volume_24h_usd']:,.0f}", f"{c_['buys_24h']} buys / {c_['sells_24h']} sells",
                   f"pool {c_['pool_age_hours']:.0f}h old"]
        if by_sym[(c_["chain"], c_["symbol"].upper())] > 1:
            reasons.append("⚠ another token with the SAME TICKER also surfaced — verify the contract carefully")
        payload = {"asset_id": aid, "chain": c_["chain"], "contract": c_["contract"], "symbol": c_["symbol"], "name": c_["pool_name"],
                   "source": f"discovery_scout/{c_['source']}", "pool": c_["pool"],
                   "observed": {k: c_[k] for k in ("price_usd", "liquidity_usd", "volume_24h_usd", "buys_24h", "sells_24h", "change_24h_pct", "pool_age_hours")},
                   "scout_score": score(c_), "reasons": reasons, "requested_by": AGENT}
        bus.publish("research.request", AGENT, payload)
        q[aid] = {**q.get(aid, {}), **payload, "status": "QUEUED", "first_seen": q.get(aid, {}).get("first_seen", _iso(now)),
                  "last_seen": _iso(now), "requested_at": _iso(now), "times_seen": q.get(aid, {}).get("times_seen", 1)}
        summary["new"] += 1
    save_queue(q)
    queen_client.heartbeat(AGENT, "healthy" if not summary["errors"] else "degraded", "; ".join(summary["errors"])[:300])
    return summary


def queue_rows(show_all: bool = False) -> list[dict]:
    q = load_queue()
    rows = [r for r in q.values() if show_all or r["status"] == "QUEUED"]
    return sorted(rows, key=lambda r: (r["status"] != "QUEUED", -(r.get("scout_score") or 0)))


def dismiss(key: str, reason: str) -> int:
    q = load_queue()
    k = key.lower()
    hits = [aid for aid, r in q.items() if aid == k or r["symbol"].lower() == k]
    for aid in hits:
        q[aid].update(status="DISMISSED", dismissed_reason=reason, dismissed_at=_iso(_now()))
    save_queue(q)
    return len(hits)


def main() -> int:
    p = argparse.ArgumentParser()
    s = p.add_subparsers(dest="cmd", required=True)
    s.add_parser("run")
    w = s.add_parser("watch")
    w.add_argument("--interval-hours", type=float, default=None)
    qq = s.add_parser("queue")
    qq.add_argument("--all", action="store_true")
    qq.add_argument("--json", action="store_true")
    d = s.add_parser("dismiss")
    d.add_argument("key")
    d.add_argument("--reason", default="beekeeper dismissed")
    a = p.parse_args()
    if a.cmd == "run":
        print(json.dumps(run_once(), indent=2))
    elif a.cmd == "watch":
        every = (a.interval_hours or load_config()["interval_hours"]) * 3600
        while True:
            try:
                print(json.dumps(run_once()), flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"scan failed: {e}", file=sys.stderr, flush=True)
                queen_client.event(AGENT, "scan", False, message=str(e))
            time.sleep(every)
    elif a.cmd == "queue":
        rows = queue_rows(a.all)
        if a.json:
            print(json.dumps(rows, indent=2))
        else:
            for r in rows:
                o = r["observed"]
                print(f"{r['status']:<10} {r.get('scout_score', 0):>5}  {r['symbol']:<12} {r['chain']:<9} {r['contract']}  "
                      f"liq ${o['liquidity_usd']:,.0f} vol ${o['volume_24h_usd']:,.0f}")
            if not rows:
                print("queue empty")
    elif a.cmd == "dismiss":
        print(f"dismissed {dismiss(a.key, a.reason)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
