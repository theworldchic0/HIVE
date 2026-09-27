"""Hive command line.

  python -m hive publish --type research.verdict --file verdict.json [--source research_agent]
  python -m hive validate --type research.verdict --file verdict.json
  python -m hive tail [-n 30] [--type fib.zone.entered]
  python -m hive setup [--missing|--check]   the API-key walkthrough (runs itself on first start)
  python -m hive doctor [--offline]          health check for the whole Hive
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


def start(port: int, skip_setup: bool = False, no_browser: bool = False) -> int:
    """Supervise the always-on Hive processes. Each agent stays independently runnable; this is
    only a convenience so one double-click brings the Hive up (and Ctrl+C takes it all down).
    First run: while any API key is still undecided, the key walkthrough runs before anything starts."""
    import subprocess
    from . import keys
    if not skip_setup and keys.undecided():
        if sys.stdin.isatty():
            from .setup_wizard import run as setup_run
            print("First start: let's add your API keys (once). Ctrl+C to do it later.")
            setup_run(only_missing=True)
        else:
            print("Some API keys are not set yet — run `python -m hive setup` in a terminal.", flush=True)
    from .paths import BLUEPRINT_DIR, FIB_DIR, META_DIR, SCOUT_DIR, TRADER_DIR
    procs = [
        subprocess.Popen([sys.executable, str(META_DIR / "metabee.py"), "run"], cwd=str(META_DIR)),
        subprocess.Popen([sys.executable, str(BLUEPRINT_DIR / "bottom_blueprint.py"), "watch", "--hours", "6"], cwd=str(BLUEPRINT_DIR)),
        subprocess.Popen([sys.executable, str(SCOUT_DIR / "scout.py"), "watch"], cwd=str(SCOUT_DIR)),
        subprocess.Popen([sys.executable, str(FIB_DIR / "fib_agent.py"), "watch"], cwd=str(FIB_DIR)),
        subprocess.Popen([sys.executable, str(TRADER_DIR / "trader.py"), "run"], cwd=str(TRADER_DIR)),
    ]
    print("Hive started: Meta Bee (nonstop) · Discovery Scout (6h) · Fib Bee (15m) · Blueprint cohort (6h) · Trader Bee (60s). UI below.", flush=True)
    try:
        import threading
        import webbrowser
        from .ui.server import serve
        if not no_browser:
            threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
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
    st.add_argument("--skip-setup", action="store_true")
    st.add_argument("--no-browser", action="store_true")
    su = s.add_parser("setup", help="API-key walkthrough: what each key does, where to get it, paste (hidden), live test, save")
    su.add_argument("--missing", action="store_true", help="only keys not yet set or skipped")
    su.add_argument("--check", action="store_true", help="status only, no questions")
    dr = s.add_parser("doctor", help="read-only health check (keys tested live, RPCs, executor, agents)")
    dr.add_argument("--offline", action="store_true")
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
        return start(a.port, a.skip_setup, a.no_browser)
    if a.cmd == "setup":
        from . import setup_wizard
        return setup_wizard.check() if a.check else setup_wizard.run(only_missing=a.missing)
    if a.cmd == "doctor":
        from .doctor import run as doctor_run
        return doctor_run(a.offline)
    if a.cmd == "demo":
        from .demo import main as demo_main
        demo_main(a.port)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
