#!/usr/bin/env python3
"""Trader Bee CLI.

  python trader.py status                 what it is doing, budget used, approvals waiting
  python trader.py run [--interval 60]    the loop (paper unless config mode=live AND armed)
  python trader.py tick                   one pass
  python trader.py wallet-new             create the Bee's OWN wallet (prints the address only)
  python trader.py wallet                 address + balances on Base and Robinhood Chain
  python trader.py arm                    HUMAN ACT: enable live trading (type the phrase)
  python trader.py disarm                 stop live trading immediately (safe any time)
  python trader.py pause [--reason ..]    kill switch: no new buys (paper or live)
  python trader.py resume
  python trader.py intents [--state NEEDS_APPROVAL]
  python trader.py approve <intent_id>    your per-trade yes for a parked buy / take-profit
  python trader.py decline <intent_id>
  python trader.py sell --asset SYMBOL --pct 100 [--confirm GO]   manual market sell from the Bee wallet
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1]))  # Hive root
sys.path.insert(0, str(ROOT))

from trader_bee import config, executor  # noqa: E402
from trader_bee.agent import TraderBee, disarm  # noqa: E402


def _print(obj):
    print(json.dumps(obj, indent=2, default=str))


def cmd_status(bee: TraderBee, a):
    s = bee.status()
    if a.json:
        return _print(s)
    b = s["budget"]
    print(f"TRADER BEE  mode={s['effective_mode'].upper()} (config: {s['config_mode']}, armed: {'YES' if s['armed'] else 'no'}, key: {'yes' if s['key_present'] else 'NO'})")
    print(f"wallet      {s['wallet_address'] or '(run wallet / wallet-new)'}")
    print(f"controls    {'PAUSED — ' + str(s['controls'].get('paused_reason')) if s['controls'].get('paused') else 'running'}  consecutive failures: {s['controls'].get('consecutive_failures', 0)}")
    print(f"sizes       discovery {s['sizes']['discovery']}  zone entry ${s['sizes']['zone_entry']}")
    print(f"budget      24h ${b['used_24h']}/${b['daily_usd']}  7d ${b['used_7d']}/${b['weekly_usd']}  buys 24h {b['buys_24h']}/{b['max_buys_per_day']}")
    print(f"intents     {s['counts']}")
    for it in s["approvals"]:
        print(f"  ⏳ {it['id']}  {it['strategy']:<14} {it['symbol']:<10} ${it['usd']:<6g} {it['reason']}")
    for m in ("live", "paper"):
        for p in s["positions"][m]:
            pnl = f"{p['pnl_usd']:+.2f}" if p["pnl_usd"] is not None else "n/a"
            print(f"  [{m}] {p['symbol']:<10} cost ${p['cost']:.2f}  tokens {p['tokens_net']:.6g}  P&L {pnl}")


def cmd_wallet_new(bee, a):
    if config.KEY_FILE.exists():
        print(f"A Trader Bee wallet already exists ({config.KEY_FILE}). Refusing to overwrite it.")
        return 1
    config.SECRETS.mkdir(exist_ok=True)
    r = executor.call("wallet-new", {})
    if not r.get("ok"):
        print("FAILED:", r.get("error"))
        return 1
    bee.store.put("wallet_address", r["address"])
    print("Trader Bee wallet created. The private key was written ONLY to:")
    print(f"  {config.KEY_FILE}")
    print("Back that file up somewhere safe and offline. It is never printed and never leaves this machine.")
    print(f"\nFUND THIS ADDRESS (same address on Base and Robinhood Chain):\n  {r['address']}")
    print("  Base:           USDC  + a little ETH for gas (~$1-2 covers many buys)")
    print("  Robinhood Chain: USDG + a little ETH for gas")
    return 0


def cmd_wallet(bee, a):
    bee.housekeep(force=True)
    _print({"address": bee.store.get("wallet_address"), "balances": bee.store.get("balances")})


def cmd_arm(bee, a):
    cfg = bee.cfg
    if not config.KEY_FILE.exists():
        print("REFUSED: no Trader Bee wallet yet. Run `python trader.py wallet-new` and fund it first.")
        return 1
    if cfg["mode"] != "live":
        print('REFUSED: config/trader_bee.json has "mode": "paper". Change it to "live" yourself first (a deliberate edit), then arm.')
        return 1
    addr = executor.call("address", {}).get("address")
    b = cfg["budget"]
    print("You are arming the Trader Bee. From now on it BUYS BY ITSELF, from this wallet only:")
    print(f"  wallet   {addr}")
    print(f"  sizes    discovery {cfg['strategies']['discovery_tier']['sizes_usd']} · zone entry ${cfg['strategies']['zone_entry']['size_usd']}")
    print(f"  budgets  ${b['daily_usd']}/24h · ${b['weekly_usd']}/7d · {b['max_buys_per_day']} buys/24h · ${b['max_exposure_per_asset_usd']}/asset")
    print("  never    sells, take-profits, or soft-flagged buys without your approval")
    print("  stop     `python trader.py disarm` or the DISARM button in the Hive UI, any time")
    phrase = cfg["safety"]["arm_phrase"]
    typed = a.phrase if a.phrase is not None else input(f'\nType exactly: {phrase}\n> ')
    if typed.strip() != phrase:
        print("Phrase did not match. NOT armed.")
        return 1
    config.ARM_FILE.write_text(json.dumps({"armed_at": datetime.now(timezone.utc).isoformat(), "wallet": addr, "by": "beekeeper"}))
    bee.store.log("warn", f"ARMED by beekeeper for wallet {addr}")
    print("ARMED. Live trading is on. Mode:", config.effective_mode(cfg).upper())
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    s = p.add_subparsers(dest="cmd", required=True)
    st = s.add_parser("status")
    st.add_argument("--json", action="store_true")
    r = s.add_parser("run")
    r.add_argument("--interval", type=int, default=None)
    s.add_parser("tick")
    s.add_parser("wallet-new")
    s.add_parser("wallet")
    ar = s.add_parser("arm")
    ar.add_argument("--phrase", default=None)
    s.add_parser("disarm")
    pa = s.add_parser("pause")
    pa.add_argument("--reason", default="beekeeper kill switch")
    s.add_parser("resume")
    it = s.add_parser("intents")
    it.add_argument("--state", default=None)
    ap = s.add_parser("approve")
    ap.add_argument("intent_id")
    de = s.add_parser("decline")
    de.add_argument("intent_id")
    se = s.add_parser("sell")
    se.add_argument("--asset", required=True)
    se.add_argument("--pct", type=float, default=100)
    se.add_argument("--confirm", default="")
    a = p.parse_args()
    bee = TraderBee()

    if a.cmd == "status":
        return cmd_status(bee, a) or 0
    if a.cmd == "tick":
        return _print(bee.tick()) or 0
    if a.cmd == "run":
        import time
        every = a.interval or bee.cfg["loop"]["interval_seconds"]
        print(f"Trader Bee running every {every}s in {config.effective_mode(bee.cfg).upper()} mode. Ctrl+C to stop.")
        while True:
            print(json.dumps(bee.tick(), default=str), flush=True)
            time.sleep(every)
    if a.cmd == "wallet-new":
        return cmd_wallet_new(bee, a)
    if a.cmd == "wallet":
        return cmd_wallet(bee, a) or 0
    if a.cmd == "arm":
        return cmd_arm(bee, a)
    if a.cmd == "disarm":
        print("DISARMED." if disarm() else "Was not armed.")
        bee.store.log("warn", "DISARMED by beekeeper (CLI)")
        return 0
    if a.cmd == "pause":
        bee.set_paused(True, a.reason, "beekeeper")
        print("PAUSED.")
        return 0
    if a.cmd == "resume":
        bee.set_paused(False, None, "beekeeper")
        print("RESUMED.")
        return 0
    if a.cmd == "intents":
        rows = bee.store.intents((a.state,) if a.state else None)
        for x in rows:
            print(f"{x['id']}  {x['state']:<15} {x['mode']:<5} {x['strategy']:<14} {x['symbol']:<10} ${x['usd'] or 0:<6g} {x['reason'] or ''}")
        return 0
    if a.cmd == "approve":
        _print(bee.approve(a.intent_id))
        return 0
    if a.cmd == "decline":
        _print(bee.decline(a.intent_id))
        return 0
    if a.cmd == "sell":
        from trader_bee.sell import manual_sell
        return manual_sell(bee, a.asset, a.pct, a.confirm == "GO")
    return 2


if __name__ == "__main__":
    sys.exit(main())
