"""`python -m hive doctor [--offline]` — one read-only health check for the whole Hive.

Never prints a key, never trades. Exit 0 = nothing critical wrong. Every ✗ comes with the fix.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import os
import sys

if os.name == "nt":
    os.system("")  # turns on ANSI colour support in the classic Windows console

from . import keys
from .paths import BLUEPRINT_DIR, FIB_DIR, QUEEN_DIR, TRADER_DIR, data_dir

G, R, Y, D, B, X = ("\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m") if sys.stdout.isatty() else ("",) * 6


def run(offline: bool = False) -> int:
    rows: list[tuple[str, str, str, str]] = []  # (level ok|warn|bad, title, detail, fix)

    def add(level, title, detail, fix=""):
        rows.append((level, title, detail, fix))

    # runtime
    v = sys.version_info
    add("ok" if v >= (3, 10) else "bad", "Python", f"{v.major}.{v.minor}.{v.micro}", "Install Python 3.10+ from https://python.org")
    node = shutil.which("node")
    if node:
        out = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip()
        major = int(out.lstrip("v").split(".")[0] or 0)
        add("ok" if major >= 20 else "bad", "Node.js", out, "Install Node 20+ LTS from https://nodejs.org")
    else:
        add("bad", "Node.js", "not found", "Install Node 20+ LTS from https://nodejs.org (the Trader Bee executor needs it)")
    ex = TRADER_DIR / "executor"
    add("ok" if (ex / "node_modules").exists() else "bad", "Trader Bee executor packages",
        "installed" if (ex / "node_modules").exists() else "missing", f"cd \"{ex}\" && npm install && npm run selftest")

    # keys
    for s in keys.SPECS:
        cur = keys.current(s)
        dec = keys.record().get(s.name, {}).get("status")
        if not cur:
            lvl = "bad" if s.level == "required" and dec != "SKIPPED" else "warn" if s.level != "optional" else "opt"
            add(lvl, s.title, f"not set{' (consciously SKIPPED)' if dec == 'SKIPPED' else ''} — {s.if_skipped}", "python -m hive setup")
            continue
        if offline or not s.verify:
            add("ok", s.title, f"set {keys.mask(cur)}" + ("" if s.verify else f" — {s.no_verify_reason}"))
            continue
        ok, why, _ = keys.verify(s, cur)
        add("ok" if ok else "bad" if ok is False else "warn", s.title, f"{keys.mask(cur)} — {why}",
            "" if ok else "python -m hive setup   (choose NEW for this key)")

    # chains (the executor's RPCs)
    if not offline:
        from .chains import CHAINS
        for name, c in CHAINS.items():
            if not c.get("tradable"):
                continue
            env = "BASE_RPC_URL" if name == "base" else "ROBINHOOD_RPC_URL"
            url = keys.current(keys.BY_NAME[env]) or c["rpc"]
            try:
                cid = keys._rpc(url, "eth_chainId")
                add("ok" if cid == c["chain_id"] else "bad", f"{name} RPC", f"chain {cid} @ {keys.mask(url)}", f"set {env} to a {name} mainnet RPC")
            except Exception as e:  # noqa: BLE001
                add("bad", f"{name} RPC", f"unreachable: {str(e)[:80]}", f"check internet, or set {env} (python -m hive setup)")

    # trader bee
    sys.path.insert(0, str(TRADER_DIR))
    try:
        from trader_bee import config as tcfg
        cfg = tcfg.load()
        mode = tcfg.effective_mode(cfg)
        add("ok", "Trader Bee mode", f"{mode.upper()} (config: {cfg['mode']}, armed: {'yes' if tcfg.armed() is not None else 'no'})")
        add("ok" if tcfg.KEY_FILE.exists() else "warn", "Trader Bee wallet", "exists" if tcfg.KEY_FILE.exists() else "not created yet",
            "cd NUK3R2-Trader-Bee-Agent-v1.0.0/trader-bee && python trader.py wallet-new")
    except Exception as e:  # noqa: BLE001
        add("bad", "Trader Bee config", str(e)[:120], "check config/trader_bee.json is valid JSON")

    # agents + data
    for title, p in (("Queen Bee", QUEEN_DIR / "config" / "queen.json"), ("Fib Bee config", FIB_DIR / "config" / "defaults.json"),
                     ("Bottom Blueprint config", BLUEPRINT_DIR / "config" / "bottom_blueprint.json")):
        try:
            json.loads(p.read_text(encoding="utf-8"))
            add("ok", title, "config valid")
        except Exception as e:  # noqa: BLE001
            add("bad", title, f"config unreadable: {e}", f"restore {p.name} from git")
    try:
        t = data_dir() / ".write-test"
        t.write_text("ok")
        t.unlink()
        add("ok", "Hive data folder", str(data_dir()))
    except OSError as e:
        add("bad", "Hive data folder", f"not writable: {e}", "check folder permissions / disk space")

    icon = {"ok": f"{G}✓{X}", "warn": f"{Y}!{X}", "bad": f"{R}✗{X}", "opt": f"{D}–{X}"}
    print(f"{B}🐝 HIVE DOCTOR{X}{' (offline: no live calls)' if offline else ''}")
    for lvl, title, detail, fix in rows:
        print(f" {icon[lvl]} {title:<40} {detail}")
        if lvl in ("warn", "bad") and fix:
            print(f"   {D}fix: {fix}{X}")
    bad = sum(1 for r in rows if r[0] == "bad")
    print(f"\n{(R + str(bad) + ' to fix' + X) if bad else (G + 'nothing critical' + X)}")
    return 1 if bad else 0
