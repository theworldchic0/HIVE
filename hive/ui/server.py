"""Hive UI server — http://127.0.0.1:8790 (the trading terminal keeps 8789).

Read side: one aggregated GET /api/hive (Queen health, Bottom Blueprint clock, Market Direction
snapshot, Fib Bee watchlist, Trader Bee status, recent bus events). It reads local files and
SQLite only — no market API calls, no keys, nothing that can trade.

Write side (Trader Bee controls only), all POST + JSON + a custom header + a localhost Host
check, so a web page you visit can't forge these requests (CSRF / DNS-rebinding guard):
  /api/trader/pause    kill switch (safe direction, always allowed)
  /api/trader/resume
  /api/trader/disarm   stop LIVE trading now (safe direction). ARMING is deliberately NOT here:
                       it is a typed CLI act (`python trader.py arm`).
  /api/trader/approve  {id}  your per-trade yes for a parked buy / take-profit proposal
  /api/trader/decline  {id}
"""
from __future__ import annotations

import importlib.util
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .. import bus, queen_client
from ..paths import BLUEPRINT_DIR, MARKET_DIRECTION_DIR, TRADER_DIR, sub

STATIC = Path(__file__).resolve().parent / "static"
if str(TRADER_DIR) not in sys.path:
    sys.path.insert(0, str(TRADER_DIR))


def _json_file(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def blueprint() -> dict:
    try:
        spec = importlib.util.spec_from_file_location("hive_bottom_blueprint", BLUEPRINT_DIR / "bottom_blueprint.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        ctx = _json_file(BLUEPRINT_DIR / "shared_context" / "latest.json", {})
        return {"ok": True, "clock": mod.clock(), "cycle": mod.CFG["cycle"], "snapshot_id": ctx.get("snapshot_id"),
                "momentum_rule": (ctx.get("momentum") or {}).get("rule"), "cycle_top": ctx.get("cycle_top"),
                "status": ctx.get("status")}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def market_direction() -> dict:
    d = _json_file(MARKET_DIRECTION_DIR / "shared_context" / "market_direction" / "latest.json", {"status": "MISSING"})
    return {k: d.get(k) for k in ("snapshot_id", "status", "generated_at", "expires_at", "regime", "final_signal", "final_call",
                                   "horizons", "message")}


def fib() -> dict:
    s = _json_file(sub("fib_agent") / "state.json", {"watchlist": {}, "assets": {}})
    rows = []
    for aid, w in s.get("watchlist", {}).items():
        a = s.get("assets", {}).get(aid, {})
        rows.append({"asset_id": aid, "symbol": w.get("symbol"), "chain": w.get("chain"), "rank": w.get("rank"),
                     "status": a.get("status"), "zone": a.get("zone"), "percent": a.get("percent"), "in_buy_zone": a.get("in_buy_zone"),
                     "price": a.get("price"), "checked_at": a.get("checked_at"), "reason": a.get("reason")})
    return {"watching": len(rows), "rows": sorted(rows, key=lambda r: (not r["in_buy_zone"], -(r["percent"] or -1)))}


def trader():
    from trader_bee.agent import TraderBee
    return TraderBee()


def trader_status() -> dict:
    try:
        return {"ok": True, **trader().status()}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def setup_status() -> dict:
    from .. import keys
    rows = keys.status_rows()
    missing_required = [r["title"] for r in rows if r["level"] == "required" and not r["set"] and r["decision"] != "SKIPPED"]
    return {"keys": rows, "missing_required": missing_required, "undecided": len(keys.undecided())}


def scout_queue() -> dict:
    q = _json_file(sub("scout") / "queue.json", {})
    rows = sorted((r for r in q.values() if r.get("status") == "QUEUED"), key=lambda r: -(r.get("scout_score") or 0))
    done = sorted((r for r in q.values() if r.get("status") == "RESEARCHED"), key=lambda r: r.get("researched_at") or "", reverse=True)
    return {"queued": rows[:50], "queued_count": len(rows), "researched": done[:10], "total_seen": len(q)}


def meta_state() -> dict:
    st = _json_file(sub("meta") / "state.json", None)
    if not st:
        return {"ok": False, "note": "Meta Bee has not produced a board yet (it starts with `python -m hive start`)."}
    return {"ok": True, "updated_at": st.get("updated_at"), "history_hours": st.get("history_hours"), "metas": st.get("metas", [])[:12],
            "top": st.get("top"), "emerging": st.get("emerging_unclassified", [])[:12], "workers": st.get("workers", {})}


def hive_state() -> dict:
    q = queen_client.snapshot()
    return {"queen": {"agents": q.get("agents", []), "recommendations": q.get("open_recommendations", []), "timestamp": q.get("timestamp_utc"),
                      "error": q.get("error")},
            "blueprint": blueprint(), "market_direction": market_direction(), "fib": fib(), "trader": trader_status(),
            "setup": setup_status(), "scout": scout_queue(), "meta": meta_state(),
            "cohort": _json_file(sub("bottom_blueprint") / "performance.json", None),
            "events": list(reversed(bus.tail(40)))}


class Handler(BaseHTTPRequestHandler):
    server_version = "HiveUI/1.0"

    def log_message(self, fmt, *args):  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj):
        self._send(code, json.dumps(obj, default=str).encode(), "application/json")

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def do_GET(self):
        if not self._host_ok():
            return self._json(403, {"error": "bad host"})
        path = self.path.split("?")[0]
        if path == "/api/hive":
            return self._json(200, hive_state())
        if path in ("/", "/index.html"):
            return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/app.js":
            return self._send(200, (STATIC / "app.js").read_bytes(), "text/javascript; charset=utf-8")
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        if not self._host_ok() or self.headers.get("X-Hive") != "1" or "application/json" not in (self.headers.get("Content-Type") or ""):
            return self._json(403, {"error": "forbidden"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(min(n, 10_000)) or b"{}")
        except Exception:
            return self._json(400, {"error": "bad json"})
        path = self.path.split("?")[0]
        try:
            t = trader()
            if path == "/api/trader/pause":
                return self._json(200, t.set_paused(True, str(body.get("reason") or "kill switch (Hive UI)")[:200], "beekeeper (ui)"))
            if path == "/api/trader/resume":
                return self._json(200, t.set_paused(False, None, "beekeeper (ui)"))
            if path == "/api/trader/disarm":
                from trader_bee.agent import disarm
                was = disarm("beekeeper (ui)")
                t.store.log("warn", "DISARMED by beekeeper (Hive UI)")
                return self._json(200, {"disarmed": True, "was_armed": was})
            if path == "/api/trader/approve":
                return self._json(200, t.approve(str(body["id"]), "beekeeper (ui)"))
            if path == "/api/trader/decline":
                return self._json(200, t.decline(str(body["id"]), "beekeeper (ui)"))
        except (ValueError, KeyError) as e:
            return self._json(409, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            return self._json(500, {"error": f"{type(e).__name__}: {e}"})
        return self._json(404, {"error": "not found"})


def serve(port: int = 8790):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Hive UI → http://127.0.0.1:{port}  (Ctrl+C to stop)", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
