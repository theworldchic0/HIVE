"""`python -m hive setup` — the first-run walkthrough: every API key, once, verified live.

Runs automatically the first time you start the Hive (HIVE.bat / HIVE.command / `python -m hive start`)
while any key is still undecided. Rules it follows:
  * The key is typed/pasted into THIS terminal only (hidden while you paste). It is written to
    module/.env (root .env for X) on this computer and never printed, logged, or sent anywhere except
    the one verify call to the service that issued it.
  * Every key gets a live test. A rejected key is never saved silently.
  * Skipping is a conscious act: you type the literal word SKIP after being told what stops working.
    Every DONE / UNVERIFIED / SKIPPED is recorded with a date in SETUP-STATE.md.
  * It never arms the Trader Bee and never changes its sizes, budgets or mode.
"""
from __future__ import annotations

import getpass
import shutil
import subprocess
import sys

from . import keys
from .paths import TRADER_DIR

ask = input
ask_secret = getpass.getpass
say = print

BOLD, DIM, GREEN, RED, YELLOW, RESET = ("\033[1m", "\033[2m", "\033[32m", "\033[31m", "\033[33m", "\033[0m") if sys.stdout.isatty() else ("",) * 6
LEVEL = {"required": f"{RED}REQUIRED{RESET}", "recommended": f"{YELLOW}RECOMMENDED{RESET}", "optional": f"{DIM}optional{RESET}"}


def _hr():
    say(DIM + "─" * 72 + RESET)


def _save(spec: keys.KeySpec, value: str) -> str:
    """Verify, then write. Returns DONE / UNVERIFIED / REJECTED."""
    say("  testing it live…")
    ok, why, extra = keys.verify(spec, value)
    if ok is False:
        say(f"  {RED}✗ {why}{RESET}")
        return "REJECTED"
    keys.write_key(spec.file, spec.name, value)
    for k, v in extra.items():
        keys.write_key(spec.file, k, v)
    status = "DONE" if ok else "UNVERIFIED"
    keys.note(spec.name, status, why)
    say(f"  {GREEN if ok else YELLOW}{'✓' if ok else '•'} {why}{RESET}")
    say(f"  saved to {spec.file.name} as {keys.mask(value)}")
    return status


def _one(spec: keys.KeySpec, i: int, n: int) -> None:
    _hr()
    say(f"{BOLD}[{i}/{n}] {spec.title}{RESET}   {LEVEL[spec.level]}   → {keys.rel(spec.file)} · {spec.name}")
    say(f"  Powers:        {spec.powers}")
    say(f"  If skipped:    {spec.if_skipped}")
    cur = keys.current(spec)
    if cur:
        say(f"  Current:       {GREEN}set{RESET} {keys.mask(cur)}  ({keys.record().get(spec.name, {}).get('status', 'not yet tested')})")
        a = ask("  Enter = keep it · NEW = replace it · TEST = re-test it live: ").strip().upper()
        if a == "TEST":
            ok, why, extra = keys.verify(spec, cur)
            say(f"  {GREEN + '✓' if ok else (RED + '✗' if ok is False else YELLOW + '•')} {why}{RESET}")
            if ok is not False:
                for k, v in extra.items():
                    keys.write_key(spec.file, k, v)
                keys.note(spec.name, "DONE" if ok else "UNVERIFIED", why)
            else:
                keys.note(spec.name, "UNVERIFIED", "re-test FAILED: " + why)
            return
        if a != "NEW":
            return
    # special case: build the Base RPC from the Alchemy key
    if spec.name == "BASE_RPC_URL":
        ak = keys.current(keys.BY_NAME["ALCHEMY_API_KEY"])
        if ak and ask("  Use your Alchemy key as the Trader Bee's private Base RPC? [Y/n]: ").strip().lower() in ("", "y", "yes"):
            if _save(spec, f"https://base-mainnet.g.alchemy.com/v2/{ak}") != "REJECTED":
                return
    say("  How to get it:")
    for n_, step in enumerate(spec.get_it, 1):
        say(f"    {n_}. {step}")
    while True:
        say(f"  {DIM}Paste it and press Enter. It stays hidden while you paste — that's on purpose.{RESET}")
        v = ask_secret("  Key (or type SKIP): ").strip()
        if v == "SKIP":
            keys.note(spec.name, "SKIPPED", f"consciously skipped — {spec.if_skipped}")
            say(f"  {YELLOW}skipped (recorded). Re-run `python -m hive setup` any time to add it.{RESET}")
            return
        if not v:
            say("  Nothing pasted. Paste the key, or type the word SKIP to skip it.")
            continue
        if v.upper() == "SKIP":
            say("  To skip, type SKIP in capitals (the conscious-skip rule).")
            continue
        st = _save(spec, v)
        if st != "REJECTED":
            return
        a = ask("  R = try again · K = keep it anyway (recorded as UNVERIFIED) · SKIP: ").strip()
        if a == "SKIP":
            keys.note(spec.name, "SKIPPED", "skipped after a failed verify")
            return
        if a.upper() == "K":
            keys.write_key(spec.file, spec.name, v)
            keys.note(spec.name, "UNVERIFIED", "kept by beekeeper although the live test rejected it")
            say(f"  {YELLOW}kept, recorded as UNVERIFIED.{RESET}")
            return


