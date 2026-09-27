"""Hive command line.

  python -m hive publish --type research.verdict --file verdict.json [--source research_agent]
  python -m hive validate --type research.verdict --file verdict.json
  python -m hive tail [-n 30] [--type fib.zone.entered]
  python -m hive start                  Fib Bee watcher + Trader Bee loop + UI, one command
  python -m hive ui [--port 8790]
  python -m hive demo [--port 8791]     offline demo with FAKE tokens (own data folder)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import bus, contracts


def _load(path: str):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data if isinstance(data, list) else [data]


def start(port: int) -> int:
    """Supervise the always-on Hive processes. Each agent stays independently runnable; this is
    only a convenience so one double-click brings the Hive up (and Ctrl+C takes it all down)."""
    import subprocess
    from .paths import FIB_DIR, TRADER_DIR
    procs = [
        subprocess.Popen([sys.executable, str(FIB_DIR / "fib_agent.py"), "watch"], cwd=str(FIB_DIR)),
        subprocess.Popen([sys.executable, str(TRADER_DIR / "trader.py"), "run"], cwd=str(TRADER_DIR)),
    ]
    print("Hive started: Fib Bee watcher + Trader Bee loop. UI below.", flush=True)
    try:
        from .ui.server import serve
        serve(port)
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m hive")
    s = p.add_subparsers(dest="cmd", required=True)
    pub = s.add_parser("publish", help="validate + append event(s) from a JSON file (object or list)")
    pub.add_argument("--type", required=True)
    pub.add_argument("--file", required=True)
    pub.add_argument("--source", default="research_agent")
    val = s.add_parser("validate", help="check payload(s) against the contract without publishing")
    val.add_argument("--type", required=True)
    val.add_argument("--file", required=True)
    t = s.add_parser("tail")
    t.add_argument("-n", type=int, default=30)
    t.add_argument("--type", default=None)
    ui = s.add_parser("ui", help="serve the Hive dashboard on 127.0.0.1")
    ui.add_argument("--port", type=int, default=8790)
    st = s.add_parser("start", help="run the Fib Bee watcher + Trader Bee loop + UI together (Ctrl+C stops all)")
    st.add_argument("--port", type=int, default=8790)
    dm = s.add_parser("demo", help="offline demo with FAKE tokens in hive_data_demo/ (UI on :8791)")
    dm.add_argument("--port", type=int, default=8791)
    a = p.parse_args(argv)

    if a.cmd == "validate":
        bad = 0
        for i, payload in enumerate(_load(a.file)):
            errs = contracts.errors_for(a.type, payload)
            print(f"[{i}] {'OK' if not errs else 'INVALID'}" + ("" if not errs else ": " + "; ".join(errs)))
            bad += bool(errs)
        return 1 if bad else 0
    if a.cmd == "publish":
        payloads = _load(a.file)
        for payload in payloads:  # validate all first: publish nothing if any is bad
            contracts.validate(a.type, payload)
        for payload in payloads:
            ev = bus.publish(a.type, a.source, payload)
            print(f"published {ev['id']} {a.type} {payload.get('symbol', '')}")
        return 0
    if a.cmd == "tail":
        for ev in bus.tail(a.n, {a.type} if a.type else None):
            print(json.dumps(ev))
        return 0
    if a.cmd == "ui":
        from .ui.server import serve
        serve(a.port)
        return 0
    if a.cmd == "start":
        return start(a.port)
    if a.cmd == "demo":
        from .demo import main as demo_main
        demo_main(a.port)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
