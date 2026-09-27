import json
from datetime import datetime, timedelta, timezone

from conftest import addr, verdict, zone_event

from hive import bus

T1, T2, T3, T4 = addr("1"), addr("2"), addr("3"), addr("4")


def pub_v(v):
    return bus.publish("research.verdict", "research_agent", v)


def pub_z(z):
    return bus.publish("fib.zone.entered", "fib_agent", z)


def intents(w, **kw):
    return w.bee.store.intents(**kw)


# ------------------------------------------------------------------ sizing: $10 / $5 / $1
def test_discovery_tiers_paper(world):
    for c, conf in ((T1, "high"), (T2, "medium"), (T3, "low")):
        world.m.add(c)
        pub_v(verdict(c, confidence=conf))
    s = world.bee.tick()
    assert s["mode"] == "paper" and s["intents_created"] == 3 and s["executed"] == 3
    got = {i["contract"]: (i["state"], i["usd"], i["tier"]) for i in intents(world)}
    assert got[T1] == ("PAPER_FILLED", 10.0, "high")
    assert got[T2] == ("PAPER_FILLED", 5.0, "medium")
    assert got[T3] == ("PAPER_FILLED", 1.0, "low")


def test_confidence_derived_from_scores_when_absent(world):
    world.m.add(T1)
    world.m.add(T2)
    world.m.add(T3)
    pub_v(verdict(T1, confidence=None, scores={"core_quality": 46, "timing": 18}))
    pub_v(verdict(T2, confidence=None, scores={"core_quality": 41, "timing": 14}))
    pub_v(verdict(T3, confidence=None, scores={"core_quality": 20, "timing": 5}))
    world.bee.tick()
    got = {i["contract"]: i["usd"] for i in intents(world)}
    assert got == {T1: 10.0, T2: 5.0, T3: 1.0}