def _trader_steps() -> None:
    _hr()
    say(f"{BOLD}Trader Bee{RESET}")
    ex = TRADER_DIR / "executor"
    if not shutil.which("node"):
        say(f"  {RED}Node.js not found.{RESET} Install Node 20+ from https://nodejs.org (LTS), then re-run setup. "
            "Without it the Trader Bee can't quote or trade (everything else in the Hive still runs).")
    elif not (ex / "node_modules").exists():
        if ask("  The trade executor needs its packages (one-time `npm install`, ~30 s). Install now? [Y/n]: ").strip().lower() in ("", "y", "yes"):
            npm = shutil.which("npm") or "npm"
            r = subprocess.run([npm, "install", "--no-audit", "--no-fund"], cwd=str(ex), shell=(sys.platform == "win32"))
            if r.returncode == 0:
                subprocess.run([npm, "run", "-s", "selftest"], cwd=str(ex), shell=(sys.platform == "win32"))
            else:
                say(f"  {RED}npm install failed — run it yourself in {ex}{RESET}")
    else:
        say(f"  {GREEN}✓{RESET} executor installed")
    key = TRADER_DIR / "secrets" / "agent_wallet.key"
    if key.exists():
        say(f"  {GREEN}✓{RESET} Trader Bee wallet exists — `python trader.py wallet` (inside trader-bee/) shows its address + balances")
    else:
        say("  The Trader Bee has no wallet yet. It gets its OWN wallet (never your main one); the key is made on this")
        say("  computer and stored only in trader-bee/secrets/agent_wallet.key. You can do this later with `python trader.py wallet-new`.")
        if ask("  Type YES to create it now (anything else = later): ").strip() == "YES":
            subprocess.run([sys.executable, str(TRADER_DIR / "trader.py"), "wallet-new"], cwd=str(TRADER_DIR))
    say(f"  Mode stays {BOLD}PAPER{RESET}. Going live is your separate, deliberate act: set \"mode\": \"live\" in")
    say("  trader-bee/config/trader_bee.json, fund the wallet, then `python trader.py arm`. Setup never arms it.")


def summary() -> None:
    _hr()
    say(f"{BOLD}Key status{RESET}  (values never shown)")
    for r in keys.status_rows():
        mark = f"{GREEN}✓{RESET}" if r["set"] else (f"{YELLOW}–{RESET}" if r["decision"] == "SKIPPED" else f"{RED}✗{RESET}")
        say(f"  {mark} {r['title']:<42} {r['level']:<12} {r['masked'] if r['set'] else (r['decision'] or 'not set')}"
            + (f"  {DIM}({r['decision']}){RESET}" if r["set"] and r["decision"] else ""))
    say(f"\n  Re-run any time: {BOLD}python -m hive setup{RESET}   ·   full health check: {BOLD}python -m hive doctor{RESET}")


def run(only_missing: bool = False) -> int:
    say(f"\n{BOLD}🐝 NUK3R2 HIVE — API KEY WALKTHROUGH{RESET}")
    say("  Each key: what it does → where to get it → paste it here (hidden) → live test → saved to your .env.")
    say("  Keys go ONLY into files on this computer. Never paste a key into a chat with anyone, Claude included.")
    todo = keys.undecided() if only_missing else keys.SPECS
    if only_missing and not todo:
        say("  All keys are set or consciously skipped.")
    for i, spec in enumerate(todo, 1):
        try:
            _one(spec, i, len(todo))
        except (KeyboardInterrupt, EOFError):
            say(f"\n  {YELLOW}Stopped. Nothing half-written; re-run `python -m hive setup` to continue where you left off.{RESET}")
            return 1
    try:
        _trader_steps()
    except (KeyboardInterrupt, EOFError):
        return 1
    summary()
    return 0


def check() -> int:
    """Non-interactive status (exit 1 while a REQUIRED key is missing and not skipped)."""
    summary()
    missing = [s for s in keys.undecided() if s.level == "required"]
    return 1 if missing else 0
