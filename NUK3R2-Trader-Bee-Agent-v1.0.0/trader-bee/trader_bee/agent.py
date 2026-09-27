"""The Trader Bee loop.

tick():
  0. reconcile  — intents left in SUBMITTING/UNKNOWN by a crash are checked on-chain, never re-sent
  1. ingest     — research.verdict (discovery buys), fib.zone.entered/exited (zone buys), hive.control
  2. process    — PLANNED / APPROVED / due retries run the gate pipeline, then execute
  3. housekeep  — wallet balances + position marks (throttled), Queen heartbeat

Two triggers, exactly as the beekeeper specified:
  * discovery_tier: a research verdict with discovery=true, gate PASS, rank BUY/WATCH
    -> ONE buy per asset, $10 high / $5 medium / $1 low confidence
  * zone_entry: Fib Bee says a gate-PASS, BUY/WATCH asset ENTERED the NUK3R2 buy zone
    -> $1, once per structure (+ cooldown)
"""
from __future__ import annotations

import json
import secrets
import time
from datetime import datetime, timezone

from hive import bus, marketdata, net, queen_client
from hive.paths import sub

from . import AGENT, config, executor, policy
from .store import OPEN_STATES, Store, now

CONSUMER = "trader_bee"
TYPES = {"research.verdict", "fib.zone.entered", "fib.zone.exited", "hive.control"}


def _new_id() -> str:
    return "TB-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(3)


