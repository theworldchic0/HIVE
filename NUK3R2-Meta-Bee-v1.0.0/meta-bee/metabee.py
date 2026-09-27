#!/usr/bin/env python3
"""NUK3R2 Meta Bee — the nonstop meta hunter (Hive id: narrative_agent).

  python metabee.py run            forever: every worker on its own cadence (Ctrl+C to stop)
  python metabee.py once           run every enabled worker once + rebuild the rollups
  python metabee.py status         the current meta board (daily / weekly / monthly)
  python metabee.py emerging       repeated names that match NO meta yet (where new metas are born)

Sub-agents (workers), one per source, each on its own schedule and each failing independently:
  cg_categories     CoinGecko categories: market-cap change + volume per category        (capital)
  cg_trending       CoinGecko trending search: coins + categories people look up        (attention)
  gt_trending       GeckoTerminal trending pools on Base / Solana / ETH / Robinhood / BSC (on-chain attention)
  ds_boosts         DexScreener boosts (PAID attention, discounted) + new token profiles
  llama_categories  DefiLlama TVL change by protocol category                            (capital)
  reddit            optional, off by default (keyless access is unreliable)

Every observation is stored (SQLite). Hourly attention scores roll up to daily / weekly / monthly, and
each meta gets a machine-measured curve label. That label is EVIDENCE for the Research Bee's narrative
curve judgment, never a score by itself and never a trade trigger.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1]))

from hive import bus, marketdata, net, queen_client  # noqa: E402
from hive.paths import sub  # noqa: E402

AGENT = "narrative_agent"
WORD = re.compile(r"[a-z0-9]+")
STOP = {"the", "a", "of", "and", "on", "to", "in", "for", "coin", "token", "finance", "protocol", "network", "usd", "weth", "wsol",
        "sol", "eth", "usdc", "usdt", "usdg", "bnb", "wbnb", "cbbtc", "is", "by", "with", "your", "first", "new", "official", "x", "it", "at", "be"}


def load_config() -> dict:
    return json.loads((ROOT / "config" / "meta.json").read_text(encoding="utf-8"))


def now() -> float:
    return time.time()


def iso(t: float | None = None) -> str:
    return datetime.fromtimestamp(t or now(), timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ------------------------------------------------------------------ storage
SCHEMA = """
CREATE TABLE IF NOT EXISTS obs(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, source TEXT, meta TEXT, metric TEXT, value REAL, detail TEXT);
CREATE INDEX IF NOT EXISTS ix_obs ON obs(meta, ts);
CREATE TABLE IF NOT EXISTS unclassified(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, source TEXT, name TEXT, symbol TEXT, chain TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS runs(worker TEXT PRIMARY KEY, last_ok REAL, last_try REAL, last_error TEXT, runs INTEGER DEFAULT 0, failures INTEGER DEFAULT 0);
"""


def db() -> sqlite3.Connection:
    c = sqlite3.connect(sub("meta") / "meta.db", timeout=30, isolation_level=None)
    c.executescript(SCHEMA)
    return c


# ------------------------------------------------------------------ classification
class Taxonomy:
    def __init__(self, cfg: dict):
        self.metas = cfg["metas"]
        self.kw = [(m["name"], {k.lower() for k in m["keywords"]}) for m in self.metas]
        self.cg = [(m["name"], [c.lower() for c in m["cg_categories"]]) for m in self.metas]
        self.llama = [(m["name"], {c.lower() for c in m["llama_categories"]}) for m in self.metas]

    def by_text(self, *texts: str) -> set[str]:
        words = set()
        for t in texts:
            words |= set(WORD.findall((t or "").lower()))
        return {name for name, kws in self.kw if words & kws}

    def by_cg_category(self, cat: str) -> set[str]:
        c = (cat or "").lower()
        return {name for name, cats in self.cg if any(x in c for x in cats)}

    def by_llama_category(self, cat: str) -> set[str]:
        return {name for name, cats in self.llama if (cat or "").lower() in cats}


def _obs(c, source: str, meta: str, metric: str, value: float, detail: dict | None = None, ts: float | None = None):
    c.execute("INSERT INTO obs(ts,source,meta,metric,value,detail) VALUES(?,?,?,?,?,?)", (ts or now(), source, meta, metric, value, json.dumps(detail or {})[:1000]))


def _unclassified(c, source, name, symbol, chain="", detail=None):
    c.execute("INSERT INTO unclassified(ts,source,name,symbol,chain,detail) VALUES(?,?,?,?,?,?)", (now(), source, name or "", symbol or "", chain or "", json.dumps(detail or {})[:500]))


# ------------------------------------------------------------------ workers (sub-agents)
def w_cg_categories(c, tax: Taxonomy, cfg: dict) -> int:
    rows = marketdata.coingecko("/coins/categories", agent=AGENT, ttl_s=1800) or []
    agg: dict[str, list] = defaultdict(list)
    for r in rows:
        for m in tax.by_cg_category(r.get("name")):
            agg[m].append(r)
    for m, rs in agg.items():
        cap = sum(float(r.get("market_cap") or 0) for r in rs)
        chg = sum(float(r.get("market_cap") or 0) * float(r.get("market_cap_change_24h") or 0) for r in rs) / cap if cap else 0
        _obs(c, "cg_categories", m, "mcap_change_24h", chg, {"categories": [r.get("name") for r in rs][:6], "market_cap": cap,
                                                            "volume_24h": sum(float(r.get("volume_24h") or 0) for r in rs)})
    return len(agg)


def w_cg_trending(c, tax: Taxonomy, cfg: dict) -> int:
    j = marketdata.coingecko("/search/trending", agent=AGENT, ttl_s=600) or {}
    n = 0
    for it in j.get("coins") or []:
        x = it.get("item") or {}
        cats = []
        metas = tax.by_text(x.get("name"), x.get("symbol"), x.get("id"))
        for cat in ((x.get("data") or {}).get("categories") or []) if isinstance((x.get("data") or {}).get("categories"), list) else []:
            metas |= tax.by_cg_category(cat)
            cats.append(cat)
        if not metas:
            _unclassified(c, "cg_trending", x.get("name"), x.get("symbol"))
        for m in metas:
            _obs(c, "cg_trending", m, "trending_hit", 1, {"name": x.get("name"), "symbol": x.get("symbol"), "rank": x.get("market_cap_rank")})
            n += 1
    for cat in j.get("categories") or []:
        for m in tax.by_cg_category(cat.get("name")):
            _obs(c, "cg_trending", m, "trending_hit", 1, {"category": cat.get("name")})
            n += 1
    return n


def w_gt_trending(c, tax: Taxonomy, cfg: dict) -> int:
    n = 0
    errors = []
    for net_id in cfg["workers"]["gt_trending"]["networks"]:
        try:
            j = marketdata._onchain(f"/networks/{net_id}/trending_pools?page=1", AGENT, "trending_pools", ttl_s=600) or {}
        except net.NetError as e:
            errors.append(f"{net_id}: {e}")
            continue
        for d in j.get("data") or []:
            a = d.get("attributes") or {}
            name = str(a.get("name") or "")
            token = name.split("/")[0].strip()
            metas = tax.by_text(token)
            if not metas:
                _unclassified(c, "gt_trending", token, token, net_id, {"pool": a.get("address"), "vol24": (a.get("volume_usd") or {}).get("h24")})
            for m in metas:
                _obs(c, "gt_trending", m, "trending_hit", 1, {"token": token, "network": net_id, "vol24": (a.get("volume_usd") or {}).get("h24")})
                n += 1
    if errors and not n:
        raise net.NetError("; ".join(errors)[:300])
    return n


def w_ds_boosts(c, tax: Taxonomy, cfg: dict) -> int:
    n = 0
    boosts = net.fetch_json("https://api.dexscreener.com/token-boosts/top/v1", agent=AGENT, operation="boosts", ttl_s=300) or []
    for b in boosts if isinstance(boosts, list) else []:
        metas = tax.by_text(b.get("description"), b.get("url"))
        if not metas:
            _unclassified(c, "ds_boosts", (b.get("url") or "").rsplit("/", 1)[-1], "", b.get("chainId"), {"paid": True})
        for m in metas:
            _obs(c, "ds_boosts", m, "boost_hit", 1, {"chain": b.get("chainId"), "token": b.get("tokenAddress"), "paid": True, "amount": b.get("totalAmount")})
            n += 1
    profiles = net.fetch_json("https://api.dexscreener.com/token-profiles/latest/v1", agent=AGENT, operation="profiles", ttl_s=300) or []
    for p in profiles if isinstance(profiles, list) else []:
        metas = tax.by_text(p.get("description"))
        if not metas:
            _unclassified(c, "ds_profiles", (p.get("description") or "")[:40], "", p.get("chainId"))
        for m in metas:
            _obs(c, "ds_profiles", m, "profile_hit", 1, {"chain": p.get("chainId"), "token": p.get("tokenAddress")})
            n += 1
    return n


def w_llama_categories(c, tax: Taxonomy, cfg: dict) -> int:
    protos = marketdata.defillama("/protocols", agent=AGENT) or []
    agg: dict[str, list] = defaultdict(list)
    for p in protos:
        for m in tax.by_llama_category(p.get("category")):
            if p.get("tvl") and p.get("change_7d") is not None:
                agg[m].append(p)
    for m, ps in agg.items():
        tvl = sum(float(p["tvl"]) for p in ps)
        chg = sum(float(p["tvl"]) * float(p["change_7d"]) for p in ps) / tvl if tvl else 0
        top = sorted(ps, key=lambda p: -float(p["tvl"]))[:5]
        _obs(c, "llama_categories", m, "tvl_change_7d", chg, {"tvl": tvl, "protocols": len(ps), "top": [p.get("name") for p in top]})
    return len(agg)


def w_reddit(c, tax: Taxonomy, cfg: dict) -> int:
    n = 0
    for s in cfg["workers"]["reddit"]["subs"]:
        j = net.fetch_json(f"https://www.reddit.com/r/{s}/hot.json?limit=50", agent=AGENT, operation="reddit", ttl_s=900)
        for ch in ((j or {}).get("data") or {}).get("children") or []:
            t = (ch.get("data") or {}).get("title") or ""
            for m in tax.by_text(t):
                _obs(c, "reddit", m, "reddit_hit", 1, {"sub": s, "title": t[:120]})
                n += 1
    return n


WORKERS = {"cg_categories": w_cg_categories, "cg_trending": w_cg_trending, "gt_trending": w_gt_trending, "ds_boosts": w_ds_boosts,
           "llama_categories": w_llama_categories, "reddit": w_reddit}


def run_worker(c, name: str, tax: Taxonomy, cfg: dict) -> dict:
    t = now()
    try:
        n = WORKERS[name](c, tax, cfg)
        c.execute("INSERT INTO runs(worker,last_ok,last_try,last_error,runs) VALUES(?,?,?,NULL,1) ON CONFLICT(worker) DO UPDATE SET last_ok=?, last_try=?, last_error=NULL, runs=runs+1",
                  (name, t, t, t, t))
        return {"worker": name, "ok": True, "observations": n}
    except Exception as e:  # noqa: BLE001 — one broken source never stops the hunt; it is reported
        msg = f"{type(e).__name__}: {str(e)[:200]}"
        c.execute("INSERT INTO runs(worker,last_try,last_error,runs,failures) VALUES(?,?,?,1,1) ON CONFLICT(worker) DO UPDATE SET last_try=?, last_error=?, runs=runs+1, failures=failures+1",
                  (name, t, msg, t, msg))
        queen_client.event(AGENT, "worker", False, message=f"{name}: {msg}")
        return {"worker": name, "ok": False, "error": msg}


# ------------------------------------------------------------------ rollups + curves
def hourly_scores(c, cfg: dict, since: float) -> dict[str, dict[int, float]]:
    """meta -> {hour_bucket: attention+capital score}. Capital metrics use the latest value in each hour."""
    w = cfg["weights"]
    hit_w = {"trending_hit": None, "boost_hit": w["ds_boost_hit"], "profile_hit": w["ds_profile_hit"], "reddit_hit": w["reddit_hit"]}
    out: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    last_cap: dict[tuple, float] = {}
    for ts, source, meta, metric, value in c.execute("SELECT ts,source,meta,metric,value FROM obs WHERE ts>=? ORDER BY ts", (since,)):
        h = int(ts // 3600)
        if metric == "trending_hit":
            out[meta][h] += value * (w["cg_trending_hit"] if source == "cg_trending" else w["gt_trending_hit"])
        elif metric in hit_w:
            out[meta][h] += value * hit_w[metric]
        elif metric == "mcap_change_24h":
            last_cap[(meta, h, "cg")] = max(-w["cg_mcap_change_clip"], min(w["cg_mcap_change_clip"], value * w["cg_mcap_change_24h_per_pt"]))
        elif metric == "tvl_change_7d":
            last_cap[(meta, h, "llama")] = max(-w["llama_tvl_change_clip"], min(w["llama_tvl_change_clip"], value * w["llama_tvl_change_7d_per_pt"]))
    for (meta, h, _), v in last_cap.items():
        out[meta][h] += v
    return out


def _avg(series: dict[int, float], lo: int, hi: int) -> float | None:
    hours = hi - lo
    if hours <= 0:
        return None
    return sum(v for h, v in series.items() if lo <= h < hi) / hours


def curve_label(cur: float | None, prev: float | None, older: float | None, cfg: dict) -> str:
    """Machine curve from three consecutive windows (older → prev → cur). Evidence, not judgment."""
    if cur is None or prev is None:
        return "insufficient_data"
    r, s = cfg["curve"]["rise_pct"] / 100, cfg["curve"]["strong_pct"] / 100
    base = max(abs(prev), 1e-9)
    d = (cur - prev) / base
    if prev <= 0.05 and cur > 0.25:
        return "revival" if older is not None and older > cur else "early_rising"
    if older is not None and prev > older * (1 + r) and cur < prev * (1 - r):
        return "peaking"
    if d > s:
        return "accelerating" if older is not None and prev > older * (1 + r) else "rising"
    if d > r:
        return "early_rising" if older is not None and prev <= older * (1 + r) else "rising"
    if d < -s:
        return "declining"
    if d < -r:
        return "fading"
    return "flat"


def rebuild(c, cfg: dict, publish: bool = True) -> dict:
    t = now()
    h_now = int(t // 3600) + 1
    series = hourly_scores(c, cfg, t - 70 * 86400)
    first = c.execute("SELECT MIN(ts) FROM obs").fetchone()[0] or t
    history_h = (t - first) / 3600
    cv = cfg["curve"]
    windows = {"daily": 24, "weekly": 24 * 7, "monthly": 24 * 30}
    # a curve needs two FULL windows (current vs previous); fewer = insufficient_data, never a guess
    enough = {"daily": history_h >= cv["min_hours_daily"], "weekly": history_h >= cv["min_days_weekly"] * 24, "monthly": history_h >= cv["min_days_monthly"] * 24}
    prev_state = {}
    try:
        prev_state = {m["name"]: m for m in json.loads((sub("meta") / "state.json").read_text()).get("metas", [])}
    except Exception:
        pass
    metas = []
    for m in cfg["metas"]:
        s = series.get(m["name"], {})
        row = {"name": m["name"], "cg_categories_lc": [x.lower() for x in m["cg_categories"]]}
        for wname, hrs in windows.items():
            cur = _avg(s, h_now - hrs, h_now)
            prev = _avg(s, h_now - 2 * hrs, h_now - hrs) if history_h >= 2 * hrs else None
            older = _avg(s, h_now - 3 * hrs, h_now - 2 * hrs) if history_h >= 3 * hrs else None
            row[f"score_{wname}"] = round(cur or 0, 3)
            row[f"curve_{wname}"] = curve_label(cur, prev, older, cfg) if enough[wname] else "insufficient_data"
        ev = c.execute("SELECT source, metric, value, detail FROM obs WHERE meta=? AND ts>=? ORDER BY ts DESC LIMIT 400", (m["name"], t - 86400)).fetchall()
        toks = Counter()
        for _, metric, _, detail in ev:
            d = json.loads(detail or "{}")
            label = d.get("token") or d.get("name") or d.get("symbol")
            if label and metric in ("trending_hit", "boost_hit", "profile_hit"):
                toks[str(label)[:40]] += 1
        row["top_tokens_24h"] = [k for k, _ in toks.most_common(6)]
        row["sources_24h"] = dict(Counter(x[0] for x in ev))
        cap = next((json.loads(x[3]) for x in ev if x[1] == "mcap_change_24h"), None)
        tvl = next((json.loads(x[3]) for x in ev if x[1] == "tvl_change_7d"), None)
        row["capital"] = {"cg_market_cap": (cap or {}).get("market_cap"), "cg_volume_24h": (cap or {}).get("volume_24h"),
                          "cg_mcap_change_24h": next((x[2] for x in ev if x[1] == "mcap_change_24h"), None),
                          "llama_tvl": (tvl or {}).get("tvl"), "llama_tvl_change_7d": next((x[2] for x in ev if x[1] == "tvl_change_7d"), None)}
        metas.append(row)
        old = prev_state.get(m["name"], {})
        if publish and old and old.get("curve_daily") != row["curve_daily"] and row["curve_daily"] in ("early_rising", "rising", "accelerating", "revival"):
            bus.publish("meta.shift", AGENT, {"meta": m["name"], "from": old.get("curve_daily"), "to": row["curve_daily"], "score_daily": row["score_daily"],
                                              "top_tokens_24h": row["top_tokens_24h"]})
    top = {w: [x["name"] for x in sorted(metas, key=lambda x: -x[f"score_{w}"]) if x[f"score_{w}"] > 0][:10] for w in windows}
    since = t - 86400
    words = Counter()
    for name, symbol in c.execute("SELECT name, symbol FROM unclassified WHERE ts>=?", (since,)):
        for wd in set(WORD.findall(f"{name} {symbol}".lower())):
            if len(wd) >= 3 and wd not in STOP and not wd.isdigit():
                words[wd] += 1
    workers = {r[0]: {"last_ok": iso(r[1]) if r[1] else None, "last_try": iso(r[2]) if r[2] else None, "last_error": r[3], "runs": r[4], "failures": r[5]}
               for r in c.execute("SELECT worker,last_ok,last_try,last_error,runs,failures FROM runs")}
    state = {"updated_at": iso(t), "history_hours": round(history_h, 1), "metas": sorted(metas, key=lambda x: -x["score_daily"]), "top": top,
             "emerging_unclassified": [{"word": wd, "hits_24h": n} for wd, n in words.most_common(20) if n >= 2], "workers": workers,
             "note": "Machine-measured attention + capital. Evidence for the Research Bee's narrative-curve judgment; never a score by itself, never a trade trigger."}
    p = sub("meta") / "state.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    os.replace(tmp, p)
    return state


def once(cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    tax = Taxonomy(cfg)
    c = db()
    res = [run_worker(c, n, tax, cfg) for n, w in cfg["workers"].items() if w.get("enabled")]
    st = rebuild(c, cfg)
    queen_client.heartbeat(AGENT, "healthy" if all(r["ok"] for r in res) else "degraded",
                           "; ".join(f"{r['worker']}: {r['error']}" for r in res if not r["ok"])[:300])
    return {"workers": res, "top_daily": st["top"]["daily"][:5]}


def run_forever():
    """The hunt never stops: each worker keeps its own clock; rollups rebuild every 5 minutes."""
    last: dict[str, float] = {}
    last_rebuild = 0.0
    c = db()
    while True:
        cfg = load_config()  # re-read: taxonomy edits apply without a restart
        tax = Taxonomy(cfg)
        ran = []
        for name, w in cfg["workers"].items():
            if w.get("enabled") and now() - last.get(name, 0) >= w["every_minutes"] * 60:
                ran.append(run_worker(c, name, tax, cfg))
                last[name] = now()
        if ran or now() - last_rebuild > 300:
            rebuild(c, cfg)
            last_rebuild = now()
            bad = [r for r in ran if not r["ok"]]
            queen_client.heartbeat(AGENT, "degraded" if bad else "healthy", "; ".join(f"{r['worker']}: {r['error']}" for r in bad)[:300])
            if ran:
                print(json.dumps({"at": iso(), "ran": ran}), flush=True)
        cutoff = now() - cfg["retention_days"] * 86400
        c.execute("DELETE FROM obs WHERE ts<?", (cutoff,))
        c.execute("DELETE FROM unclassified WHERE ts<?", (cutoff,))
        time.sleep(20)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["run", "once", "status", "emerging"])
    a = p.parse_args()
    if a.cmd == "run":
        run_forever()
    elif a.cmd == "once":
        print(json.dumps(once(), indent=2))
    else:
        try:
            st = json.loads((sub("meta") / "state.json").read_text())
        except FileNotFoundError:
            print("no meta state yet — run `python metabee.py once`")
            return 1
        if a.cmd == "emerging":
            print(json.dumps(st["emerging_unclassified"], indent=2))
        else:
            print(f"META BOARD  {st['updated_at']}  (history {st['history_hours']}h)")
            print(f"{'meta':<34}{'daily':>8} {'curve':<18}{'weekly':>8} {'curve':<18}{'monthly':>8} {'curve':<18}")
            for m in st["metas"][:20]:
                print(f"{m['name']:<34}{m['score_daily']:>8} {m['curve_daily']:<18}{m['score_weekly']:>8} {m['curve_weekly']:<18}{m['score_monthly']:>8} {m['curve_monthly']:<18}")
            for w, r in st["workers"].items():
                print(f"  worker {w:<18} last ok {r['last_ok']}  failures {r['failures']}" + (f"  ERROR {r['last_error']}" if r["last_error"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