def test_discovery_once_per_asset(world):
    world.m.add(T1)
    pub_v(verdict(T1))
    world.bee.tick()
    later = (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat().replace("+00:00", "Z")
    pub_v(verdict(T1, researched_at=later))
    world.bee.tick()
    assert len(intents(world)) == 1


def test_non_discovery_and_avoid_do_not_tier_buy(world):
    world.m.add(T1)
    world.m.add(T2)
    pub_v(verdict(T1, discovery=False))
    pub_v(verdict(T2, rank="AVOID"))
    world.bee.tick()
    assert intents(world) == []


def test_non_trader_chain_ignored(world):
    v = verdict(T1, chain="ethereum")
    pub_v(v)
    world.bee.tick()
    assert intents(world) == []


# ------------------------------------------------------------------ $1 zone entry
def test_zone_entry_buys_one_dollar_once_per_structure(world):
    world.m.add(T1)
    pub_v(verdict(T1, rank="WATCH", discovery=False))
    pub_z(zone_event(T1))
    world.bee.tick()
    pub_z(zone_event(T1))  # replayed / duplicate signal
    world.bee.tick()
    zs = intents(world, strategy="zone_entry")
    assert len(zs) == 1 and zs[0]["usd"] == 1.0 and zs[0]["state"] == "PAPER_FILLED"


def test_zone_entry_requires_gate_pass_and_rank(world):
    world.m.add(T1)
    world.m.add(T2)
    pub_v(verdict(T1, gate="FAIL", discovery=False))
    pub_v(verdict(T2, rank="AVOID", discovery=False))
    pub_z(zone_event(T1))
    pub_z(zone_event(T2, structure="FIB-2"))
    world.bee.tick()
    states = {i["contract"]: (i["state"], i["reason"]) for i in intents(world)}
    assert states[T1][0] == "REJECTED" and "gate FAIL" in states[T1][1]
    assert states[T2][0] == "REJECTED" and "rank AVOID" in states[T2][1]


def test_zone_live_price_recheck(world):
    world.m.add(T1, price=0.02)  # event said 0.01 but price already ran above the zone
    pub_v(verdict(T1, discovery=False))
    pub_z(zone_event(T1))
    world.bee.tick()
    it = intents(world)[0]
    assert it["state"] == "REJECTED" and "back above the buy zone" in it["reason"] and it["retryable"] == 1


def test_zone_new_atl_invalidates(world):
    world.m.add(T1, price=0.005)
    pub_v(verdict(T1, discovery=False))
    pub_z(zone_event(T1))
    world.bee.tick()
    it = intents(world)[0]
    assert it["state"] == "REJECTED" and "new ATL" in it["reason"] and it["retryable"] == 0


def test_zone_exit_expires_waiting_intent(world):
    world.m.add(T1, price=0.02)
    pub_v(verdict(T1, discovery=False))
    pub_z(zone_event(T1))
    world.bee.tick()
    bus.publish("fib.zone.exited", "fib_agent", {**zone_event(T1), "in_buy_zone": False, "zone": "NUK3"})
    world.bee.tick()
    assert intents(world)[0]["state"] == "EXPIRED"


def test_stale_zone_signal_not_chased(world, monkeypatch):
    world.m.add(T1)
    pub_v(verdict(T1, discovery=False))
    ev = pub_z(zone_event(T1))
    from trader_bee import agent
    real = agent.now
    monkeypatch.setattr(agent, "now", lambda: real() + 3 * 3600)
    world.bee.tick()
    it = intents(world)[0]
    assert it["state"] == "REJECTED" and "not chased" in it["reason"]


# ------------------------------------------------------------------ hard gates
def test_identity_needs_two_sources(world):
    world.m.add(T1)
    pub_v(verdict(T1, sources=("dexscreener",)))
    world.bee.tick()
    it = intents(world)[0]
    assert it["state"] == "REJECTED" and "independent sources" in it["reason"]


def test_liquidity_floor_and_honeypot_and_tax(world):
    world.m.add(T1, liq=10_000)
    world.m.add(T2, goplus="honeypot")
    world.m.add(T3, goplus="taxed")
    for c in (T1, T2, T3):
        pub_v(verdict(c))
    world.bee.tick()
    r = {i["contract"]: i["reason"] for i in intents(world)}
    assert "hard floor" in r[T1]
    assert "is_honeypot" in r[T2]
    assert "tax" in r[T3]


def test_low_security_score_rejected(world):
    world.m.add(T1)
    pub_v(verdict(T1, security=60))
    world.bee.tick()
    assert "security score 60" in intents(world)[0]["reason"]


def test_price_impact_and_roundtrip(world):
    world.m.add(T1)
    world.fx.impact = 0.08
    pub_v(verdict(T1))
    world.bee.tick()
    assert "price impact" in intents(world)[0]["reason"]
    world.m.add(T2)
    world.fx.impact = 0.005
    world.fx.roundtrip = 0.5
    pub_v(verdict(T2))
    world.bee.tick()
    r = {i["contract"]: i["reason"] for i in intents(world)}
    assert "round-trip loss" in r[T2]


def test_source_down_is_reject_not_pass(world):
    world.m.add(T1)
    world.m.down = True
    pub_v(verdict(T1))
    world.bee.tick()
    it = intents(world)[0]
    assert it["state"] == "REJECTED" and "source broken" in it["reason"] and it["retryable"] == 1


def test_registry_conflict_rejected(world, monkeypatch):
    from trader_bee import policy
    monkeypatch.setattr(policy, "_module_registry", lambda: {"BEE": {"chainId": 8453, "contract": addr("9"), "symbol": "BEE"}})
    world.m.add(T1)
    pub_v(verdict(T1))
    world.bee.tick()
    assert "conflicts with the terminal registry" in intents(world)[0]["reason"]


# ------------------------------------------------------------------ soft gates -> approval
def test_soft_gate_parks_for_approval_then_executes(world):
    world.m.add(T1, liq=30_000)  # between hard 25k and soft 50k
    pub_v(verdict(T1))
    world.bee.tick()
    it = intents(world)[0]
    assert it["state"] == "NEEDS_APPROVAL" and "thin liquidity" in it["reason"]
    world.bee.approve(it["id"])
    world.bee.tick()
    it = world.bee.store.intent(it["id"])
    assert it["state"] == "PAPER_FILLED"
    assert any("approved by beekeeper" in n for n in it["gates"]["notes"])


def test_security_unverifiable_needs_approval(world):
    world.m.add(T1, goplus=None)
    pub_v(verdict(T1, security=None))
    world.bee.tick()
    it = intents(world)[0]
    assert it["state"] == "NEEDS_APPROVAL" and "unverifiable" in it["reason"]


def test_decline(world):
    world.m.add(T1, age_h=2)
    pub_v(verdict(T1))
    world.bee.tick()
    it = intents(world)[0]
    assert it["state"] == "NEEDS_APPROVAL" and "old" in it["reason"]
    assert world.bee.decline(it["id"])["state"] == "DECLINED"


def test_unexplained_clone_needs_approval_known_decoy_ok(world):
    world.m.add(T1, liq=100_000)
    world.m.tokens[T1.lower()]["clones"] = [{"contract": addr("7"), "liq": 900_000}]
    pub_v(verdict(T1))
    world.bee.tick()
    assert "same-ticker" in intents(world)[0]["reason"]
    world.m.add(T2, liq=100_000, symbol="ANT")
    world.m.tokens[T2.lower()]["clones"] = [{"contract": addr("8"), "liq": 900_000}]
    v = verdict(T2, symbol="ANT")
    v["identity"]["decoys"] = [addr("8")]
    pub_v(v)
    world.bee.tick()
    assert world.bee.store.intent_by_key(f"discovery:base:{T2}")["state"] == "PAPER_FILLED"


# ------------------------------------------------------------------ budget + kill switch
def test_daily_budget(world):
    world.cfg["budget"]["daily_usd"] = 12
    for c in (T1, T2):
        world.m.add(c)
        pub_v(verdict(c, confidence="high"))
    world.bee.tick()
    st = sorted((i["state"], i["reason"] or "") for i in intents(world))
    assert st[0][0] == "PAPER_FILLED" and st[1][0] == "REJECTED" and "daily budget" in st[1][1]


def test_per_asset_exposure(world):
    world.cfg["budget"]["max_exposure_per_asset_usd"] = 10
    world.m.add(T1)
    pub_v(verdict(T1, confidence="high"))
    pub_z(zone_event(T1))
    world.bee.tick()
    z = intents(world, strategy="zone_entry")[0]
    assert z["state"] == "REJECTED" and "per-asset exposure" in z["reason"]


def test_pause_then_resume(world):
    world.bee.set_paused(True, "test", "beekeeper")
    world.m.add(T1)
    pub_v(verdict(T1))
    world.bee.tick()
    assert intents(world)[0]["state"] == "REJECTED"
    world.bee.set_paused(False, None, "beekeeper")
    world.bee.store.update_intent(intents(world)[0]["id"], last_attempt_at=0)
    world.bee.tick()
    assert intents(world)[0]["state"] == "PAPER_FILLED"


def test_hive_control_pause(world):
    bus.publish("hive.control", "queen", {"target_agent": "trader_bee", "command": "pause", "requested_by": "queen", "reason": "provider outage"})
    world.bee.tick()
    assert world.bee.controls()["paused"] is True


def test_research_downgrade_expires_waiting(world):
    world.m.add(T1, liq=30_000)
    pub_v(verdict(T1))
    world.bee.tick()
    assert intents(world)[0]["state"] == "NEEDS_APPROVAL"
    later = (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat().replace("+00:00", "Z")
    pub_v(verdict(T1, rank="AVOID", researched_at=later))
    world.bee.tick()
    assert intents(world)[0]["state"] == "EXPIRED"


# ------------------------------------------------------------------ live mode
def test_live_requires_arming(world):
    world.cfg["mode"] = "live"  # config says live, but nobody armed it
    world.m.add(T1)
    pub_v(verdict(T1))
    world.bee.tick()
    assert intents(world)[0]["mode"] == "paper" and not any(c[0] == "buy" for c in world.fx.calls)


def test_live_buy_confirmed_and_budgeted(world):
    world.arm()
    world.m.add(T1)
    pub_v(verdict(T1, confidence="medium"))
    world.bee.tick()
    it = intents(world)[0]
    assert it["mode"] == "live" and it["state"] == "CONFIRMED" and it["tx_hash"].startswith("0x")
    assert it["token_amount"] == 500.0
    assert world.bee.store.spent("live", 0) == (5.0, 1)
    buy = [p for c, p in world.fx.calls if c == "buy"][0]
    assert buy["usd"] == 5.0 and buy["allowedSpenders"] and buy["intent_id"] == it["id"]


def test_live_insufficient_funds_retryable(world):
    world.arm()
    world.fx.stable = 0.5
    world.m.add(T1)
    pub_v(verdict(T1))
    world.bee.tick()
    it = intents(world)[0]
    assert it["state"] == "REJECTED" and "insufficient USDC" in it["reason"] and it["retryable"] == 1


def test_circuit_breaker(world):
    world.arm()
    world.fx.buy_result = {"ok": False, "sent": True, "stage": "revert", "txHash": "0xbad", "error": "TX REVERTED"}
    for c in (T1, T2, T3, T4):
        world.m.add(c)
        pub_v(verdict(c, confidence="low"))
    world.bee.tick()
    states = [i["state"] for i in intents(world)]
    assert states.count("FAILED") == 3
    assert world.bee.controls()["paused"] is True and "circuit breaker" in world.bee.controls()["paused_reason"]


def test_not_sent_is_retryable_not_failed(world):
    world.arm()
    world.fx.buy_result = {"ok": False, "sent": False, "stage": "route", "error": "spender not pinned"}
    world.m.add(T1)
    pub_v(verdict(T1))
    world.bee.tick()
    it = intents(world)[0]
    assert it["state"] == "REJECTED" and it["retryable"] == 1


def test_unknown_after_broadcast_reconciled(world):
    world.arm()
    world.fx.buy_result = {"ok": False, "sent": True, "stage": "unknown", "txHash": "0xabc", "error": "rpc died"}
    world.m.add(T1)
    pub_v(verdict(T1))
    world.bee.tick()
    it = intents(world)[0]
    assert it["state"] == "UNKNOWN"
    from hive.paths import sub
    (sub("trader_bee") / "exec-journal.jsonl").write_text(json.dumps({"intent_id": it["id"], "kind": "swap", "stage": "sent", "txHash": "0xabc"}) + "\n")
    world.bee.tick()
    it = world.bee.store.intent(it["id"])
    assert it["state"] == "CONFIRMED" and it["token_amount"] == 123.0
    # never re-sent
    assert sum(1 for c, _ in world.fx.calls if c == "buy") == 1


def test_crash_in_submitting_without_journal_marked_failed(world, monkeypatch):
    world.arm()
    world.m.add(T1)
    from trader_bee.store import now as real_now
    it = world.bee.store.create_intent({"id": "TB-x", "idem_key": "k", "asset_id": f"base:{T1.lower()}", "chain": "base", "contract": T1,
                                        "symbol": "BEE", "strategy": "discovery_tier", "usd": 1.0, "mode": "live", "state": "SUBMITTING"})
    world.bee.store.c.execute("UPDATE intents SET updated_at=? WHERE id='TB-x'", (real_now() - 3600,))
    world.bee.tick()
    assert world.bee.store.intent("TB-x")["state"] == "FAILED"


# ------------------------------------------------------------------ take-profit proposals
def test_take_profit_proposed_after_zone_buy(world):
    world.m.add(T1)
    pub_v(verdict(T1, discovery=False))
    pub_z(zone_event(T1))
    world.bee.tick()
    tp = intents(world, strategy="take_profit")
    assert len(tp) == 1 and tp[0]["state"] == "NEEDS_APPROVAL"
    exp = 0.009 + (0.03 - 0.009) * (1 - 0.214)
    assert abs(tp[0]["trigger"]["limit_price_usd"] - exp) < 1e-12
    assert world.bee.approve(tp[0]["id"])["state"] == "PAPER_PLACED"


def test_events_published(world):
    world.m.add(T1)
    pub_v(verdict(T1))
    world.bee.tick()
    types = [e["type"] for e in bus.tail(50)]
    assert "trader.intent.created" in types and "trader.trade.executed" in types


def test_status_shape(world):
    world.m.add(T1)
    pub_v(verdict(T1))
    world.bee.tick()
    s = world.bee.status()
    assert s["effective_mode"] == "paper" and s["budget"]["used_24h"] == 10.0
    assert s["positions"]["paper"][0]["symbol"] == "BEE"


def test_disarm_mid_tick_blocks_send(world, monkeypatch):
    world.arm()
    world.m.add(T1)
    pub_v(verdict(T1))
    from trader_bee import agent, config
    real_eval = agent.policy.evaluate

    def evaluate_then_disarm(*a, **k):
        d = real_eval(*a, **k)
        config.ARM_FILE.unlink()  # beekeeper hits DISARM while gates were running
        return d
    monkeypatch.setattr(agent.policy, "evaluate", evaluate_then_disarm)
    world.bee.tick()
    it = intents(world)[0]
    assert it["state"] == "REJECTED" and "nothing sent" in it["reason"]
    assert not any(c == "buy" for c, _ in world.fx.calls)


def test_paper_take_profit_fills_at_mark(world):
    world.m.add(T1)
    pub_v(verdict(T1, discovery=False))
    pub_z(zone_event(T1))
    world.bee.tick()
    tp = intents(world, strategy="take_profit")[0]
    world.bee.approve(tp["id"])
    world.bee.store.set_mark(f"base:{T1.lower()}", 0.05, "test")  # above the 0.0255 limit
    world.bee.track_take_profits()
    tp = world.bee.store.intent(tp["id"])
    assert tp["state"] == "PAPER_FILLED" and tp["token_amount"] == tp["trigger"]["qty"]
    pos = world.bee.store.positions("paper")[0]
    assert abs(pos["tokens_net"] - pos["tokens"] / 2) < 1e-9  # half the bag sold


def test_live_take_profit_orderbook_states(world):
    world.arm()
    world.m.add(T1)
    pub_v(verdict(T1, discovery=False))
    pub_z(zone_event(T1))
    world.bee.tick()
    tp = intents(world, strategy="take_profit")[0]
    assert world.bee.approve(tp["id"])["state"] == "PLACED"
    real = world.fx.__call__

    def fx(cmd, p, t, status={"s": "PARTIAL", "pct": 40.0}):
        if cmd == "order-status":
            return {"ok": True, "orders": {h.lower(): {"status": status["s"], "filledPct": status["pct"], "reason": None} for h in p["orderHashes"]}}
        return real(cmd, p, t)
    from trader_bee import executor
    executor.runner = fx
    assert world.bee.track_take_profits()["partial"] == 1
    fx.__defaults__[0].update(s="FILLED", pct=100.0)
    assert world.bee.track_take_profits()["filled"] == 1
    assert world.bee.store.intent(tp["id"])["state"] == "CONFIRMED"
