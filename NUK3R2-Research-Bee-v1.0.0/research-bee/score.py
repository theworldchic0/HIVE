#!/usr/bin/env python3
"""NUK3R2 Research Bee — scorer, validator and report writer.

  python score.py check    <scorecard.json>     validate only (lists every missing score / missing evidence)
  python score.py finalize <scorecard.json>     validate → compute → report.md + verdict.json (+ scores.json)

The math is the Phase 1 document's, with the two audited fixes (config/research.json):
  Gate               Ease + Hair-on-Fire + Exclusivity /30, PASS at 16+ (absolute: a fail stops everything)
  Narrative Power    7 Shiller questions × 0-2 = /14
  Asset Expression   5 × 0-2 = /10
  Team               person = high(0-5) + medium(0-3) + low(0-2); (Founder×5 + Σothers)/(5 + n_others)
  Core Quality /50   Product /10 + Narrative Power /14 + Asset Expression /10 + Team /10 + Smart Money /6
  Timing /20         Stage→points /5 + Curve→points /5 + Constellation /5 + Liquidity Trajectory /5
  Matrix             Exceptional 45+/17+ · Priority 40+/13+ · Quality Watch 40+/<13 · Narrative Spec 13+ · Pass <40/<13

Evidence standard (§21): every scored item needs >=1 evidence item. A score without evidence is refused.
The verdict is WRITTEN, not published: the beekeeper reads the report first, then `hive publish`.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1]))

from hive import chains, contracts  # noqa: E402

NP_KEYS = ("one_sentence", "perennial_root", "tribe", "face_or_mystery", "fear_envy", "repetition_machine", "action_script")
NP_LABELS = {"one_sentence": "One-Sentence Test", "perennial_root": "Perennial Root", "tribe": "Tribe", "face_or_mystery": "Face or Mystery",
             "fear_envy": "Fear + Envy Engine", "repetition_machine": "Repetition Machine", "action_script": "Action Script"}
AE_KEYS = ("narrative_token_fit", "category_leadership", "distribution_reach", "product_reality", "token_capture")
AE_LABELS = {"narrative_token_fit": "Narrative-to-Token Fit", "category_leadership": "Category Leadership", "distribution_reach": "Distribution / Reach",
             "product_reality": "Product Reality", "token_capture": "Token Capture / Economic Link"}
STATUSES = ["EARLY ASYMMETRIC", "STRONG ACCUMULATION", "WATCH", "MATURE / LATE", "DEAD NARRATIVE", "SPECULATIVE NARRATIVE"]


def load_config() -> dict:
    return json.loads((ROOT / "config" / "research.json").read_text(encoding="utf-8"))


class Problems(list):
    def need(self, cond: bool, msg: str):
        if not cond:
            self.append(msg)


def _scored(item: dict, name: str, mx: int, p: Problems, allow_null=False) -> float | None:
    s = (item or {}).get("score")
    if s is None:
        if not allow_null:
            p.append(f"{name}: score missing")
        return None
    p.need(isinstance(s, (int, float)) and 0 <= s <= mx, f"{name}: score {s!r} outside 0-{mx}")
    p.need(bool(item.get("evidence")), f"{name}: no evidence — every score needs a source (§21 evidence standard)")
    return float(s) if isinstance(s, (int, float)) else None


def person_score(person: dict, name: str, p: Problems) -> float:
    if person.get("unverifiable"):
        return 0.0
    hi, me, lo = person.get("high"), person.get("medium"), person.get("low")
    for v, mx, part in ((hi, 5, "high"), (me, 3, "medium"), (lo, 2, "low")):
        p.need(v is not None and 0 <= v <= mx, f"team {name}: {part} credibility must be 0-{mx} (or set unverifiable: true)")
    p.need(bool(person.get("sources")), f"team {name}: no source — material team claims need a link + quote (§13)")
    return float((hi or 0) + (me or 0) + (lo or 0))


def compute(sc: dict, cfg: dict) -> tuple[dict, Problems]:
    p = Problems()
    a = sc.get("asset") or {}
    p.need(a.get("identity_status") == "VERIFIED", f"identity is {a.get('identity_status')} — research cannot produce a tradable verdict on an unverified contract")
    g = sc["gate"]
    gate_parts = {k: _scored(g[k], f"gate.{k}", 10, p) for k in ("ease_of_use", "hair_on_fire", "exclusivity")}
    gate_total = sum(v or 0 for v in gate_parts.values())
    gate_pass = gate_total >= cfg["gate"]["pass_min"] and all(v is not None for v in gate_parts.values())
    out = {"gate": {**gate_parts, "total": gate_total, "pass": gate_pass}}
    decision = (sc.get("decision") or {}).get("call")
    p.need(decision in ("BUY", "WATCH", "PASS"), "decision.call must be BUY, WATCH or PASS")
    p.need(bool((sc.get("decision") or {}).get("why")), "decision.why: explain the decision in plain English")
    if not gate_pass:
        out["stopped_at_gate"] = True
        p.need(decision == "PASS", "the Exclusivity Gate failed — the gate is absolute, the decision must be PASS")
        return out, p

    c = sc.get("cycle") or {}
    p.need(c.get("regime") in c.get("regime_options", []) or c.get("regime") in (
        "Bull Expansion", "Late Expansion", "Distribution / Transition", "Bear Decline", "Capitulation / Bottom Watch", "Recovery / Early Expansion", "Mania / Late Cycle"),
        "cycle.regime: pick one of the seven regimes")
    p.need(bool(c.get("interpretation")), "cycle.interpretation: the mandatory one-line cycle interpretation")
    n = sc.get("narrative") or {}
    p.need(bool(n.get("primary")), "narrative.primary: the one-sentence story")
    p.need(all((n.get("lineage") or {}).get(k) for k in ("perennial_root", "prior_crypto_narrative", "current_mutation", "asset_expression")),
           "narrative.lineage: all four links (root → prior crypto narrative → mutation → this asset)")
    p.need(n.get("status") in ("Emerging", "Rising", "Mature", "Fading", "Revived", "Dead"), "narrative.status missing")
    if n.get("status") == "Revived" or (sc.get("stage") or {}).get("revival"):
        p.need(bool((sc.get("stage") or {}).get("revival_catalyst")), "revival requires a NEW catalyst (§4E / Principle 14) — name it in stage.revival_catalyst")

    np_ = {k: _scored(sc["narrative_power"][k], f"narrative_power.{k}", 2, p) for k in NP_KEYS}
    np_total = sum(v or 0 for v in np_.values())
    ae = {k: _scored(sc["asset_expression"][k], f"asset_expression.{k}", 2, p) for k in AE_KEYS}
    ae_total = sum(v or 0 for v in ae.values())
    product = _scored(sc["product_quality"], "product_quality", 10, p) or 0
    smf = _scored(sc["smart_money_fit"], "smart_money_fit", 6, p) or 0

    t = sc.get("team") or {}
    founder = t.get("founder") or {}
    fs = person_score(founder, founder.get("name") or "founder", p)
    others = [person_score(o, o.get("name") or f"member {i + 1}", p) for i, o in enumerate(t.get("others") or [])]
    team = (fs * 5 + sum(others)) / (5 + len(others))
    unverifiable = [x.get("name") or "?" for x in [founder, *(t.get("others") or [])] if x.get("unverifiable")]

    st = sc.get("stage") or {}
    p.need(st.get("stage") in (1, 2, 3, 4, 5), "stage.stage must be 1-5")
    p.need(bool(st.get("evidence")), "stage: no evidence")
    tcfg = cfg["timing"]
    stage_pts = min(5, tcfg["stage_points"].get(str(st.get("stage")), 0) + (tcfg["stage_revival_bonus"] if st.get("revival") else 0))
    cv = sc.get("curve") or {}
    p.need(cv.get("label") in tcfg["curve_points"], f"curve.label must be one of {list(tcfg['curve_points'])}")
    p.need(bool(cv.get("evidence")), "curve: no evidence (one viral post / one influencer is the weakest evidence — §7D)")
    curve_pts = tcfg["curve_points"].get(cv.get("label"), 0)
    const = _scored(sc["constellation"], "constellation", 5, p) or 0
    liq_traj = _scored((sc.get("liquidity") or {}).get("trajectory") or {}, "liquidity.trajectory", 5, p) or 0

    core = product + np_total + ae_total + team + smf
    timing = stage_pts + curve_pts + const + liq_traj
    m = cfg["matrix"]
    if core >= m["exceptional"]["core"] and timing >= m["exceptional"]["timing"]:
        cls = "exceptional"
    elif core >= m["priority"]["core"] and timing >= m["priority"]["timing"]:
        cls = "priority_opportunity"
    elif core >= m["priority"]["core"]:
        cls = "quality_watch"
    elif timing >= m["priority"]["timing"]:
        cls = "narrative_speculation_watch"
    else:
        cls = "pass_avoid"

    p.need(bool(sc.get("archetypes")), "archetypes: assign at least one (§9)")
    p.need(sc.get("final_status") in STATUSES, f"final_status must be one of {STATUSES}")
    p.need(bool(sc.get("risk_flags")), "risk_flags: list every material risk (an empty list is not credible)")
    p.need(bool(sc.get("recheck_triggers")), "recheck_triggers: state what would justify re-running this research")
    p.need(bool(sc.get("one_sentence_overview")), "one_sentence_overview missing")
    p.need((sc.get("narrative_conversion") or {}).get("state") in ("None", "Emerging", "Confirmed", "Strong", "Reflexive"), "narrative_conversion.state missing")

    band = lambda v, bands: next(lbl for lo, lbl in bands if v >= lo)  # noqa: E731
    out.update({
        "narrative_power": {**np_, "total": np_total, "band": band(np_total, [(13, "Exceptional narrative engine"), (11, "Very strong narrative"), (9, "Strong narrative"),
                                                                                (6, "Limited or inconsistent narrative power"), (0, "Weak narrative engine")])},
        "asset_expression": {**ae, "total": ae_total},
        "product_quality": product, "smart_money_fit": smf,
        "team": {"founder": fs, "others": others, "weighted": round(team, 2), "unverifiable": unverifiable},
        "core_quality": round(core, 2),
        "core_band": band(core, [(45, "Exceptional"), (40, "Strong"), (35, "Good"), (30, "Acceptable but inconsistent"), (25, "Below standard"), (0, "Weak")]),
        "timing": {"stage_points": stage_pts, "curve_points": curve_pts, "constellation": const, "liquidity_trajectory": liq_traj, "total": timing,
                   "band": band(timing, [(17, "Exceptional"), (13, "Favorable"), (10, "Neutral"), (6, "Weak / uncertain"), (0, "Poor timing")])},
        "matrix_class": cls, "confidence": m["confidence"][cls],
    })
    if decision == "BUY" and cls in ("pass_avoid",):
        p.append("decision BUY while the Opportunity Matrix says Pass/Avoid — allowed only with an explicit override reason in decision.override_reason")
        if (sc.get("decision") or {}).get("override_reason"):
            p.pop()
    return out, p


def verdict(sc: dict, res: dict) -> dict:
    a = sc["asset"]
    call = sc["decision"]["call"]
    rank = "FAIL" if not res["gate"]["pass"] else {"BUY": "BUY", "WATCH": "WATCH", "PASS": "AVOID"}[call]
    ev = json.loads(Path(sc["evidence_file"]).read_text()) if sc.get("evidence_file") and Path(sc["evidence_file"]).exists() else {}
    cyc = ev.get("cycle") or {}
    v = {
        "asset_id": chains.asset_id(a["chain"], a["contract"]), "chain": a["chain"], "contract": a["contract"], "symbol": a["symbol"], "name": a.get("name"),
        "researched_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "snapshot_id": "RB-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + (a["symbol"] or "X"),
        "identity": {"status": a["identity_status"], "sources": a.get("identity_sources") or [], "canonical_pool": a.get("canonical_pool"),
                     "gt_network": (chains.get(a["chain"]) or {}).get("gt_network"), "decoys": a.get("decoys") or []},
        "gate": {"result": "PASS" if res["gate"]["pass"] else "FAIL", "score": res["gate"]["total"]},
        "rank": rank, "discovery": bool(a.get("discovery")),
        "security": ({"score": sc["security_score"], "source": "research"} if sc.get("security_score") is not None else None),
        "liquidity_usd": ((ev.get("liquidity") or {}).get("main_pool") or {}).get("liquidity_usd"),
        "market_direction_snapshot_id": (cyc.get("market_direction") or {}).get("snapshot_id"),
        "blueprint_snapshot_id": (cyc.get("bottom_blueprint") or {}).get("snapshot_id"),
        "notes": sc["decision"]["why"][:900],
    }
    if res["gate"]["pass"]:
        v["confidence"] = res["confidence"]
        v["scores"] = {"core_quality": res["core_quality"], "timing": res["timing"]["total"], "narrative_power": res["narrative_power"]["total"]}
        v["archetype"] = ", ".join(sc.get("archetypes") or []) or None
        v["narrative_stage"] = f"stage {sc['stage']['stage']}{' + revival' if sc['stage'].get('revival') else ''} · curve {sc['curve']['label']}"
    else:
        v["confidence"] = None
    return v


def _ev(items) -> str:
    out = []
    for e in items or []:
        if isinstance(e, dict):
            out.append(f"[{e.get('source', 'source')}] “{e.get('quote', '')}”" if e.get("quote") else f"[{e.get('source', 'source')}]")
        else:
            out.append(str(e))
    return "; ".join(out) or "—"


def report(sc: dict, res: dict, v: dict) -> str:
    a = sc["asset"]
    ev = json.loads(Path(sc["evidence_file"]).read_text()) if sc.get("evidence_file") and Path(sc["evidence_file"]).exists() else {}
    cyc, liq, bb = ev.get("cycle") or {}, ev.get("liquidity") or {}, ev.get("btc_benchmark") or {}
    L = [f"# {a.get('name') or a['symbol']} (${a['symbol']}) — NUK3R2 Phase 1 Research Report",
         f"_Point-in-time research, {v['researched_at']} · snapshot {v['snapshot_id']} · not investment advice._", "",
         "## 1. Header", f"- **Chain:** {a['chain']}  ·  **Contract:** `{a['contract']}`",
         f"- **Identity:** {a['identity_status']} via {', '.join(a.get('identity_sources') or [])}" + (f"  ·  decoys rejected: {len(a.get('decoys') or [])}" if a.get("decoys") else ""),
         f"- **CoinGecko:** {a.get('coingecko_url') or '—'}  ·  **Website:** {a.get('website') or '—'}", "",
         "## 2. One-Sentence Overview", sc.get("one_sentence_overview") or "—", ""]
    if not res["gate"]["pass"]:
        g = res["gate"]
        L += ["## Exclusivity Gate — FAILED (research stops here)",
              f"- Ease of Use {g['ease_of_use']}/10 — {_ev(sc['gate']['ease_of_use']['evidence'])}",
              f"- Hair-on-Fire {g['hair_on_fire']}/10 — {_ev(sc['gate']['hair_on_fire']['evidence'])}",
              f"- Exclusivity {g['exclusivity']}/10 — {_ev(sc['gate']['exclusivity']['evidence'])}",
              f"- **Total {g['total']}/30 (pass = 16+).** The gate is absolute.", "",
              "## My Decision", f"**PASS** — {sc['decision']['why']}"]
        return "\n".join(L) + "\n"
    n, st, cv = sc["narrative"], sc["stage"], sc["curve"]
    L += ["## 3. Cycle Context",
          f"- **Regime:** {sc['cycle']['regime']} — {sc['cycle']['interpretation']}",
          f"- BTC ${cyc.get('btc_price', '—'):,} ({cyc.get('distance_from_cycle_high_pct', '—')}% from the ${cyc.get('cycle_top', {}).get('price', 0):,} cycle high"
          + (f"; +{cyc['distance_from_cycle_low_pct']}% from the {cyc['cycle_low_since_top']['date']} low)" if cyc.get("distance_from_cycle_low_pct") is not None else ")")
          if isinstance(cyc.get("btc_price"), (int, float)) else "- BTC price: unavailable (source down)",
          f"- Bottom Blueprint: {((cyc.get('bottom_blueprint') or {}).get('clock') or {}).get('state', '—')} "
          f"(day {((cyc.get('bottom_blueprint') or {}).get('clock') or {}).get('bottom_window_day', '—')}) · Market Direction: {(cyc.get('market_direction') or {}).get('status', '—')}", "",
          "## 4. Narrative Identity", f"- **Primary:** {n['primary']}", f"- **Secondary:** {', '.join(n.get('secondary') or []) or '—'}",
          f"- **Perennial root(s):** {', '.join(map(str, n.get('perennial_roots') or [])) or '—'}",
          f"- **Constellation:** {', '.join(n.get('constellation_members') or []) or '—'}",
          f"- **Lineage:** {n['lineage']['perennial_root']} → {n['lineage']['prior_crypto_narrative']} → {n['lineage']['current_mutation']} → {n['lineage']['asset_expression']}",
          f"- **Status:** {n['status']}", "",
          f"## 5. Narrative Power — {res['narrative_power']['total']:g}/14 ({res['narrative_power']['band']})"]
    L += [f"- {NP_LABELS[k]}: {res['narrative_power'][k]:g}/2 — {_ev(sc['narrative_power'][k]['evidence'])}" for k in NP_KEYS]
    L += ["", "## 6. Narrative Timing", f"- **Stage:** {st['stage']}{' + Revival (' + str(st.get('revival_catalyst')) + ')' if st.get('revival') else ''} → {res['timing']['stage_points']}/5 timing pts — {_ev(st.get('evidence'))}",
          f"- **Curve:** {cv['label']} → {res['timing']['curve_points']}/5 — {_ev(cv.get('evidence'))}",
          f"- **Narrative conversion:** {sc['narrative_conversion']['state']} — {_ev(sc['narrative_conversion'].get('evidence'))}", ""]
    if ev.get("meta") and ev["meta"].get("matching_metas"):
        L += ["**Meta Bee (machine-measured, evidence only):** " + "; ".join(f"{m['name']}: {m.get('curve_daily', '?')} (d) / {m.get('curve_weekly', '?')} (w)" for m in ev["meta"]["matching_metas"]), ""]
    L += [f"## 7. Narrative Constellation — {res['timing']['constellation']:g}/5", f"- {_ev(sc['constellation']['evidence'])}", "",
          f"## 8. Archetype", f"- {', '.join(sc['archetypes'])}", "",
          f"## 9. Asset Expression — {res['asset_expression']['total']:g}/10"]
    L += [f"- {AE_LABELS[k]}: {res['asset_expression'][k]:g}/2 — {_ev(sc['asset_expression'][k]['evidence'])}" for k in AE_KEYS]
    g = res["gate"]
    L += ["", "## 10. Product", f"- Gate: Ease {g['ease_of_use']:g} · Hair-on-Fire {g['hair_on_fire']:g} · Exclusivity {g['exclusivity']:g} = **{g['total']:g}/30 PASS**",
          f"- Product Quality {res['product_quality']:g}/10 — {_ev(sc['product_quality']['evidence'])}", "",
          "## 11. Liquidity",
          f"- Main pool: ${(liq.get('main_pool') or {}).get('liquidity_usd', 0):,} on {(liq.get('main_pool') or {}).get('dex', '—')} · all pools ${liq.get('total_liquidity_usd', 0):,}"
          f" ({liq.get('pairs_counted', '—')} counted, {liq.get('pairs_excluded_as_suspect', 0)} excluded as suspect)",
          f"- ±2% depth: {'$' + format(liq['depth_2pct_measured_usd'], ',') if liq.get('depth_2pct_measured_usd') else 'not measured'} (estimate ≈${liq.get('depth_2pct_estimate_usd', 0):,}, not used for tier)",
          f"- **Tier:** {liq.get('tier') or '—'} · **Trajectory:** {res['timing']['liquidity_trajectory']:g}/5 — {_ev(sc['liquidity']['trajectory']['evidence'])}",
          f"- Cycle-relative: {sc['liquidity'].get('cycle_relative') or '—'} · Contract verification: {a['identity_status']} ({', '.join(a.get('identity_sources') or [])})", ""]
    if bb.get("excess_pp") is not None:
        L += [f"**BTC benchmark** ({bb['window_start']} → now): token {bb['token_return_pct']:+.1f}% vs BTC {bb['btc_return_pct']:+.1f}% = **{bb['excess_pp']:+.1f} pp** ({bb['method']})", ""]
    t = res["team"]
    L += [f"## 12. Team — {t['weighted']:g}/10 (founder-weighted)"]
    for person, s in [(sc["team"]["founder"], t["founder"]), *zip(sc["team"].get("others") or [], t["others"])]:
        L.append(f"- {person.get('name') or '?'} ({person.get('role') or '—'}): " + ("**UNVERIFIABLE** (a real finding, not neutral)" if person.get("unverifiable") else f"{s:g}/10")
                 + f" — {_ev(person.get('sources'))}")
    L += ["", f"## 13. Smart Money Fit — {res['smart_money_fit']:g}/6", f"- {_ev(sc['smart_money_fit']['evidence'])}", "",
          f"## 14. Core Quality — {res['core_quality']:g}/50 ({res['core_band']})",
          f"Product {res['product_quality']:g} + Narrative Power {res['narrative_power']['total']:g} + Asset Expression {res['asset_expression']['total']:g} + Team {t['weighted']:g} + Smart Money {res['smart_money_fit']:g}", "",
          f"## 15. Timing — {res['timing']['total']:g}/20 ({res['timing']['band']})",
          f"Stage {res['timing']['stage_points']} + Curve {res['timing']['curve_points']} + Constellation {res['timing']['constellation']:g} + Liquidity Trajectory {res['timing']['liquidity_trajectory']:g}",
          f"**Opportunity Matrix:** {res['matrix_class'].replace('_', ' ').title()} → Hive confidence **{res['confidence']}**", "",
          f"## 16. Final Status — {sc['final_status']}", "",
          "## 17. Risk Flags"] + [f"- {r}" for r in sc["risk_flags"]] + ["", "## 18. Re-check Triggers"] + [f"- {r}" for r in sc["recheck_triggers"]] + [
          "", f"## 19. My Decision — **{sc['decision']['call']}**", sc["decision"]["why"], "",
          f"_Hive handoff: rank **{v['rank']}**, confidence **{v.get('confidence')}**, discovery **{v['discovery']}** → "
          + ("the Trader Bee may buy $" + {"high": "10", "medium": "5", "low": "1"}.get(v.get("confidence") or "", "0") + " (discovery tier) if every gate passes, and the Fib Bee starts watching for the $1 zone entry._"
             if v["discovery"] and v["rank"] in ("BUY", "WATCH") else "the Fib Bee watches it for the $1 buy-zone entry._" if v["rank"] in ("BUY", "WATCH") else "nothing trades._")]
    if ev.get("source_health"):
        bad = {k: s for k, s in ev["source_health"].items() if s != "ok"}
        L += ["", "_Sources: " + ", ".join(k for k, s in ev["source_health"].items() if s == "ok") + (" · FAILED: " + "; ".join(f"{k} ({s})" for k, s in bad.items()) if bad else "") + "_"]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check", "finalize"])
    ap.add_argument("scorecard")
    a = ap.parse_args()
    path = Path(a.scorecard)
    sc = json.loads(path.read_text(encoding="utf-8"))
    res, probs = compute(sc, load_config())
    if probs:
        print(f"NOT READY — {len(probs)} item(s):")
        for x in probs:
            print("  ✗", x)
        return 1
    if a.cmd == "check":
        print("scorecard complete ✓", json.dumps({k: res[k] for k in res if k in ("core_quality", "timing", "matrix_class", "confidence")}, default=str))
        return 0
    v = verdict(sc, res)
    contracts.validate("research.verdict", v)
    (path.parent / "scores.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    (path.parent / "verdict.json").write_text(json.dumps(v, indent=1), encoding="utf-8")
    (path.parent / "report.md").write_text(report(sc, res, v), encoding="utf-8")
    print(json.dumps({"report": str(path.parent / "report.md"), "verdict": str(path.parent / "verdict.json"), "rank": v["rank"], "confidence": v.get("confidence"),
                      "gate": v["gate"], "core_quality": res.get("core_quality"), "timing": (res.get("timing") or {}).get("total"), "matrix": res.get("matrix_class")}, indent=1))
    print("\nShow the beekeeper report.md. Publish ONLY after they confirm:\n  python -m hive publish --type research.verdict --file " + str(path.parent / "verdict.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
