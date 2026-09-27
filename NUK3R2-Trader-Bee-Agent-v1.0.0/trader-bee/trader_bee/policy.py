"""Sizing + the gate pipeline. Pure decision logic: reads data, never executes.

Every buy candidate runs the same pipeline, in this order (cheapest and most decisive first):

  1 control     paused / circuit breaker
  2 research    chain allowed, identity VERIFIED by >= N sources, gate PASS, rank eligible,
                not a known decoy, no conflict with the terminal's human-verified registry
  3 budget      daily $, weekly $, buys/day, per-asset exposure
  4 market      live DexScreener census: liquidity floors, pair age, unexplained same-ticker clones
  5 security    research score >= min, GoPlus honeypot / tax / blacklist flags
  6 zone        (zone buys) live price still inside the buy zone of the signalled structure
  7 route       live quote race: price impact vs mid, round-trip sellability (tax/honeypot tell)
  8 funds       (live) stable balance + gas

Outcomes: PASS -> execute. APPROVAL -> beekeeper queue (soft findings). REJECT -> recorded with
reason; `retryable` rejections (budget, funds, source down, paused) are re-tried later while
the signal is still valid. A broken data source is NEVER read as a pass.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from hive import marketdata, net
from hive.paths import MODULE_DIR

from . import executor


@dataclass
class Decision:
    outcome: str = "pass"  # pass | approval | reject
    reasons: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    retryable: bool = False
    checks: dict = field(default_factory=dict)
    quote: dict = field(default_factory=dict)

    def reject(self, reason: str, retryable: bool = False):
        self.outcome = "reject"
        self.reasons.append(reason)
        self.retryable = retryable
        return self

    def soft(self, reason: str, approved: bool):
        if approved:
            self.notes.append(f"approved by beekeeper despite: {reason}")
        else:
            if self.outcome == "pass":
                self.outcome = "approval"
            self.reasons.append(reason)

    @property
    def done(self) -> bool:
        return self.outcome == "reject"


# ---------------------------------------------------------------- sizing
def resolve_confidence(verdict: dict, bands: dict) -> str:
    c = verdict.get("confidence")
    if c in ("high", "medium", "low"):
        return c
    s = verdict.get("scores") or {}
    cq, t = s.get("core_quality"), s.get("timing")
    for tier in ("high", "medium"):
        b = bands.get(tier) or {}
        if cq is not None and t is not None and cq >= b.get("min_core_quality", 1e9) and t >= b.get("min_timing", 1e9):
            return tier
    return bands.get("fallback", "low")


def discovery_size(verdict: dict, cfg: dict) -> tuple[str, float]:
    tier = resolve_confidence(verdict, cfg["confidence_bands"])
    return tier, float(cfg["strategies"]["discovery_tier"]["sizes_usd"][tier])


def clamp_slippage(cfg: dict) -> float:
    e = cfg["execution"]
    return max(e["slippage_min_pct"], min(e["slippage_max_pct"], e["slippage_pct"]))


# ---------------------------------------------------------------- helpers
def _module_registry() -> dict:
    try:
        return json.loads((MODULE_DIR / "registry.json").read_text(encoding="utf-8")).get("tokens", {})
    except Exception:
        return {}


def zone_band(anchors: dict, upper_percent: float = 78.6) -> dict:
    """Price band of the buy zone under BOTH structures: [bottom, min(upper edge wick, upper edge body)]."""
    b = float(anchors["bottom"])
    tops = [float(anchors[k]) for k in ("wick_high", "body_high") if anchors.get(k)]
    upper = min(b + (t - b) * (1 - upper_percent / 100.0) for t in tops)
    return {"low": b, "high": upper}


# ---------------------------------------------------------------- the pipeline
def evaluate(intent: dict, asset: dict | None, cfg: dict, store, mode: str, approved: bool = False,
             controls: dict | None = None) -> Decision:
    d = Decision()
    g = cfg["gates"]
    usd = float(intent["usd"])
    controls = controls or {}

    # 1 control
    if controls.get("paused"):
        return d.reject(f"paused: {controls.get('paused_reason') or 'kill switch'}", retryable=True)

    # 2 research
    if asset is None:
        return d.reject("no research verdict for this asset")
    v = asset["verdict"]
    chain = v["chain"]
    if chain not in cfg["chains"]:
        return d.reject(f"chain '{chain}' is not tradable by the Trader Bee (allowed: {', '.join(cfg['chains'])})")
    idn = v["identity"]
    srcs = sorted(set(idn.get("sources") or []))
    if idn["status"] != "VERIFIED" or len(srcs) < g["min_identity_sources"]:
        return d.reject(f"identity not verified by >= {g['min_identity_sources']} independent sources ({idn['status']}, {srcs})")
    if v["gate"]["result"] != "PASS":
        return d.reject("research gate FAIL")
    strat = cfg["strategies"][intent["strategy"]] if intent["strategy"] in cfg["strategies"] else {}
    ranks = strat.get("eligible_ranks", ["BUY", "WATCH"])
    if v["rank"] not in ranks:
        return d.reject(f"rank {v['rank']} not eligible ({'/'.join(ranks)})")
    if intent["contract"].lower() in {x.lower() for x in (idn.get("decoys") or [])}:
        return d.reject("contract is on research's decoy list")
    reg = _module_registry()
    for name, row in reg.items():
        if row.get("chainId") == _chain_id(chain) and (row.get("symbol") or name).upper() == v["symbol"].upper() \
                and row.get("contract", "").lower() != intent["contract"].lower():
            return d.reject(f"conflicts with the terminal registry: {name} is verified at {row.get('contract')}")
    d.checks["research"] = {"rank": v["rank"], "gate": v["gate"], "identity_sources": srcs, "researched_at": v["researched_at"]}

    # 3 budget
    b = cfg["budget"]
    t = time.time()
    day, n_day = store.spent(mode, t - 86400)
    week, _ = store.spent(mode, t - 7 * 86400)
    asset_total, _ = store.spent(mode, 0, intent["asset_id"])
    d.checks["budget"] = {"day_usd": round(day, 2), "week_usd": round(week, 2), "buys_today": n_day, "asset_usd": round(asset_total, 2)}
    if day + usd > b["daily_usd"] + 1e-9:
        return d.reject(f"daily budget: ${day:.2f} used + ${usd:.2f} > ${b['daily_usd']}", retryable=True)
    if week + usd > b["weekly_usd"] + 1e-9:
        return d.reject(f"weekly budget: ${week:.2f} used + ${usd:.2f} > ${b['weekly_usd']}", retryable=True)
    if n_day + 1 > b["max_buys_per_day"]:
        return d.reject(f"max {b['max_buys_per_day']} buys per 24h reached", retryable=True)
    if asset_total + usd > b["max_exposure_per_asset_usd"] + 1e-9:
        return d.reject(f"per-asset exposure: ${asset_total:.2f} + ${usd:.2f} > ${b['max_exposure_per_asset_usd']}")

    # 4 market (live census)
    try:
        census = marketdata.dexscreener_token(chain, intent["contract"], agent="trader_bee")
    except net.NetError as e:
        return d.reject(f"DexScreener unavailable ({e}) — source broken, not treated as a pass", retryable=True)
    liq, mid = census["liquidity_usd"], census["price_usd"]
    d.checks["market"] = {"liquidity_usd": round(liq), "pairs_counted": census["counted"], "excluded_as_suspect": census["excluded_as_suspect"],
                          "price_usd": mid, "best_pair": (census["best"] or {}).get("url")}
    if not mid:
        return d.reject("no live priced pair on this chain", retryable=True)
    if liq < g["hard_min_liquidity_usd"]:
        return d.reject(f"liquidity ${liq:,.0f} < hard floor ${g['hard_min_liquidity_usd']:,}", retryable=True)
    if liq < g["soft_min_liquidity_usd"]:
        d.soft(f"thin liquidity ${liq:,.0f} (< ${g['soft_min_liquidity_usd']:,})", approved)
    if census["oldest_pair_created_ms"]:
        age_h = (t * 1000 - census["oldest_pair_created_ms"]) / 3.6e6
        d.checks["market"]["pair_age_hours"] = round(age_h, 1)
        if age_h < g["min_pair_age_hours"]:
            if g.get("young_pair") == "reject":
                return d.reject(f"pair only {age_h:.1f}h old", retryable=True)
            d.soft(f"pair only {age_h:.1f}h old (< {g['min_pair_age_hours']}h)", approved)
    try:
        clones = marketdata.dexscreener_symbol_clones(chain, v["symbol"], intent["contract"], agent="trader_bee")
        known = {x.lower() for x in (idn.get("decoys") or [])}
        bigger = [c for c in clones if c["liquidity_usd"] > liq and c["contract"] not in known]
        d.checks["market"]["same_ticker_clones"] = len(clones)
        if bigger:
            msg = f"unexplained same-ticker token with MORE liquidity: {bigger[0]['contract']} (${bigger[0]['liquidity_usd']:,.0f})"
            if g.get("unexplained_clone") == "reject":
                return d.reject(msg)
            d.soft(msg, approved)
    except net.NetError as e:
        d.soft(f"clone check unavailable ({e})", approved)

    # 5 security
    sec = v.get("security") or {}
    score = sec.get("score")
    gp = None
    try:
        gp = marketdata.goplus_security(chain, intent["contract"], agent="trader_bee")
    except net.NetError as e:
        d.notes.append(f"GoPlus unavailable: {e}")
    d.checks["security"] = {"research_score": score, "goplus": gp}
    if score is not None and score < g["min_security_score"]:
        return d.reject(f"research security score {score} < {g['min_security_score']}")
    if gp:
        bad = [k for k in ("is_honeypot", "cannot_sell_all", "is_blacklisted", "owner_change_balance", "transfer_pausable") if gp.get(k)]
        if bad:
            return d.reject("GoPlus flags: " + ", ".join(bad))
        if gp["buy_tax"] * 100 > g["max_buy_tax_pct"] or gp["sell_tax"] * 100 > g["max_sell_tax_pct"]:
            return d.reject(f"token tax buy {gp['buy_tax'] * 100:.1f}% / sell {gp['sell_tax'] * 100:.1f}% over limit")
    if score is None and not gp:
        if g.get("security_unverifiable") == "reject":
            return d.reject("security unverifiable (no research score, GoPlus has no coverage)")
        d.soft("security unverifiable (no research score, GoPlus has no coverage) — unverifiable is a finding, not a pass", approved)

    # 6 zone re-check (zone buys): verify against reality, not the old event
    if intent["strategy"] == "zone_entry":
        anchors = intent["trigger"].get("anchors") or {}
        band = zone_band(anchors)
        tol = g["zone_price_tolerance_pct"] / 100.0
        d.checks["zone"] = {"band_low": band["low"], "band_high": band["high"], "live_price": mid}
        if mid < band["low"] * (1 - tol):
            return d.reject(f"price ${mid:.8g} broke below the structure bottom ${band['low']:.8g} (new ATL) — structure invalid")
        if mid > band["high"] * (1 + tol):
            return d.reject(f"price ${mid:.8g} is back above the buy zone (≤ ${band['high']:.8g})", retryable=True)

    # 7 route: live quote race + round-trip sellability
    stable = _stable(chain)
    try:
        q = executor.call("quote", {"chain": chain, "src": stable["contract"], "dst": intent["contract"], "amount": f"{usd:.6f}"}, timeout=60)
    except executor.ExecutorError as e:
        return d.reject(f"quote failed: {e}", retryable=True)
    if not q.get("ok") or not q.get("bestOut"):
        return d.reject(f"no venue produced a quote: {q.get('error') or q.get('quotes')}", retryable=True)
    out = float(q["bestOut"])
    eff = usd / out
    impact = (eff / mid - 1) * 100
    d.quote = {"winner": q.get("winner"), "tokens_out": out, "effective_price": eff, "mid": mid, "impact_pct": round(impact, 3),
               "quotes": q.get("quotes")}
    if impact > g["max_price_impact_pct"]:
        return d.reject(f"price impact {impact:.2f}% > {g['max_price_impact_pct']}% (quote vs pool mid)", retryable=True)
    try:
        back = executor.call("quote", {"chain": chain, "src": intent["contract"], "dst": stable["contract"], "amount": _fmt(out * 0.999)}, timeout=60)
        back_usd = float(back.get("bestOut") or 0)
    except executor.ExecutorError:
        back_usd = 0.0
    loss = (1 - back_usd / usd) * 100 if usd else 100
    d.quote["roundtrip_usd"] = back_usd
    d.quote["roundtrip_loss_pct"] = round(loss, 3)
    if back_usd <= 0:
        return d.reject("cannot quote a SELL of this token back to the stable (honeypot tell / no exit route)")
    if loss > g["max_roundtrip_loss_pct"]:
        return d.reject(f"round-trip loss {loss:.1f}% > {g['max_roundtrip_loss_pct']}% (tax / thin exit)")

    # 8 funds (live only)
    if mode == "live":
        try:
            bal = executor.call("balances", {"chain": chain, "tokens": [stable["contract"]]}, timeout=60)
        except executor.ExecutorError as e:
            return d.reject(f"balance read failed: {e}", retryable=True)
        have = float(((bal.get("tokens") or {}).get(stable["contract"].lower()) or {}).get("amount") or 0)
        gas = float(bal.get("native") or 0)
        need_gas = cfg["execution"]["min_gas_native"].get(chain, 0)
        d.checks["funds"] = {"stable": have, "native": gas}
        if have < usd + cfg["budget"]["min_stable_reserve_usd"]:
            return d.reject(f"insufficient {stable['symbol']}: have {have:.2f}, need {usd:.2f}", retryable=True)
        if gas < need_gas:
            return d.reject(f"insufficient gas: {gas:.6f} ETH < {need_gas}", retryable=True)
    return d


def _fmt(x: float) -> str:
    return f"{x:.12f}".rstrip("0").rstrip(".")


def _chain_id(chain: str) -> int | None:
    from hive import chains
    c = chains.get(chain)
    return c["chain_id"] if c else None


def _stable(chain: str) -> dict:
    from hive import chains
    return chains.get(chain)["stable"]
