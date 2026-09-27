#!/usr/bin/env python3
"""Fib Bee CLI.

  python fib_agent.py tick                      one watch pass (verdicts -> structures -> zones -> events)
  python fib_agent.py watch [--interval 900]    loop forever (Ctrl+C to stop)
  python fib_agent.py status                    watchlist + current zone per asset
  python fib_agent.py structure --candles c.json [--price 0.01]   offline: build + classify from a file
  python fib_agent.py lab [--propose]           wick vs body: which anchor whipsaws less? (30+ crossings each before any finding)
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1]))  # Hive root (for `import hive`)
sys.path.insert(0, str(ROOT))

from src import watcher  # noqa: E402
from src.structure import build  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    s = p.add_subparsers(dest="cmd", required=True)
    s.add_parser("tick")
    w = s.add_parser("watch")
    w.add_argument("--interval", type=int, default=None)
    s.add_parser("status")
    lb = s.add_parser("lab")
    lb.add_argument("--propose", action="store_true", help="file a Queen change proposal if the sample is sufficient")
    st = s.add_parser("structure")
    st.add_argument("--candles", required=True)
    st.add_argument("--price", type=float, default=None)
    a = p.parse_args()
    cfg = watcher.load_config()
    if a.cmd == "tick":
        print(json.dumps(watcher.tick(), indent=2))
    elif a.cmd == "watch":
        every = a.interval or cfg["watcher"]["interval_seconds"]
        while True:
            try:
                print(json.dumps({"at": watcher.now_iso(), **watcher.tick()}), flush=True)
            except Exception as e:  # noqa: BLE001 — keep watching; the Queen sees the failure
                print(f"tick failed: {e}", file=sys.stderr, flush=True)
            time.sleep(every)
    elif a.cmd == "status":
        s_ = watcher.load_state()
        print(json.dumps({"watchlist": s_["watchlist"], "assets": s_["assets"]}, indent=2))
    elif a.cmd == "lab":
        from src.lab import analyze
        res = analyze(cfg)
        print(json.dumps(res, indent=2))
        if a.propose:
            if "difference_pp" not in res:
                print("No proposal: sample too small. Nothing changes.")
            else:
                import importlib.util
                from hive.paths import QUEEN_DIR
                spec = importlib.util.spec_from_file_location("q", QUEEN_DIR / "scripts" / "queen.py")
                q = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(q)
                print(json.dumps(q.propose("fib_methodology", "Fib anchor method review", "Which anchor gives cleaner NUK3R2 reactions?",
                                           res, "Consider making the better-performing anchor the primary for buy-zone checks",
                                           res["finding"], "Small or regime-specific samples can mislead", "Keep both structures stored; revert the rule",
                                           "Re-run `fib_agent.py lab` on the next 30 crossings"), indent=2))
                print("Filed as PROPOSED. The Queen never applies it; the beekeeper approves or rejects.")
    elif a.cmd == "structure":
        candles = json.loads(Path(a.candles).read_text())
        out = build(candles, "offline", cfg.get("structure_rules"))
        if a.price is not None and out["status"] == "ACTIVE":
            out["evaluation"] = watcher.evaluate(out, a.price, cfg["buy_zone"]["zones"], cfg["buy_zone"]["anchor_rule"])
        print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
