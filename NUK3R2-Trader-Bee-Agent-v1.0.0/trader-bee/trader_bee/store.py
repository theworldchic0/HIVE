"""Durable Trader Bee state (SQLite in <HIVE_DATA>/trader_bee/trader_bee.db).

The intents table is the heart of it. Every buy the Bee considers becomes ONE row keyed by a
UNIQUE idempotency key (discovery:<asset> / zone:<asset>:<structure>), so a replayed event,
a crash, or two loops running at once can never buy the same thing twice.

Intent state machine
    PLANNED ──gates──► REJECTED (retryable or final)
                   ├─► NEEDS_APPROVAL ──beekeeper──► APPROVED ──► (execute) / DECLINED
                   └─► READY ──► SUBMITTING ──► CONFIRMED | FAILED | UNKNOWN (reconcile)
    paper mode: READY ──► PAPER_FILLED
SUBMITTING is written BEFORE the executor is called; a row found in SUBMITTING at startup is
never re-sent — it is reconciled against the chain via the executor journal.
"""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone

from hive.paths import sub

SCHEMA = """
CREATE TABLE IF NOT EXISTS assets(
  asset_id TEXT PRIMARY KEY, chain TEXT, contract TEXT, symbol TEXT, rank TEXT, gate TEXT,
  confidence TEXT, discovery INTEGER, researched_at TEXT, verdict_json TEXT, updated_at REAL);
CREATE TABLE IF NOT EXISTS intents(
  id TEXT PRIMARY KEY, idem_key TEXT UNIQUE NOT NULL, asset_id TEXT NOT NULL, chain TEXT, contract TEXT,
  symbol TEXT, strategy TEXT NOT NULL, tier TEXT, usd REAL, mode TEXT, state TEXT NOT NULL, reason TEXT,
  retryable INTEGER DEFAULT 0, trigger_json TEXT DEFAULT '{}', gates_json TEXT DEFAULT '{}',
  quote_json TEXT DEFAULT '{}', result_json TEXT DEFAULT '{}', tx_hash TEXT, venue TEXT,
  token_amount REAL, stable_spent REAL, fill_price_usd REAL, parent_id TEXT,
  approved_by TEXT, approved_at REAL, attempts INTEGER DEFAULT 0, last_attempt_at REAL,
  created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS ix_intents_state ON intents(state);
CREATE INDEX IF NOT EXISTS ix_intents_asset ON intents(asset_id);
CREATE TABLE IF NOT EXISTS control(key TEXT PRIMARY KEY, value TEXT, updated_at REAL);
CREATE TABLE IF NOT EXISTS log(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, level TEXT, intent_id TEXT, message TEXT, data_json TEXT);
CREATE TABLE IF NOT EXISTS marks(asset_id TEXT PRIMARY KEY, price_usd REAL, source TEXT, marked_at REAL, error TEXT);
"""

SPEND_STATES = ("SUBMITTING", "SUBMITTED", "CONFIRMED", "UNKNOWN")
PAPER_SPEND_STATES = ("PAPER_FILLED",)
OPEN_STATES = ("PLANNED", "READY", "APPROVED", "SUBMITTING", "SUBMITTED")


def now() -> float:
    return time.time()


def iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Store:
    def __init__(self, path=None):
        self.path = path or (sub("trader_bee") / "trader_bee.db")
        self.c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        self.c.row_factory = sqlite3.Row
        self.c.execute("PRAGMA journal_mode=WAL")
        self.c.executescript(SCHEMA)

    # ---------- control / kv ----------
    def get(self, key: str, default=None):
        r = self.c.execute("SELECT value FROM control WHERE key=?", (key,)).fetchone()
        return json.loads(r["value"]) if r else default

    def put(self, key: str, value) -> None:
        self.c.execute("INSERT INTO control(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                       (key, json.dumps(value), now()))

    def log(self, level: str, message: str, intent_id: str | None = None, data: dict | None = None) -> None:
        self.c.execute("INSERT INTO log(ts,level,intent_id,message,data_json) VALUES(?,?,?,?,?)",
                       (now(), level, intent_id, message[:1000], json.dumps(data or {}, default=str)))

    def recent_log(self, n: int = 100) -> list[dict]:
        rows = self.c.execute("SELECT * FROM log ORDER BY id DESC LIMIT ?", (n,)).fetchall()
        return [{**dict(r), "ts": iso(r["ts"]), "data": json.loads(r["data_json"] or "{}")} for r in rows]

    # ---------- assets (latest verdict per asset) ----------
    def upsert_asset(self, v: dict, confidence: str | None) -> bool:
        """Store the verdict if it is newer than what we have. Returns True if it was newer."""
        cur = self.c.execute("SELECT researched_at FROM assets WHERE asset_id=?", (v["asset_id"],)).fetchone()
        if cur and cur["researched_at"] and cur["researched_at"] > v["researched_at"]:
            return False
        self.c.execute(
            "INSERT INTO assets(asset_id,chain,contract,symbol,rank,gate,confidence,discovery,researched_at,verdict_json,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(asset_id) DO UPDATE SET chain=excluded.chain, contract=excluded.contract, "
            "symbol=excluded.symbol, rank=excluded.rank, gate=excluded.gate, confidence=excluded.confidence, discovery=excluded.discovery, "
            "researched_at=excluded.researched_at, verdict_json=excluded.verdict_json, updated_at=excluded.updated_at",
            (v["asset_id"], v["chain"], v["contract"], v["symbol"], v["rank"], v["gate"]["result"], confidence,
             1 if v.get("discovery") else 0, v["researched_at"], json.dumps(v), now()))
        return True

    def asset(self, asset_id: str) -> dict | None:
        r = self.c.execute("SELECT * FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
        if not r:
            return None
        return {**dict(r), "verdict": json.loads(r["verdict_json"])}

    def assets(self) -> list[dict]:
        return [dict(r) for r in self.c.execute("SELECT asset_id,chain,contract,symbol,rank,gate,confidence,discovery,researched_at FROM assets ORDER BY researched_at DESC")]

    # ---------- intents ----------
    def create_intent(self, row: dict) -> dict | None:
        """Insert a new intent. Returns None if the idempotency key already exists."""
        t = now()
        fields = {"state": "PLANNED", "created_at": t, "updated_at": t, **row}
        for k in ("trigger_json", "gates_json", "quote_json", "result_json"):
            if isinstance(fields.get(k), (dict, list)):
                fields[k] = json.dumps(fields[k], default=str)
        cols = ",".join(fields)
        try:
            self.c.execute(f"INSERT INTO intents({cols}) VALUES({','.join('?' * len(fields))})", tuple(fields.values()))
        except sqlite3.IntegrityError:
            return None
        return self.intent(fields["id"])

    def update_intent(self, intent_id: str, **fields) -> dict:
        for k in ("trigger_json", "gates_json", "quote_json", "result_json"):
            if isinstance(fields.get(k), (dict, list)):
                fields[k] = json.dumps(fields[k], default=str)
        fields["updated_at"] = now()
        sets = ",".join(f"{k}=?" for k in fields)
        self.c.execute(f"UPDATE intents SET {sets} WHERE id=?", (*fields.values(), intent_id))
        return self.intent(intent_id)

    def transition(self, intent_id: str, from_states: tuple, **fields) -> bool:
        """Compare-and-set state change: only applies if the row is still in one of from_states."""
        fields["updated_at"] = now()
        for k in ("trigger_json", "gates_json", "quote_json", "result_json"):
            if isinstance(fields.get(k), (dict, list)):
                fields[k] = json.dumps(fields[k], default=str)
        sets = ",".join(f"{k}=?" for k in fields)
        q = f"UPDATE intents SET {sets} WHERE id=? AND state IN ({','.join('?' * len(from_states))})"
        cur = self.c.execute(q, (*fields.values(), intent_id, *from_states))
        return cur.rowcount == 1

    @staticmethod
    def _hydrate(r) -> dict:
        d = dict(r)
        for k in ("trigger_json", "gates_json", "quote_json", "result_json"):
            d[k[:-5]] = json.loads(d.pop(k) or "{}")
        d["created_at_iso"], d["updated_at_iso"] = iso(d["created_at"]), iso(d["updated_at"])
        return d

    def intent(self, intent_id: str) -> dict | None:
        r = self.c.execute("SELECT * FROM intents WHERE id=?", (intent_id,)).fetchone()
        return self._hydrate(r) if r else None

    def intent_by_key(self, key: str) -> dict | None:
        r = self.c.execute("SELECT * FROM intents WHERE idem_key=?", (key,)).fetchone()
        return self._hydrate(r) if r else None

    def intents(self, states: tuple | None = None, limit: int = 200, strategy: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM intents", []
        where = []
        if states:
            where.append(f"state IN ({','.join('?' * len(states))})")
            args += list(states)
        if strategy:
            where.append("strategy=?")
            args.append(strategy)
        if where:
            q += " WHERE " + " AND ".join(where)
        q += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        return [self._hydrate(r) for r in self.c.execute(q, args)]

    # ---------- budget ----------
    def spent(self, mode: str, since_ts: float, asset_id: str | None = None) -> tuple[float, int]:
        states = PAPER_SPEND_STATES if mode == "paper" else SPEND_STATES
        q = (f"SELECT COALESCE(SUM(COALESCE(stable_spent, usd)),0) s, COUNT(*) n FROM intents WHERE mode=? AND strategy!='take_profit' "
             f"AND state IN ({','.join('?' * len(states))}) AND COALESCE(last_attempt_at, created_at)>=?")
        args = [mode, *states, since_ts]
        if asset_id:
            q += " AND asset_id=?"
            args.append(asset_id)
        r = self.c.execute(q, args).fetchone()
        return float(r["s"]), int(r["n"])

    def last_buy_at(self, asset_id: str, strategy: str, mode: str) -> float | None:
        states = PAPER_SPEND_STATES if mode == "paper" else SPEND_STATES
        r = self.c.execute(f"SELECT MAX(COALESCE(last_attempt_at, created_at)) t FROM intents WHERE asset_id=? AND strategy=? AND mode=? "
                           f"AND state IN ({','.join('?' * len(states))})", (asset_id, strategy, mode, *states)).fetchone()
        return r["t"]

    # ---------- positions ----------
    def positions(self, mode: str) -> list[dict]:
        states = PAPER_SPEND_STATES if mode == "paper" else ("CONFIRMED",)
        rows = self.c.execute(
            f"SELECT asset_id, chain, contract, symbol, SUM(COALESCE(token_amount,0)) tokens, SUM(COALESCE(stable_spent,usd)) cost, COUNT(*) buys, "
            f"MIN(created_at) first_at FROM intents WHERE mode=? AND strategy IN ('discovery_tier','zone_entry','manual') "
            f"AND state IN ({','.join('?' * len(states))}) GROUP BY asset_id", (mode, *states)).fetchall()
        sold = {r["asset_id"]: r["t"] for r in self.c.execute(
            f"SELECT asset_id, SUM(COALESCE(token_amount,0)) t FROM intents WHERE mode=? AND strategy IN ('take_profit','manual_sell') AND state IN ('CONFIRMED','PAPER_FILLED') GROUP BY asset_id", (mode,))}
        out = []
        for r in rows:
            d = dict(r)
            d["tokens_net"] = d["tokens"] - (sold.get(d["asset_id"]) or 0)
            m = self.c.execute("SELECT * FROM marks WHERE asset_id=?", (d["asset_id"],)).fetchone()
            d["mark_usd"] = m["price_usd"] if m else None
            d["marked_at"] = iso(m["marked_at"]) if m else None
            d["value_usd"] = d["tokens_net"] * d["mark_usd"] if m and m["price_usd"] is not None else None
            d["pnl_usd"] = (d["value_usd"] - d["cost"]) if d["value_usd"] is not None else None
            out.append(d)
        return out

    def set_mark(self, asset_id: str, price: float | None, source: str, error: str | None = None) -> None:
        self.c.execute("INSERT INTO marks(asset_id,price_usd,source,marked_at,error) VALUES(?,?,?,?,?) ON CONFLICT(asset_id) DO UPDATE SET "
                       "price_usd=COALESCE(excluded.price_usd, marks.price_usd), source=excluded.source, marked_at=excluded.marked_at, error=excluded.error",
                       (asset_id, price, source, now(), error))
