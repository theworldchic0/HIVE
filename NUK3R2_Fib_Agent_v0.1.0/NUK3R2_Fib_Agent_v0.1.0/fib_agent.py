#!/usr/bin/env python3
"""Fib Bee CLI.

  python fib_agent.py tick                      one watch pass (verdicts -> structures -> zones -> events)
  python fib_agent.py watch [--interval 900]    loop forever (Ctrl+C to stop)
  python fib_agent.py status                    watchlist + current zone per asset
  python fib_agent.py structure --candles c.json [--price 0.01]   offline: build + classify from a file
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
    elif a.cmd == "structure":
        candles = json.loads(Path(a.candles).read_text())
        out = build(candles, "offline", cfg.get("structure_rules"))
        if a.price is not None and out["status"] == "ACTIVE":
            out["evaluation"] = watcher.evaluate(out, a.price, cfg["buy_zone"]["zones"], cfg["buy_zone"]["anchor_rule"])
        print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
