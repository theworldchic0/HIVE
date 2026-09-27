"""Fib hypothesis lab — which anchor method produces cleaner level reactions?

Reads the immutable reaction log (observations.jsonl). For each (asset, structure, method, level) the
crossings are put in time order. A crossing followed by the OPPOSITE crossing within
`whipsaw_hours` is a whipsaw (the level didn't hold). A lower whipsaw rate = cleaner reactions.

Nothing changes automatically. Below `minimum_observations_for_comparison` per method the lab says
"insufficient sample". Above it, `--propose` files a change proposal with the Queen, which waits for
the beekeeper's approval (Queen operating model §2D).
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime

from hive.paths import sub


def _t(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def analyze(cfg: dict, whipsaw_hours: float = 24.0) -> dict:
    rows = []
    try:
        for line in (sub("fib_agent") / "observations.jsonl").read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r.get("type") == "reaction":
                rows.append(r)
    except FileNotFoundError:
        pass
    groups = defaultdict(list)
    for r in rows:
        groups[(r["asset_id"], r["structure_id"], r["anchor_method"], r["target_level"])].append(r)
    per = defaultdict(lambda: {"events": 0, "whipsaws": 0, "by_level": defaultdict(lambda: {"events": 0, "whipsaws": 0}), "by_mode": defaultdict(lambda: {"events": 0, "whipsaws": 0})})
    for (aid, sid, method, lvl), evs in groups.items():
        evs.sort(key=lambda r: r["timestamp"])
        for i, e in enumerate(evs):
            nxt = evs[i + 1] if i + 1 < len(evs) else None
            whip = bool(nxt and nxt["event_type"] != e["event_type"] and _t(nxt["timestamp"]) - _t(e["timestamp"]) <= whipsaw_hours * 3600)
            for bucket in (per[method], per[method]["by_level"][str(lvl)], per[method]["by_mode"][e.get("study_mode", "?")]):
                bucket["events"] += 1
                bucket["whipsaws"] += int(whip)
    need = cfg["learning"]["minimum_observations_for_comparison"]
    out = {"minimum_observations": need, "methods": {}}
    for m, d in per.items():
        out["methods"][m] = {"events": d["events"], "whipsaw_rate_pct": round(100 * d["whipsaws"] / d["events"], 1) if d["events"] else None,
                             "sample": "sufficient" if d["events"] >= need else "insufficient",
                             "by_level": {k: {**v, "whipsaw_rate_pct": round(100 * v["whipsaws"] / v["events"], 1)} for k, v in d["by_level"].items()},
                             "by_mode": {k: {**v, "whipsaw_rate_pct": round(100 * v["whipsaws"] / v["events"], 1)} for k, v in d["by_mode"].items()}}
    ms = out["methods"]
    if all(ms.get(k, {}).get("sample") == "sufficient" for k in ("wick_high", "body_high")):
        w, b = ms["wick_high"]["whipsaw_rate_pct"], ms["body_high"]["whipsaw_rate_pct"]
        better = "body_high" if b < w else "wick_high"
        out["finding"] = f"{better} anchors whipsawed less ({min(w, b)}% vs {max(w, b)}%) over {ms['wick_high']['events']}/{ms['body_high']['events']} crossings"
        out["difference_pp"] = round(abs(w - b), 1)
    else:
        out["finding"] = f"insufficient sample — each method needs {need}+ crossings before any comparison (no conclusions yet)"
    return out
