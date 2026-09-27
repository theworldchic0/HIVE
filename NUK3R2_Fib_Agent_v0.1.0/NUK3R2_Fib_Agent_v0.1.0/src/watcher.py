"""Fib Bee zone watcher — the live half of the Fib Agent.

Loop (every `watcher.interval_seconds`):
  1. Read new research.verdict events. The watchlist = newest verdict per asset where the gate
     PASSED and rank is in watchlist.start_statuses (BUY / WATCH). A newer verdict that drops
     the asset (FAIL / AVOID) removes it.
  2. For each watched asset: resolve the pool (research canonical_pool, else the top
     poison-guarded pool, labeled auto_resolved), fetch daily candles (cached ~6h), build the
     Wick + Body structures, read the live price, classify the zone.
  3. Publish fib.zone.entered when the asset moves INTO the buy zone (or a new structure is born
     with price already inside it), fib.zone.exited when it leaves. Every transition is also
     appended to the immutable observation log.

No wallet, no trading permission. It only tells the Hive where price sits on the structure.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from hive import bus, marketdata, net, queen_client
from hive.paths import sub

from .structure import build
from .zones import zone_for_price

AGENT = "fib_agent"
CONSUMER = "fib_agent.watchlist"
ROOT = Path(__file__).resolve().parents[1]


def load_config() -> dict:
    return json.loads((ROOT / "config" / "defaults.json").read_text(encoding="utf-8"))


def _state_path() -> Path:
    return sub("fib_agent") / "state.json"


def load_state() -> dict:
    p = _state_path()
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"watchlist": {}, "assets": {}}


def save_state(s: dict) -> None:
    p = _state_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def observe(record: dict) -> None:
    with open(sub("fib_agent") / "observations.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ingest_verdicts(state: dict, cfg: dict) -> int:
    """Fold new research verdicts into the watchlist. Returns how many were read."""
    statuses = set(cfg["watchlist"]["start_statuses"])
    need_pass = cfg["watchlist"].get("require_gate_pass", True)
    n = 0
    for end, ev in bus.consume(CONSUMER, {"research.verdict"}):
        v = ev["payload"]
        aid = v["asset_id"]
        prev = state["watchlist"].get(aid)
        if prev and prev.get("researched_at", "") > v["researched_at"]:
            bus.ack(CONSUMER, end)
            continue  # an older verdict arriving late never overrides a newer one
        eligible = (v["rank"] in statuses and (v["gate"]["result"] == "PASS" or not need_pass)
                    and v["identity"]["status"] == "VERIFIED")
        if eligible:
            state["watchlist"][aid] = {
                "asset_id": aid, "chain": v["chain"], "contract": v["contract"], "symbol": v["symbol"],
                "rank": v["rank"], "researched_at": v["researched_at"],
                "pool": (v["identity"].get("canonical_pool") or None), "pool_source": "research" if v["identity"].get("canonical_pool") else None,
            }
        else:
            state["watchlist"].pop(aid, None)
        bus.ack(CONSUMER, end)
        n += 1
    return n


def evaluate(structure: dict, price: float, buy_zones: list[str], anchor_rule: str = "both_structures") -> dict:
    b = structure["bottom_anchor"]
    wz, wp = zone_for_price(b, structure["wick_high"], price)
    bz, bp = zone_for_price(b, structure["body_high"], price)
    in_w, in_b = wz in buy_zones, bz in buy_zones
    if anchor_rule == "wick_only":
        inside, zone, pct = in_w, wz, wp
    elif anchor_rule == "body_only":
        inside, zone, pct = in_b, bz, bp
    else:  # both_structures (default): the stricter reading
        inside, zone, pct = in_w and in_b, bz, bp
    broken = "BELOW_STRUCTURE" in (wz, bz)
    return {"zone": zone, "percent": round(pct, 3), "in_buy_zone": inside and not broken,
            "wick": {"zone": wz, "percent": round(wp, 3)}, "body": {"zone": bz, "percent": round(bp, 3)},
            "broken": broken}


def scan_asset(item: dict, astate: dict, cfg: dict) -> dict | None:
    """Scan one asset. Returns the event published (if any). Updates astate in place."""
    w = cfg["watcher"]
    chain, token = item["chain"], item["contract"]
    if not item.get("pool"):
        tp = marketdata.top_pool(chain, token, agent=AGENT)
        if not tp:
            astate.update({"status": "UNRESOLVED_POOL", "checked_at": now_iso()})
            return None
        item["pool"], item["pool_source"] = tp["pool"], "auto_resolved"
    candles = marketdata.ohlcv(chain, item["pool"], token, w["candle_timeframe"], w["candle_limit"], agent=AGENT,
                               ttl_s=w["candle_ttl_hours"] * 3600)
    st = build(candles, item["asset_id"], cfg.get("structure_rules"))
    price = marketdata.pool_price(chain, item["pool"], token, agent=AGENT)["price_usd"]
    base_payload = {"asset_id": item["asset_id"], "chain": chain, "contract": token, "symbol": item["symbol"],
                    "price": price, "observed_at": now_iso()}
    if st["status"] != "ACTIVE":
        astate.update({"status": st["status"], "reason": st.get("reason"), "checked_at": now_iso(), "price": price,
                       "in_buy_zone": False, "structure_id": None})
        return None
    ev = evaluate(st, price, cfg["buy_zone"]["zones"], cfg["buy_zone"].get("anchor_rule", "both_structures"))
    status = "BROKEN" if ev["broken"] else "ACTIVE"
    was_in = bool(astate.get("in_buy_zone")) and astate.get("structure_id") == st["structure_id"]
    prev_zone = astate.get("zone")
    payload = {**base_payload, "structure_id": st["structure_id"], "zone": ev["zone"], "previous_zone": prev_zone,
               "percent": ev["percent"], "in_buy_zone": ev["in_buy_zone"], "structure_status": status,
               "study_mode": st["study_mode"],
               "anchors": {"bottom": st["bottom_anchor"], "wick_high": st["wick_high"], "body_high": st["body_high"],
                           "wick_zone": ev["wick"], "body_zone": ev["body"], "flags": st["flags"],
                           "pool": item["pool"], "pool_source": item.get("pool_source")},
               "levels": st["levels"]["body_high"]}
    # Reaction tracker: level crossings between the previous scan and now, on BOTH anchor methods.
    prev_px = astate.get("price") if astate.get("structure_id") == st["structure_id"] else None
    if prev_px:
        for method in ("wick_high", "body_high"):
            for lvl, lvl_px in st["levels"][method].items():
                if lvl in ("0.0", "100.0"):
                    continue
                kind = "breakdown" if prev_px >= lvl_px > price else "reclaim" if prev_px < lvl_px <= price else None
                if kind:
                    observe({"type": "reaction", "asset_id": item["asset_id"], "symbol": item["symbol"], "structure_id": st["structure_id"],
                             "anchor_method": method, "target_level": float(lvl), "level_price": lvl_px, "event_type": kind,
                             "price": price, "previous_price": prev_px, "timestamp": now_iso(), "study_mode": st["study_mode"]})
    published = None
    if ev["in_buy_zone"] and not was_in:
        published = bus.publish("fib.zone.entered", AGENT, payload)
    elif was_in and not ev["in_buy_zone"]:
        published = bus.publish("fib.zone.exited", AGENT, payload)
    if published or prev_zone != ev["zone"]:
        observe({"type": "zone_transition", **payload})
    astate.update({"status": status, "structure_id": st["structure_id"], "zone": ev["zone"], "percent": ev["percent"],
                   "in_buy_zone": ev["in_buy_zone"], "price": price, "checked_at": now_iso(),
                   "bottom": st["bottom_anchor"], "wick_high": st["wick_high"], "body_high": st["body_high"],
                   "study_mode": st["study_mode"], "flags": st["flags"], "pool": item["pool"]})
    return published


def tick() -> dict:
    cfg = load_config()
    state = load_state()
    read = ingest_verdicts(state, cfg)
    summary = {"verdicts_read": read, "watching": len(state["watchlist"]), "entered": 0, "exited": 0, "errors": 0}
    for aid, item in list(state["watchlist"].items()):
        astate = state["assets"].setdefault(aid, {})
        try:
            ev = scan_asset(item, astate, cfg)
            if ev:
                summary["entered" if ev["type"] == "fib.zone.entered" else "exited"] += 1
        except (net.NetError, ValueError, KeyError) as e:
            summary["errors"] += 1
            astate.update({"status": "DATA_ERROR", "reason": str(e)[:200], "checked_at": now_iso()})
            queen_client.event(AGENT, "scan", False, message=f"{item['symbol']}: {e}")
    for aid in list(state["assets"]):
        if aid not in state["watchlist"]:
            state["assets"].pop(aid)
    save_state(state)
    queen_client.heartbeat(AGENT, "healthy" if not summary["errors"] else "degraded",
                           "" if not summary["errors"] else f"{summary['errors']} scan errors")
    return summary
