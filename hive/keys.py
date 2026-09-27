"""Every API key the Hive + the trading terminal use, in one table, with a LIVE verify for each.

Keys live in ONE place so they're entered once: `module/.env` (the terminal's file, which the Hive
also reads), except X_BEARER_TOKEN which the terminal reads from the root `.env`.
Values are never printed — only masked (first 4 … last 2 + length).
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .paths import HIVE_ROOT, MODULE_DIR, sub

MODULE_ENV = MODULE_DIR / ".env"
ROOT_ENV = HIVE_ROOT / ".env"
PLACEHOLDER = re.compile(r"^$|^(your|paste|replace|changeme|change_me|xxx+|placeholder|<.*>|todo|tbd)", re.I)


@dataclass
class KeySpec:
    name: str
    title: str
    level: str                     # required | recommended | optional
    powers: str
    if_skipped: str
    get_it: list[str]
    file: Path = MODULE_ENV
    verify: str | None = None      # name of a verify function below, or None (format check only)
    no_verify_reason: str = ""
    pattern: str = r"^\S{8,}$"
    extra: dict = field(default_factory=dict)


SPECS: list[KeySpec] = [
    KeySpec("ONEINCH_API_KEY", "1inch API key", "required",
            "Trader Bee quotes + swaps (1inch side of the best-price race) and resting take-profit orders; the terminal's execution engine.",
            "Trader Bee can still paper-trade on KyberSwap quotes, but it can't use 1inch or place take-profits, and the terminal can't trade.",
            ["Go to https://portal.1inch.dev and sign in (email or wallet).",
             "Open 'Applications' → create an app (any name, e.g. 'hive').",
             "Copy the API key shown for that app."],
            verify="oneinch"),
    KeySpec("ALCHEMY_API_KEY", "Alchemy API key", "recommended",
            "The terminal's wallet + ledger tracking, and a private, reliable Base RPC for the Trader Bee (public RPCs rate-limit).",
            "The terminal's portfolio/ledger go blind; the Trader Bee falls back to the public Base RPC (slower, may rate-limit).",
            ["Go to https://dashboard.alchemy.com and create a free account.",
             "Create an app → chain: Base → network: Base Mainnet.",
             "Open the app → 'API Key' → copy the key (just the key, not the whole URL)."],
            verify="alchemy"),
    KeySpec("COINGECKO_API_KEY", "CoinGecko API key", "recommended",
            "Fib Bee candles + live pool prices (CoinGecko on-chain API) and the terminal's charts. Demo (free) or Pro keys both work.",
            "Fib Bee uses keyless GeckoTerminal paced at 2.6 s per call — works, but slow and can hit rate limits; terminal charts may go blank.",
            ["Go to https://www.coingecko.com/en/api/pricing → pick the free 'Demo' plan (or your paid plan).",
             "Open your developer dashboard → 'Add New Key' → copy it.",
             "The walkthrough detects Demo vs Pro automatically."],
            verify="coingecko"),
    KeySpec("CODEX_API_KEY", "Codex API key", "optional",
            "The terminal's momentum screens (doctrine/list-a-screen.mjs, screens/momentum-today.mjs) — research discovery lists.",
            "Those momentum screens throw immediately; suggestion lists stay empty. The Hive's own Discovery Scout does NOT need it.",
            ["Go to https://www.codex.io → sign up → Dashboard → API keys.", "Create a key and copy it."],
            verify="codex"),
    KeySpec("ELFA_API_KEY", "Elfa API key", "optional",
            "screens/elfa-probe.mjs social-signal probe (bills credits per stage; nothing runs it by default).",
            "The social probe won't run. Nothing else changes.",
            ["Go to https://www.elfa.ai → developer / API access → create a key."],
            no_verify_reason="not tested live — Elfa bills credits per call, so the walkthrough only checks the format"),
    KeySpec("X_BEARER_TOKEN", "X (Twitter) bearer token", "optional",
            "Founder / social tracing lookups in research (official X API, pay-per-use).",
            "Social tracing via the terminal is off. (X via an MCP server in your Claude client doesn't need this.)",
            ["Go to https://developer.x.com → sign in → create a Project + App.",
             "Keys and tokens → Bearer Token → Generate → copy it.",
             "Add a few dollars of pay-per-use credit if the portal asks."],
            file=ROOT_ENV, no_verify_reason="not tested live — X bills per read, so the walkthrough only checks the format"),
    KeySpec("ANTHROPIC_API_KEY", "Anthropic API key (optional parsing)", "optional",
            "Lets the terminal's Trade Idea panel parse dictation with Claude. OFF by default: the TEXT of each dictation is then sent to api.anthropic.com.",
            "Dictation parsing stays 100% local (the default). Nothing breaks.",
            ["Go to https://console.anthropic.com → API Keys → Create Key → copy it."],
            verify="anthropic"),
    KeySpec("BASE_RPC_URL", "Base RPC URL (optional override)", "optional",
            "A private Base RPC for the Trader Bee executor. If you entered an Alchemy key, the walkthrough can fill this for you.",
            "Uses the public https://mainnet.base.org (slower, can rate-limit). The walkthrough can build this from your Alchemy key.",
            ["Any Base mainnet RPC URL (Alchemy, QuickNode, Infura…), e.g. https://base-mainnet.g.alchemy.com/v2/<key>."],
            verify="rpc", pattern=r"^https://\S+$", extra={"chain_id": 8453}),
    KeySpec("ROBINHOOD_RPC_URL", "Robinhood Chain RPC URL (optional override)", "optional",
            "A private Robinhood Chain RPC for the Trader Bee executor.",
            "Uses the public https://rpc.mainnet.chain.robinhood.com.",
            ["Only if your RPC provider offers Robinhood Chain (chain id 4663)."],
            verify="rpc", pattern=r"^https://\S+$", extra={"chain_id": 4663}),
]
BY_NAME = {s.name: s for s in SPECS}


# ------------------------------------------------------------------ .env files
def parse_env(path: Path) -> dict:
    out = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return out


def is_set(v) -> bool:
    return v is not None and not PLACEHOLDER.search(str(v).strip()) and "PASTE_" not in str(v)


def current(spec: KeySpec) -> str | None:
    v = parse_env(spec.file).get(spec.name)
    return v if is_set(v) else None


def mask(v: str | None) -> str:
    if not v:
        return "—"
    if v.startswith("https://"):
        # an RPC URL often carries the key in its path or query: show only the host, always
        return "https://" + v[8:].split("/", 1)[0].split("?", 1)[0] + ("/•••" if len(v[8:]) > len(v[8:].split("/", 1)[0]) else "")
    return f"{v[:4]}…{v[-2:]} ({len(v)} chars)"


def write_key(path: Path, name: str, value: str) -> None:
    """Replace NAME=... (placeholder or old value) or append it. Atomic; file kept private (0600)."""
    if not re.fullmatch(r"[A-Z0-9_]+", name) or any(c in value for c in "\r\n"):
        raise ValueError("refusing to write a malformed key/value")
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else [
        "# API keys — local only. Never commit, never paste into a chat. Written by `python -m hive setup`."]
    done = False
    for i, line in enumerate(lines):
        if re.match(rf"^\s*{re.escape(name)}\s*=", line):
            lines[i] = f"{name}={value}"
            done = True
    if not done:
        lines.append(f"{name}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass  # Windows: file ACLs, chmod is a no-op
    os.replace(tmp, path)


# ------------------------------------------------------------------ live verification
# Tests swap this: http(url, method, headers, body) -> (status, bytes)
http = None


def _http(url, method="GET", headers=None, body=None, timeout=12):
    if http is not None:
        return http(url, method, headers or {}, body)
    data = json.dumps(body).encode() if body is not None else None
    h = {"User-Agent": "NUK3R2-Hive-setup/1.0", "Accept": "application/json", **(headers or {})}
    if data is not None:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() if hasattr(e, "read") else b""


def _rpc(url, method):
    st, raw = _http(url, "POST", body={"jsonrpc": "2.0", "id": 1, "method": method, "params": []})
    if st != 200:
        raise RuntimeError(f"HTTP {st}")
    j = json.loads(raw)
    if j.get("error"):
        raise RuntimeError(j["error"].get("message", "rpc error"))
    return int(j["result"], 16)


def v_oneinch(key, spec):
    st, _ = _http("https://api.1inch.dev/swap/v6.0/8453/tokens", headers={"Authorization": f"Bearer {key}"})
    if st in (401, 403):
        return False, f"1inch rejected the key (HTTP {st}) — re-copy it from portal.1inch.dev", {}
    if st in (200, 429):
        return True, f"1inch accepted the key (HTTP {st})", {}
    return None, f"1inch answered HTTP {st} — key saved but not confirmed", {}


def v_alchemy(key, spec):
    block = _rpc(f"https://base-mainnet.g.alchemy.com/v2/{key}", "eth_blockNumber")
    return True, f"Alchemy works — Base block #{block:,}", {}


def v_coingecko(key, spec):
    for plan, url, hdr in (("pro", "https://pro-api.coingecko.com/api/v3/ping", "x-cg-pro-api-key"),
                           ("demo", "https://api.coingecko.com/api/v3/ping", "x-cg-demo-api-key")):
        st, _ = _http(url, headers={hdr: key})
        if st == 200:
            return True, f"CoinGecko accepted it as a {plan.upper()} key", {"COINGECKO_API_PLAN": plan}
    return False, "CoinGecko rejected the key on both the Pro and the Demo endpoint", {}


def v_codex(key, spec):
    st, raw = _http("https://graph.codex.io/graphql", "POST", headers={"Authorization": key}, body={"query": "{ getNetworks { id } }"})
    txt = raw.decode(errors="ignore")[:300].lower()
    if st in (401, 403) or "unauthorized" in txt or "invalid api key" in txt:
        return False, f"Codex rejected the key (HTTP {st})", {}
    if st == 200 and '"data"' in txt:
        return True, "Codex accepted the key", {}
    return None, f"Codex answered HTTP {st} — key saved but not confirmed", {}


def v_anthropic(key, spec):
    st, _ = _http("https://api.anthropic.com/v1/models", headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
    if st == 200:
        return True, "Anthropic accepted the key", {}
    if st in (401, 403):
        return False, f"Anthropic rejected the key (HTTP {st})", {}
    return None, f"Anthropic answered HTTP {st} — key saved but not confirmed", {}


def v_rpc(url, spec):
    cid = _rpc(url, "eth_chainId")
    want = spec.extra["chain_id"]
    if cid != want:
        return False, f"that RPC is chain {cid}, not {want} — wrong network", {}
    return True, f"RPC answers as chain {cid} (block #{_rpc(url, 'eth_blockNumber'):,})", {}


VERIFIERS = {"oneinch": v_oneinch, "alchemy": v_alchemy, "coingecko": v_coingecko, "codex": v_codex, "anthropic": v_anthropic, "rpc": v_rpc}


def verify(spec: KeySpec, value: str) -> tuple[bool | None, str, dict]:
    """(True, why, extra_keys) = verified live · (False, why, {}) = rejected · (None, why, {}) = could not confirm."""
    if not re.fullmatch(spec.pattern, value):
        return False, "that doesn't look like a valid value (spaces, too short, or not a URL where a URL is expected)", {}
    if not spec.verify:
        return None, spec.no_verify_reason or "format OK (no live check for this key)", {}
    try:
        return VERIFIERS[spec.verify](value, spec)
    except Exception as e:  # noqa: BLE001 — offline / DNS / TLS: say so, never pretend it verified
        return None, f"could not reach the service to verify ({type(e).__name__}: {str(e)[:80]}) — saved, NOT verified", {}


# ------------------------------------------------------------------ the record (conscious-skip law)
def _state_file() -> Path:
    return sub("setup") / "keys.json"


def record() -> dict:
    try:
        return json.loads(_state_file().read_text(encoding="utf-8"))
    except Exception:
        return {}


def note(name: str, status: str, detail: str) -> None:
    """status: DONE | UNVERIFIED | SKIPPED. Also appends the dated paper-trail line to SETUP-STATE.md."""
    r = record()
    at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    r[name] = {"status": status, "at": at, "detail": detail[:200]}
    p = _state_file()
    p.write_text(json.dumps(r, indent=1), encoding="utf-8")
    ss = HIVE_ROOT / "SETUP-STATE.md"
    try:
        txt = ss.read_text(encoding="utf-8")
        txt = txt.replace("(nothing recorded yet — run SETUP-CLAUDE.md Step 0)\n", "")
        if not txt.endswith("\n"):
            txt += "\n"
        txt += f"- {at} · HIVE KEYS · {name} · {status} — {detail[:160]}\n"
        ss.write_text(txt, encoding="utf-8")
    except FileNotFoundError:
        pass


def rel(p: Path) -> str:
    try:
        return str(p.relative_to(HIVE_ROOT))
    except ValueError:
        return p.name


def status_rows() -> list[dict]:
    """For the doctor + UI. Never includes a value — only masked form and state."""
    rec = record()
    rows = []
    for s in SPECS:
        v = current(s)
        r = rec.get(s.name, {})
        rows.append({"name": s.name, "title": s.title, "level": s.level, "set": bool(v), "masked": mask(v),
                     "file": rel(s.file), "decision": r.get("status"), "decided_at": r.get("at")})
    return rows


def undecided() -> list[KeySpec]:
    """Keys with no value AND no recorded conscious SKIP — i.e. the walkthrough still owes them a question."""
    rec = record()
    return [s for s in SPECS if not current(s) and rec.get(s.name, {}).get("status") != "SKIPPED"]
