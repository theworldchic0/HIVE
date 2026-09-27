"""Bottom Blueprint Observatory — the passer-cohort performance experiment (ACCURACY_METHOD.md).

Every research PASS (any rank) is frozen into the cohort at intake: identity, research timestamp,
verdict labels (rank, confidence, archetype, stage), Blueprint clock, entry price and BTC price at
intake. Frozen means frozen: later verdicts are appended as label HISTORY, never rewrite the entry
(anti-hindsight rule). Then one observation per day per member, until the bull-cycle end (set by the
beekeeper in config when known) or the fifth-halving boundary, whichever comes first.

BTC-relative performance is measured over the SAME period (entry → observation) as percentage-point
subtraction. The Observatory reports descriptive results only while live; calibration belongs to a
separate future Blueprint Auditor.
"""
from __future__ import annotations

import json
import os
import statistics
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1]))

from hive import bus, chains, marketdata, net, queen_client  # noqa: E402
from hive.paths import sub  # noqa: E402

AGENT = "bottom_blueprint_observatory"
CONSUMER = "bottom_blueprint.cohort"
OBS_EVERY_S = 20 * 3600


def _cfg() -> dict:
    return json.loads((ROOT / "config" / "bottom_blueprint.json").read_text(encoding="utf-8"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    return (dt or _now()).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _cohort_path() -> Path:
    return sub("bottom_blueprint") / "cohort.json"


def load_cohort() -> dict:
    try:
        return json.loads(_cohort_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cohort(c: dict) -> None:
    p = _cohort_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(c, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def end_date(cfg: dict) -> date:
    ends = [date.fromisoformat(cfg["fifth_halving_projected"])]
    if cfg.get("bull_cycle_end"):
        ends.append(date.fromisoformat(cfg["bull_cycle_end"]))
    return min(ends)


def price_now(chain: str, contract: str, cg_id: str | None = None) -> tuple[float | None, str]:
    """Live USD price. DEX tokens: poison-guarded DexScreener; native coins: CoinGecko."""
    if contract.startswith("native:"):
        cid = contract.split(":", 1)[1]
        j = marketdata.coingecko(f"/simple/price?ids={cid}&vs_currencies=usd", agent=AGENT, ttl_s=120)
        return (float(j[cid]["usd"]) if j and cid in j else None), "coingecko"
    if chain in chains.CHAINS:
        c = marketdata.dexscreener_token(chain, contract, agent=AGENT)
        return c.get("price_usd"), "dexscreener"
    return None, "unsupported chain"


def intake(clock_fn) -> int:
    """Freeze new PASSers into the cohort. Returns how many joined."""
    cohort = load_cohort()
    joined = 0
    for end, ev in bus.consume(CONSUMER, {"research.verdict"}):
        v = ev["payload"]
        aid = v["asset_id"]
        label = {"at": v["researched_at"], "snapshot_id": v.get("snapshot_id"), "gate": v["gate"]["result"], "rank": v["rank"],
                 "confidence": v.get("confidence"), "archetype": v.get("archetype"), "narrative_stage": v.get("narrative_stage"), "scores": v.get("scores")}
        if aid in cohort:
            cohort[aid].setdefault("label_history", []).append(label)  # history grows; the frozen entry never changes
        elif v["gate"]["result"] == "PASS":
            try:
                px, src = price_now(v["chain"], v["contract"])
                btc, _ = marketdata.btc_spot(agent=AGENT)
            except net.NetError as e:
                px, src, btc = None, f"error: {e}", None
            cohort[aid] = {"asset_id": aid, "chain": v["chain"], "contract": v["contract"], "symbol": v["symbol"], "frozen_at": _iso(),
                           "research": label, "discovery": v.get("discovery", False), "blueprint_snapshot_id": v.get("blueprint_snapshot_id"),
                           "clock_at_research": clock_fn(datetime.fromisoformat(v["researched_at"].replace("Z", "+00:00")).date()),
                           "entry": {"price": px, "btc": btc, "at": _iso(), "source": src,
                                     "note": "price observed at intake (minutes after the verdict), never back-filled"},
                           "status": "TRACKING" if px and btc else "PRICE_PENDING", "label_history": []}
            joined += 1
        bus.ack(CONSUMER, end)
    save_cohort(cohort)
    return joined


def observe(force: bool = False) -> dict:
    cfg = _cfg()
    cohort = load_cohort()
    stop = end_date(cfg)
    out = {"observed": 0, "errors": 0, "closed": 0}
    try:
        btc, _ = marketdata.btc_spot(agent=AGENT)
    except net.NetError as e:
        queen_client.event(AGENT, "observe", False, message=f"BTC price unavailable: {e}")
        return {**out, "errors": 1, "error": str(e)}
    t = _now()
    with open(sub("bottom_blueprint") / "observations.jsonl", "a", encoding="utf-8") as f:
        for aid, m in cohort.items():
            if m["status"] == "CLOSED":
                continue
            if t.date() > stop:
                m["status"] = "CLOSED"
                m["closed_reason"] = f"reached the tracking boundary {stop} (bull-cycle end or fifth halving)"
                out["closed"] += 1
                continue
            last = m.get("last_observed_at")
            if not force and last and (t - datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds() < OBS_EVERY_S:
                continue
            try:
                px, src = price_now(m["chain"], m["contract"])
            except net.NetError as e:
                out["errors"] += 1
                m["last_error"] = str(e)[:160]
                continue
            if not px:
                out["errors"] += 1
                continue
            if m["status"] == "PRICE_PENDING":
                m["entry"] = {"price": px, "btc": btc, "at": _iso(t), "source": src, "note": "first price available AFTER intake — later than the research timestamp"}
                m["status"] = "TRACKING"
            e = m["entry"]
            tr = (px / e["price"] - 1) * 100
            br = (btc / e["btc"] - 1) * 100
            row = {"asset_id": aid, "at": _iso(t), "price": px, "btc": btc, "token_return_pct": round(tr, 2), "btc_return_pct": round(br, 2),
                   "excess_pp": round(tr - br, 2), "days_since_entry": (t - datetime.fromisoformat(e["at"].replace("Z", "+00:00"))).days}
            f.write(json.dumps(row) + "\n")
            m["latest"] = row
            m["last_observed_at"] = row["at"]
            out["observed"] += 1
    save_cohort(cohort)
    return out


def performance(window_start: str | None = None) -> dict:
    """Descriptive only — no calibration claims while the experiment is live."""
    cfg = _cfg()
    ws = window_start or cfg["cycle"]["bottom_window_start"]
    cohort = load_cohort()
    members = list(cohort.values())
    live = [m for m in members if m.get("latest")]
    since_window = [m for m in members if (m["research"]["at"] or "")[:10] >= ws]

    def stats(ms):
        ex = [m["latest"]["excess_pp"] for m in ms if m.get("latest")]
        tr = [m["latest"]["token_return_pct"] for m in ms if m.get("latest")]
        if not ex:
            return {"n": len(ms), "observed": 0}
        return {"n": len(ms), "observed": len(ex), "median_token_return_pct": round(statistics.median(tr), 2),
                "median_excess_pp": round(statistics.median(ex), 2), "pct_beating_btc": round(100 * sum(1 for x in ex if x > 0) / len(ex), 1)}
    by_rank, by_arch = {}, {}
    for m in live:
        by_rank.setdefault(m["research"]["rank"], []).append(m)
        for a in (m["research"].get("archetype") or "unlabeled").split(", "):
            by_arch.setdefault(a, []).append(m)
    ranked = sorted(live, key=lambda m: -m["latest"]["excess_pp"])
    brief = lambda m: {"symbol": m["symbol"], "chain": m["chain"], "excess_pp": m["latest"]["excess_pp"], "token_return_pct": m["latest"]["token_return_pct"],  # noqa: E731
                       "days": m["latest"]["days_since_entry"], "rank_at_research": m["research"]["rank"]}
    return {"as_of": _iso(), "tracking_until": end_date(cfg).isoformat(), "window_start": ws, "all": stats(members),
            "since_window_start": stats(since_window), "by_rank": {k: stats(v) for k, v in by_rank.items()},
            "by_archetype": {k: stats(v) for k, v in by_arch.items()}, "leaders": [brief(m) for m in ranked[:5]],
            "laggards": [brief(m) for m in ranked[-5:][::-1]], "pending_price": sum(1 for m in members if m["status"] == "PRICE_PENDING"),
            "note": "Descriptive, live out-of-sample. Entries are frozen at intake; no member is ever edited or removed for performing badly."}


def track(clock_fn, force: bool = False) -> dict:
    j = intake(clock_fn)
    o = observe(force)
    perf = performance()
    p = sub("bottom_blueprint") / "performance.json"
    p.write_text(json.dumps(perf, indent=1), encoding="utf-8")
    queen_client.heartbeat(AGENT, "healthy" if not o.get("errors") else "degraded", f"{o.get('errors', 0)} observation errors" if o.get("errors") else "")
    return {"joined": j, **o, "cohort": perf["all"]}