def _parse_ts(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


class TraderBee:
    def __init__(self, store: Store | None = None, cfg: dict | None = None):
        self.store = store or Store()
        self._cfg = cfg

    @property
    def cfg(self) -> dict:
        return self._cfg or config.load()

    # ------------------------------------------------------------ controls
    def controls(self) -> dict:
        return self.store.get("controls", {"paused": False, "paused_reason": None, "consecutive_failures": 0})

    def set_paused(self, paused: bool, reason: str | None, by: str) -> dict:
        c = self.controls()
        c.update({"paused": paused, "paused_reason": reason if paused else None, "changed_by": by, "changed_at": now()})
        if not paused:
            c["consecutive_failures"] = 0
        self.store.put("controls", c)
        self.store.log("warn" if paused else "info", f"{'PAUSED' if paused else 'RESUMED'} by {by}" + (f": {reason}" if reason else ""))
        bus.publish("trader.paused" if paused else "trader.resumed", AGENT, {"by": by, "reason": reason})
        return c

    def _publish(self, etype: str, it: dict, reason: str | None = None):
        try:
            bus.publish(etype, AGENT, {"intent_id": it["id"], "asset_id": it["asset_id"], "symbol": it["symbol"],
                                       "strategy": it["strategy"], "tier": it.get("tier"), "usd": it.get("usd"),
                                       "mode": it.get("mode") or "paper", "state": it["state"], "reason": reason,
                                       "tx_hash": it.get("tx_hash"), "venue": it.get("venue")}, correlation_id=it["id"])
        except Exception as e:  # noqa: BLE001 — bus problems must not block trading decisions
            self.store.log("error", f"bus publish failed: {e}", it["id"])

    # ------------------------------------------------------------ ingest
    def ingest(self) -> dict:
        cfg = self.cfg
        counts = {"verdicts": 0, "zone_signals": 0, "intents_created": 0}
        for end, ev in bus.consume(CONSUMER, TYPES):
            try:
                t = ev["type"]
                p = ev["payload"]
                if t == "research.verdict":
                    counts["verdicts"] += 1
                    counts["intents_created"] += self._on_verdict(p, cfg, ev)
                elif t == "fib.zone.entered":
                    counts["zone_signals"] += 1
                    counts["intents_created"] += self._on_zone_entered(p, cfg, ev)
                elif t == "fib.zone.exited":
                    self._on_zone_exited(p)
                elif t == "hive.control" and p.get("target_agent") == AGENT:
                    self._on_control(p)
            except Exception as e:  # noqa: BLE001 — one bad event never stalls the queue
                self.store.log("error", f"event {ev.get('id')} failed: {e}")
                queen_client.event(AGENT, "handoff", False, target=ev.get("source", ""), correlation_id=ev.get("id", ""), message=str(e))
            bus.ack(CONSUMER, end)
        return counts

    def _on_verdict(self, v: dict, cfg: dict, ev: dict) -> int:
        conf = policy.resolve_confidence(v, cfg["confidence_bands"])
        if not self.store.upsert_asset(v, conf):
            return 0  # older verdict arriving late
        if v["rank"] not in ("BUY", "WATCH") or v["gate"]["result"] != "PASS":
            self._expire_open(v["asset_id"], f"research downgraded to {v['rank']}/{v['gate']['result']}")
        s = cfg["strategies"]["discovery_tier"]
        if not (s["enabled"] and (v.get("discovery") or not s["require_discovery_flag"])):
            return 0
        if v["gate"]["result"] != "PASS" or v["rank"] not in s["eligible_ranks"]:
            return 0
        if v["chain"] not in cfg["chains"]:
            self.store.log("info", f"{v['symbol']} discovery on {v['chain']}: not a Trader Bee chain, skipped")
            return 0
        age_h = (now() - _parse_ts(v["researched_at"])) / 3600
        tier, usd = policy.discovery_size(v, cfg)
        row = {"id": _new_id(), "idem_key": f"discovery:{v['asset_id']}", "asset_id": v["asset_id"], "chain": v["chain"],
               "contract": v["contract"], "symbol": v["symbol"], "strategy": "discovery_tier", "tier": tier, "usd": usd,
               "mode": config.effective_mode(cfg),
               "trigger_json": {"event_id": ev["id"], "researched_at": v["researched_at"], "confidence": tier,
                                "scores": v.get("scores"), "snapshot_id": v.get("snapshot_id")}}
        if age_h > s["max_verdict_age_hours"]:
            row.update(state="REJECTED", reason=f"verdict is {age_h:.0f}h old (> {s['max_verdict_age_hours']}h)")
        it = self.store.create_intent(row)
        if it:
            self.store.log("info", f"intent {it['id']}: discovery {tier} ${usd:g} {it['symbol']}", it["id"])
            self._publish("trader.intent.created", it)
            return 1
        return 0

    def _on_zone_entered(self, p: dict, cfg: dict, ev: dict) -> int:
        s = cfg["strategies"]["zone_entry"]
        if not s["enabled"] or not p.get("in_buy_zone"):
            return 0
        aid = p["asset_id"]
        mode = config.effective_mode(cfg)
        row = {"id": _new_id(), "idem_key": f"zone:{aid}:{p['structure_id']}", "asset_id": aid, "chain": p["chain"],
               "contract": p["contract"], "symbol": p["symbol"], "strategy": "zone_entry", "tier": "zone", "usd": float(s["size_usd"]),
               "mode": mode,
               "trigger_json": {"event_id": ev["id"], "event_ts": ev["ts"], "structure_id": p["structure_id"], "zone": p["zone"],
                                "percent": p["percent"], "price": p["price"], "anchors": p.get("anchors") or {},
                                "study_mode": p.get("study_mode")}}
        age_m = (now() - _parse_ts(ev["ts"])) / 60
        last = self.store.last_buy_at(aid, "zone_entry", mode)
        if age_m > s["max_signal_age_minutes"]:
            row.update(state="REJECTED", reason=f"zone signal is {age_m:.0f} min old (> {s['max_signal_age_minutes']}) — processed late, not chased")
        elif last and now() - last < s["cooldown_hours"] * 3600:
            row.update(state="REJECTED", reason=f"zone buy cooldown: last zone buy {(now() - last) / 3600:.1f}h ago (< {s['cooldown_hours']}h)")
        it = self.store.create_intent(row)
        if it:
            self.store.log("info", f"intent {it['id']}: zone entry $1 {it['symbol']} ({p['zone']} {p['percent']:.1f}%)", it["id"])
            self._publish("trader.intent.created", it)
            return 1
        return 0

    def _on_zone_exited(self, p: dict):
        for it in self.store.intents(("PLANNED", "NEEDS_APPROVAL", "APPROVED", "REJECTED"), strategy="zone_entry"):
            if it["asset_id"] == p["asset_id"] and it["trigger"].get("structure_id") == p["structure_id"]:
                if it["state"] != "REJECTED" or it["retryable"]:
                    self.store.transition(it["id"], (it["state"],), state="EXPIRED", reason=f"left the buy zone ({p['zone']})", retryable=0)

    def _expire_open(self, asset_id: str, reason: str):
        for it in self.store.intents(("PLANNED", "NEEDS_APPROVAL", "APPROVED", "REJECTED")):
            if it["asset_id"] == asset_id and it["strategy"] != "take_profit" and (it["state"] != "REJECTED" or it["retryable"]):
                self.store.transition(it["id"], (it["state"],), state="EXPIRED", reason=reason, retryable=0)

    def _on_control(self, p: dict):
        cmd, by = p["command"], p.get("requested_by", "hive")
        if cmd == "pause":
            self.set_paused(True, p.get("reason") or "hive.control pause", by)
        elif cmd == "resume":
            self.set_paused(False, None, by)
        elif cmd == "disarm":
            disarm(by)
            self.store.log("warn", f"DISARMED by {by}: {p.get('reason') or ''}")

    # ------------------------------------------------------------ process
    def due(self) -> list[dict]:
        cfg = self.cfg
        spacing = cfg["safety"]["retry_spacing_minutes"] * 60
        out = self.store.intents(("PLANNED", "APPROVED"), limit=500)
        for it in self.store.intents(("REJECTED",), limit=500):
            if not it["retryable"] or (it["last_attempt_at"] and now() - it["last_attempt_at"] < spacing):
                continue
            if it["strategy"] == "discovery_tier":
                age_h = (now() - _parse_ts(it["trigger"]["researched_at"])) / 3600
                if age_h > cfg["strategies"]["discovery_tier"]["max_verdict_age_hours"]:
                    self.store.transition(it["id"], ("REJECTED",), state="EXPIRED", reason=f"verdict aged out while waiting: {it['reason']}", retryable=0)
                    continue
            out.append(it)
        return sorted(out, key=lambda x: x["created_at"])

    def process(self) -> dict:
        cfg = self.cfg
        mode = config.effective_mode(cfg)
        res = {"evaluated": 0, "executed": 0, "rejected": 0, "approval": 0, "failed": 0}
        for it in self.due():
            if it["strategy"] == "take_profit":
                continue
            approved = it["state"] == "APPROVED"
            asset = self.store.asset(it["asset_id"])
            prev_state, prev_reason = it["state"], it.get("reason")
            try:
                dec = policy.evaluate(it, asset, cfg, self.store, mode, approved=approved, controls=self.controls())
            except Exception as e:  # noqa: BLE001 — a gate crash is a reject, never a pass
                dec = policy.Decision().reject(f"gate error: {type(e).__name__}: {e}", retryable=True)
            res["evaluated"] += 1
            common = {"mode": mode, "gates_json": {"checks": dec.checks, "notes": dec.notes, "reasons": dec.reasons},
                      "quote_json": dec.quote, "attempts": (it["attempts"] or 0) + 1, "last_attempt_at": now()}
            if dec.outcome == "reject":
                reason = "; ".join(dec.reasons)
                self.store.update_intent(it["id"], state="REJECTED", reason=reason, retryable=1 if dec.retryable else 0, **common)
                res["rejected"] += 1
                if prev_state != "REJECTED" or prev_reason != reason:
                    self.store.log("info", f"{it['symbol']} {it['strategy']} rejected: {reason}", it["id"])
                    self._publish("trader.intent.rejected", {**it, "state": "REJECTED", "mode": mode}, reason)
                continue
            if dec.outcome == "approval":
                reason = "; ".join(dec.reasons)
                self.store.update_intent(it["id"], state="NEEDS_APPROVAL", reason=reason, retryable=0, **common)
                res["approval"] += 1
                self.store.log("warn", f"{it['symbol']} needs beekeeper approval: {reason}", it["id"])
                self._publish("trader.approval.requested", {**it, "state": "NEEDS_APPROVAL", "mode": mode}, reason)
                continue
            self.store.update_intent(it["id"], state="READY", reason=None, retryable=0, **common)
            ok = self.execute(self.store.intent(it["id"]), dec, mode)
            res["executed" if ok else "failed"] += 1
        return res

    def execute(self, it: dict, dec: policy.Decision, mode: str) -> bool:
        cfg = self.cfg
        if mode == "paper":
            q = dec.quote
            if not self.store.transition(it["id"], ("READY",), state="PAPER_FILLED", venue=q.get("winner"), token_amount=q.get("tokens_out"),
                                         stable_spent=it["usd"], fill_price_usd=q.get("effective_price"),
                                         result_json={"paper": True, "quote": q}):
                return False
            it = self.store.intent(it["id"])
            self.store.log("trade", f"PAPER BUY ${it['usd']:g} {it['symbol']} ≈{q.get('tokens_out'):.6g} via {q.get('winner')}", it["id"])
            self._publish("trader.trade.executed", it)
            self.propose_take_profit(it)
            return True

        # re-check arming + kill switch at the last moment: a DISARM/Pause pressed mid-tick wins
        if config.effective_mode(cfg) != "live" or self.controls().get("paused"):
            self.store.transition(it["id"], ("READY",), state="REJECTED", retryable=1, reason="disarmed or paused just before sending — nothing sent")
            return False
        # live: persist SUBMITTING before anything can hit the chain
        if not self.store.transition(it["id"], ("READY",), state="SUBMITTING"):
            return False
        payload = {"intent_id": it["id"], "chain": it["chain"], "token": it["contract"], "usd": it["usd"],
                   "slippagePct": policy.clamp_slippage(cfg), "approvalMode": cfg["execution"]["approval_mode"],
                   "allowedSpenders": cfg["execution"]["allowed_spenders"].get(it["chain"], []),
                   "minGasNative": cfg["execution"]["min_gas_native"].get(it["chain"], 0),
                   "receiptTimeoutS": cfg["execution"]["receipt_timeout_s"], "retryOnce": cfg["execution"]["retry_once_on_revert"],
                   "maxImpactPct": cfg["gates"]["max_price_impact_pct"], "midPriceUsd": dec.quote.get("mid")}
        try:
            r = executor.call("buy", payload, timeout=cfg["execution"]["receipt_timeout_s"] * 2 + 120)
        except executor.ExecutorError as e:
            self.store.update_intent(it["id"], state="UNKNOWN", reason=f"executor error mid-trade: {e} — reconciling against the chain")
            self.store.log("error", f"{it['symbol']} executor error: {e}", it["id"])
            self._failure(str(e))
            return False
        if r.get("ok"):
            self.store.update_intent(it["id"], state="CONFIRMED", tx_hash=r.get("txHash"), venue=r.get("venue"),
                                     token_amount=r.get("tokensReceived"), stable_spent=r.get("stableSpent") or it["usd"],
                                     fill_price_usd=(r.get("stableSpent") or it["usd"]) / r["tokensReceived"] if r.get("tokensReceived") else None,
                                     result_json=r)
            c = self.controls()
            c["consecutive_failures"] = 0
            self.store.put("controls", c)
            it = self.store.intent(it["id"])
            self.store.log("trade", f"LIVE BUY ${it['stable_spent']:.2f} {it['symbol']} → {it['token_amount']} via {it['venue']} tx {it['tx_hash']}", it["id"])
            self._publish("trader.trade.executed", it)
            queen_client.event(AGENT, "trade", True, correlation_id=it["id"], message=f"{it['symbol']} ${it['usd']}")
            self.propose_take_profit(it)
            return True
        if not r.get("sent"):
            # nothing reached the chain: no money moved, safe to retry later
            self.store.update_intent(it["id"], state="REJECTED", retryable=1, reason=f"not sent: {r.get('error')}", result_json=r)
            self.store.log("warn", f"{it['symbol']} buy not sent: {r.get('error')}", it["id"])
            return False
        if r.get("stage") in ("receipt", "unknown"):
            # broadcast happened but the outcome is not known yet: never FAILED, never retried — reconciled
            self.store.update_intent(it["id"], state="UNKNOWN", reason=r.get("error"), tx_hash=r.get("txHash"), result_json=r)
            self.store.log("warn", f"{it['symbol']} outcome unknown after broadcast ({r.get('txHash')}) — reconciling", it["id"])
            return False
        self.store.update_intent(it["id"], state="FAILED", reason=r.get("error") or "reverted", tx_hash=r.get("txHash"), result_json=r)
        it = self.store.intent(it["id"])
        self.store.log("error", f"{it['symbol']} LIVE BUY FAILED: {it['reason']}", it["id"])
        self._publish("trader.trade.failed", it, it["reason"])
        self._failure(it["reason"])
        return False

    def _failure(self, why: str):
        c = self.controls()
        c["consecutive_failures"] = c.get("consecutive_failures", 0) + 1
        self.store.put("controls", c)
        queen_client.event(AGENT, "trade", False, message=why)
        lim = self.cfg["safety"]["circuit_breaker_consecutive_failures"]
        if c["consecutive_failures"] >= lim and not c.get("paused"):
            self.set_paused(True, f"circuit breaker: {c['consecutive_failures']} consecutive execution failures (last: {why[:120]})", "trader_bee")

    # ------------------------------------------------------------ take-profit proposals
    def _anchors_for(self, it: dict) -> dict | None:
        a = (it.get("trigger") or {}).get("anchors")
        if a and a.get("bottom") and a.get("body_high"):
            return a
        try:
            st = json.loads((sub("fib_agent") / "state.json").read_text(encoding="utf-8"))
            s = st["assets"].get(it["asset_id"]) or {}
            if s.get("status") == "ACTIVE" and s.get("bottom") and s.get("body_high"):
                return {"bottom": s["bottom"], "body_high": s["body_high"], "wick_high": s.get("wick_high")}
        except Exception:
            return None
        return None

    def propose_take_profit(self, parent: dict) -> dict | None:
        tp = self.cfg["take_profit"]
        if not tp.get("propose") or not parent.get("token_amount"):
            return None
        a = self._anchors_for(parent)
        if not a:
            self.store.log("info", f"{parent['symbol']}: no ACTIVE Fib structure — no take-profit proposal", parent["id"])
            return None
        b, top = float(a["bottom"]), float(a["body_high"])
        price = b + (top - b) * (1 - tp["level_percent"] / 100.0)
        if parent.get("fill_price_usd") and price <= parent["fill_price_usd"]:
            return None
        qty = float(parent["token_amount"]) * tp["fraction_of_position"]
        it = self.store.create_intent({
            "id": _new_id(), "idem_key": f"tp:{parent['id']}", "asset_id": parent["asset_id"], "chain": parent["chain"],
            "contract": parent["contract"], "symbol": parent["symbol"], "strategy": "take_profit", "tier": "tp",
            "usd": round(qty * price, 4), "mode": parent["mode"], "state": "NEEDS_APPROVAL", "parent_id": parent["id"],
            "reason": f"proposed: sell {tp['fraction_of_position']:.0%} at the NSZ edge (${price:.8g}, {tp['level_percent']}% level)",
            "trigger_json": {"limit_price_usd": price, "qty": qty, "expiry_days": tp["expiry_days"], "anchors": a}})
        if it:
            self._publish("trader.approval.requested", it, it["reason"])
        return it

    # ------------------------------------------------------------ beekeeper actions (per-trade human confirmation)
    def approve(self, intent_id: str, by: str = "beekeeper") -> dict:
        it = self.store.intent(intent_id)
        if not it or it["state"] != "NEEDS_APPROVAL":
            raise ValueError(f"intent {intent_id} is not awaiting approval")
        if it["strategy"] != "take_profit":
            self.store.transition(intent_id, ("NEEDS_APPROVAL",), state="APPROVED", approved_by=by, approved_at=now())
            self.store.log("info", f"{it['symbol']} buy APPROVED by {by} (hard gates re-run before execution)", intent_id)
            return self.store.intent(intent_id)
        mode = config.effective_mode(self.cfg)
        tr = it["trigger"]
        if mode == "paper" or it["mode"] == "paper":
            self.store.transition(intent_id, ("NEEDS_APPROVAL",), state="PAPER_PLACED", approved_by=by, approved_at=now(), mode="paper")
            self.store.log("trade", f"PAPER TAKE-PROFIT placed: {tr['qty']:.6g} {it['symbol']} @ ${tr['limit_price_usd']:.8g}", intent_id)
            return self.store.intent(intent_id)
        if not self.store.transition(intent_id, ("NEEDS_APPROVAL",), state="SUBMITTING", approved_by=by, approved_at=now()):
            raise ValueError("intent changed state")
        r = executor.call("limit-sell", {"intent_id": intent_id, "chain": it["chain"], "token": it["contract"], "qty": f"{tr['qty']:.12f}",
                                         "limitPriceUsd": tr["limit_price_usd"], "expiryDays": tr["expiry_days"],
                                         "allowedSpenders": self.cfg["execution"]["allowed_spenders"].get(it["chain"], [])}, timeout=180)
        if r.get("ok"):
            self.store.update_intent(intent_id, state="PLACED", tx_hash=r.get("orderHash"), venue="1inch-orderbook", result_json=r)
            self.store.log("trade", f"TAKE-PROFIT LIVE on 1inch orderbook: {it['symbol']} order {r.get('orderHash')}", intent_id)
        else:
            self.store.update_intent(intent_id, state="FAILED", reason=r.get("error"), result_json=r)
        return self.store.intent(intent_id)

    def decline(self, intent_id: str, by: str = "beekeeper") -> dict:
        if not self.store.transition(intent_id, ("NEEDS_APPROVAL",), state="DECLINED", approved_by=by, approved_at=now()):
            raise ValueError(f"intent {intent_id} is not awaiting approval")
        self.store.log("info", f"intent {intent_id} DECLINED by {by}", intent_id)
        return self.store.intent(intent_id)

    # ------------------------------------------------------------ reconcile + housekeeping
    def reconcile(self) -> int:
        n = 0
        journal = {}
        try:
            for line in (sub("trader_bee") / "exec-journal.jsonl").read_text(encoding="utf-8").splitlines():
                j = json.loads(line)
                journal.setdefault(j["intent_id"], []).append(j)
        except FileNotFoundError:
            pass
        for it in self.store.intents(("SUBMITTING", "UNKNOWN")):
            if it["state"] == "SUBMITTING" and now() - it["updated_at"] < 900:
                continue  # possibly still in flight in another process
            sent = [j for j in journal.get(it["id"], []) if j.get("stage") == "sent" and j.get("kind") != "approve"]
            if not sent:
                self.store.update_intent(it["id"], state="FAILED", reason="reconcile: no broadcast recorded in the executor journal — nothing was sent")
                n += 1
                continue
            txh = sent[-1]["txHash"]
            try:
                rc = executor.call("receipt", {"chain": it["chain"], "txHash": txh, "token": it["contract"] if it["strategy"] != "manual_sell" else None}, timeout=60)
            except executor.ExecutorError as e:
                self.store.log("warn", f"reconcile {it['id']}: receipt lookup failed ({e}); will retry", it["id"])
                continue
            if rc.get("status") == 1:
                amt = rc.get("tokensReceived")
                self.store.update_intent(it["id"], state="CONFIRMED", tx_hash=txh, token_amount=amt, stable_spent=it["usd"],
                                         fill_price_usd=(it["usd"] / amt) if amt else None,
                                         reason="reconciled from the chain receipt" + ("" if amt else " (token amount unknown — check the explorer)"))
            elif rc.get("status") == 0:
                self.store.update_intent(it["id"], state="FAILED", tx_hash=txh, reason="reconciled: transaction reverted")
            else:
                self.store.update_intent(it["id"], state="UNKNOWN", tx_hash=txh, reason="reconcile: tx still pending / not found")
                continue
            n += 1
        return n

    def housekeep(self, force: bool = False) -> None:
        cfg = self.cfg
        lp = cfg["loop"]
        t = now()
        if config.KEY_FILE.exists() and (force or t - self.store.get("balances_at", 0) > lp["balances_every_seconds"]):
            bals = {}
            for chain in cfg["chains"]:
                held = sorted({p["contract"] for p in self.store.positions("live") if p["chain"] == chain})
                try:
                    from hive import chains as ch
                    r = executor.call("balances", {"chain": chain, "tokens": [ch.get(chain)["stable"]["contract"], *held]}, timeout=60)
                    bals[chain] = r
                    if r.get("address"):
                        self.store.put("wallet_address", r["address"])
                except executor.ExecutorError as e:
                    bals[chain] = {"ok": False, "error": str(e)}
            self.store.put("balances", bals)
            self.store.put("balances_at", t)
        if force or t - self.store.get("marks_at", 0) > lp["marks_every_seconds"]:
            seen = set()
            for mode in ("live", "paper"):
                for p in self.store.positions(mode):
                    if p["asset_id"] in seen:
                        continue
                    seen.add(p["asset_id"])
                    try:
                        c = marketdata.dexscreener_token(p["chain"], p["contract"], agent=AGENT)
                        self.store.set_mark(p["asset_id"], c["price_usd"], "dexscreener")
                    except net.NetError as e:
                        self.store.set_mark(p["asset_id"], None, "dexscreener", str(e)[:200])
            self.store.put("marks_at", t)

    def tick(self) -> dict:
        t0 = time.time()
        summary = {"at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(), "mode": config.effective_mode(self.cfg)}
        try:
            summary["reconciled"] = self.reconcile()
            summary.update(self.ingest())
            summary.update(self.process())
            self.housekeep()
            queen_client.heartbeat(AGENT, "healthy")
        except Exception as e:  # noqa: BLE001
            summary["error"] = f"{type(e).__name__}: {e}"
            self.store.log("error", f"tick failed: {summary['error']}")
            queen_client.heartbeat(AGENT, "degraded", summary["error"])
        summary["ms"] = round((time.time() - t0) * 1000)
        self.store.put("last_tick", summary)
        return summary

    # ------------------------------------------------------------ status for CLI / UI
    def status(self) -> dict:
        cfg = self.cfg
        mode = config.effective_mode(cfg)
        t = now()
        day, n_day = self.store.spent(mode, t - 86400)
        week, _ = self.store.spent(mode, t - 7 * 86400)
        counts = {r["state"]: r["n"] for r in self.store.c.execute("SELECT state, COUNT(*) n FROM intents GROUP BY state")}
        return {
            "agent": AGENT, "version": "1.0.0", "config_mode": cfg["mode"], "effective_mode": mode, "armed": config.armed(),
            "key_present": config.KEY_FILE.exists(), "wallet_address": self.store.get("wallet_address"),
            "controls": self.controls(), "chains": cfg["chains"],
            "sizes": {"discovery": cfg["strategies"]["discovery_tier"]["sizes_usd"], "zone_entry": cfg["strategies"]["zone_entry"]["size_usd"],
                      "discovery_enabled": cfg["strategies"]["discovery_tier"]["enabled"], "zone_enabled": cfg["strategies"]["zone_entry"]["enabled"]},
            "budget": {**cfg["budget"], "used_24h": round(day, 2), "used_7d": round(week, 2), "buys_24h": n_day},
            "balances": self.store.get("balances", {}), "balances_at": self.store.get("balances_at"),
            "counts": counts,
            "approvals": self.store.intents(("NEEDS_APPROVAL",), limit=50),
            "recent": self.store.intents(limit=60),
            "positions": {"live": self.store.positions("live"), "paper": self.store.positions("paper")},
            "log": self.store.recent_log(60), "last_tick": self.store.get("last_tick"),
        }


def disarm(by: str = "beekeeper") -> bool:
    if config.ARM_FILE.exists():
        config.ARM_FILE.unlink()
        return True
    return False
