#!/usr/bin/env python3
"""NUK3R2 Research Bee — deterministic FACT collector (Phase 1, step 0 of every report).

  python collect.py PONS
  python collect.py "HOOKR | Robinhood Chain"
  python collect.py 0xCONTRACT [--chain base]
  python collect.py PONS --pick 2          choose candidate #2 when identity is AMBIGUOUS

Writes <HIVE_DATA>/research/<run>/evidence.json (raw facts + source health) and a scorecard.json
pre-filled with the identity + the quantitative fields. Claude fills the judgments; score.py does the
math. This script never scores narrative, team or product — those are researcher judgments.

Identity rule (terminal law 3 + Hive rule): identity = CHAIN + CONTRACT. VERIFIED needs one IDENTITY
ANCHOR (CoinGecko's platform mapping or the contract printed on the official site) plus at least one
more independent source (DexScreener/GeckoTerminal pools, the chain explorer). A ticker match alone
is never identity. Same-ticker contracts on the same chain are listed as decoys.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[1]))

from hive import chains, marketdata, net  # noqa: E402
from hive.paths import BLUEPRINT_DIR, MARKET_DIRECTION_DIR, sub  # noqa: E402

AGENT = "research_agent"
EVM_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
SOL_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
CHAIN_ALIASES = {"robinhood chain": "robinhood", "rh": "robinhood", "robinhood": "robinhood", "base": "base", "sol": "solana",
                 "solana": "solana", "eth": "ethereum", "ethereum": "ethereum", "arb": "arbitrum", "arbitrum": "arbitrum", "bsc": "bsc", "bnb": "bsc"}


def load_config() -> dict:
    return json.loads((ROOT / "config" / "research.json").read_text(encoding="utf-8"))


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Health:
    """Every source call is recorded: ok, or the exact failure. A failure is never read as 'no data'."""

    def __init__(self):
        self.sources: dict[str, str] = {}
        self.gaps: list[str] = []

    def run(self, name: str, fn, *a, **k):
        try:
            out = fn(*a, **k)
            self.sources.setdefault(name, "ok")
            return out
        except net.NetError as e:
            self.sources[name] = f"ERROR: {str(e)[:160]}"
            return None
        except Exception as e:  # noqa: BLE001 — a parser surprise is still a broken source, reported
            self.sources[name] = f"ERROR: {type(e).__name__}: {str(e)[:140]}"
            return None


def parse_query(q: str, chain_arg: str | None) -> dict:
    q = q.strip()
    chain = chain_arg
    if "|" in q:
        q, c = [x.strip() for x in q.split("|", 1)]
        chain = chain or c
    chain = CHAIN_ALIASES.get((chain or "").strip().lower(), (chain or "").strip().lower() or None)
    q = q.lstrip("$").strip()
    if EVM_RE.match(q):
        return {"kind": "contract", "contract": q, "chain": chain}
    if SOL_RE.match(q) and not q.isupper():
        return {"kind": "contract", "contract": q, "chain": chain or "solana"}
    return {"kind": "ticker", "symbol": q.upper(), "chain": chain}


# ------------------------------------------------------------------ identity
def _ds_candidates(pairs: list[dict], symbol: str | None, contract: str | None) -> dict:
    """Group DexScreener pairs into (chain, contract) candidates for the queried token."""
    cands: dict[tuple, dict] = {}
    for p in pairs:
        ck = chains.by_dexscreener(p.get("chainId") or "")
        for side in ("baseToken", "quoteToken"):
            t = p.get(side) or {}
            addr = t.get("address") or ""
            if contract and addr.lower() != contract.lower():
                continue
            if symbol and (t.get("symbol") or "").upper() != symbol:
                continue
            if not addr:
                continue
            key = (ck or f"unsupported:{p.get('chainId')}", chains.norm_contract(ck or "", addr))
            c = cands.setdefault(key, {"chain": key[0], "contract": key[1], "symbol": t.get("symbol"), "name": t.get("name"),
                                       "ds_liquidity_usd": 0.0, "ds_volume_24h": 0.0, "ds_pairs": 0, "oldest_pair_ms": None, "sources": set()})
            c["ds_liquidity_usd"] += float((p.get("liquidity") or {}).get("usd") or 0)
            c["ds_volume_24h"] += float((p.get("volume") or {}).get("h24") or 0)
            c["ds_pairs"] += 1
            if p.get("pairCreatedAt"):
                c["oldest_pair_ms"] = min(c["oldest_pair_ms"] or p["pairCreatedAt"], p["pairCreatedAt"])
            c["sources"].add("dexscreener")
    return cands


def resolve_identity(query: dict, cfg: dict, h: Health) -> dict:
    symbol = query.get("symbol")
    contract = query.get("contract")
    pairs = h.run("dexscreener", (lambda: marketdata.net.fetch_json(f"https://api.dexscreener.com/latest/dex/tokens/{contract}", agent=AGENT,
                                                                    operation="token_pairs").get("pairs") or []) if contract else
                  (lambda: marketdata.dexscreener_search(symbol, agent=AGENT))) or []
    cands = _ds_candidates(pairs, symbol, contract)

    # CoinGecko: symbol search -> coin -> platform map (the strongest identity anchor available keyless)
    cg_coins = []
    if symbol:
        s = h.run("coingecko", marketdata.coingecko, f"/search?query={symbol}", agent=AGENT) or {}
        ids = [c["id"] for c in (s.get("coins") or []) if (c.get("symbol") or "").upper() == symbol][:3]
    else:
        ids = []
    for cid in ids:
        coin = h.run("coingecko", marketdata.coingecko, f"/coins/{cid}?localization=false&tickers=false&community_data=false&developer_data=false", agent=AGENT)
        if coin:
            cg_coins.append(coin)
    if contract and not cg_coins:
        for ck in ([query["chain"]] if query.get("chain") else cfg["chains_searched"]):
            c = chains.get(ck) or {}
            if not c.get("cg_platform"):
                continue
            coin = h.run("coingecko", marketdata.coingecko, f"/coins/{c['cg_platform']}/contract/{contract}", agent=AGENT)
            if coin and coin.get("id"):
                cg_coins.append(coin)
                break
    for coin in cg_coins:
        matched = False
        for platform, addr in (coin.get("platforms") or {}).items():
            ck = chains.by_cg_platform(platform)
            if not ck or not addr:
                continue
            key = (ck, chains.norm_contract(ck, addr))
            if key in cands:
                cands[key]["sources"].add("coingecko")
                cands[key]["coingecko_id"] = coin["id"]
                matched = True
        if not matched and not any(v for v in (coin.get("platforms") or {}).values()):
            # a coin with no token contract (L1 native asset): identity is the CoinGecko id
            key = ("native", f"native:{coin['id']}")
            cands[key] = {"chain": "native", "contract": key[1], "symbol": (coin.get("symbol") or "").upper(), "name": coin.get("name"),
                          "ds_liquidity_usd": 0.0, "ds_volume_24h": 0.0, "ds_pairs": 0, "oldest_pair_ms": None,
                          "sources": {"coingecko"}, "coingecko_id": coin["id"]}

    if query.get("chain"):
        cands = {k: v for k, v in cands.items() if v["chain"] in (query["chain"], "native")}

    # deepen the top candidates: GeckoTerminal info, explorer, official site
    top = sorted(cands.values(), key=lambda c: (-len(c["sources"]), -c["ds_liquidity_usd"]))[:4]
    cg_by_id = {c["id"]: c for c in cg_coins}
    for c in top:
        if c["chain"] not in chains.CHAINS:
            continue
        info = h.run("geckoterminal", marketdata.geckoterminal_token_info, c["chain"], c["contract"], agent=AGENT)
        if info:
            c["sources"].add("geckoterminal")
            c["gt_info"] = info
            if info.get("coingecko_coin_id") and not c.get("coingecko_id"):
                c["coingecko_id_from_gt"] = info["coingecko_coin_id"]
        ex = h.run("explorer", marketdata.blockscout_token, c["chain"], c["contract"], agent=AGENT)
        if ex and ex.get("exists"):
            c["sources"].add("explorer")
            c["explorer"] = ex
        if cfg.get("official_site_contract_check"):
            sites = list((c.get("gt_info") or {}).get("websites") or [])
            coin = cg_by_id.get(c.get("coingecko_id") or "")
            if coin:
                sites += [u for u in ((coin.get("links") or {}).get("homepage") or []) if u]
            for url in list(dict.fromkeys(sites))[:3]:
                html = h.run("official_site", net.fetch_text, url, agent=AGENT, operation="official_site")
                if html and c["contract"].lower() in html.lower():
                    c["sources"].add("official_site")
                    c["official_site_hit"] = url
                    break
            c["official_sites"] = list(dict.fromkeys(sites))[:5]

    ranked = sorted(cands.values(), key=lambda c: (-len(c["sources"]), -c["ds_liquidity_usd"]))
    for c in ranked:
        anchors = c["sources"] & {"coingecko", "official_site"}
        c["identity_anchor"] = sorted(anchors)
        c["sources"] = sorted(c["sources"])
        c["verified"] = bool(anchors) and len(c["sources"]) >= 2
    verified = [c for c in ranked if c["verified"]]
    if not ranked:
        status, chosen = "NOT_FOUND", None
    elif len(verified) == 1:
        status, chosen = "VERIFIED", verified[0]
    elif len(verified) > 1:
        status, chosen = "AMBIGUOUS", None
    else:
        status, chosen = "UNRESOLVED", None
    return {"status": status, "chosen": chosen, "candidates": ranked,
            "rule": "VERIFIED = one identity anchor (CoinGecko platform mapping or contract on the official site) + >=2 sources in total"}


# ------------------------------------------------------------------ facts about the chosen asset
def cycle_context(cfg: dict, h: Health) -> dict:
    out = {"halving_date": cfg["btc_benchmark"]["halving_date"], "cycle_top": cfg["btc_benchmark"]["cycle_top"]}
    btc = h.run("btc_price", marketdata.btc_spot, agent=AGENT)
    if btc:
        out["btc_price"], out["btc_price_source"] = btc
        top = cfg["btc_benchmark"]["cycle_top"]["price"]
        out["distance_from_cycle_high_pct"] = round((btc[0] / top - 1) * 100, 2)
    # lowest daily low since the cycle top (Coinbase daily candles, 300 per request)
    lows = []
    start = date.fromisoformat(cfg["btc_benchmark"]["cycle_top"]["date"])
    today = datetime.now(timezone.utc).date()
    while start < today:
        end = min(start + timedelta(days=299), today)
        rows = h.run("btc_history", net.fetch_json, f"https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=86400&start={start}T00:00:00Z&end={end}T23:59:59Z",
                     agent=AGENT, operation="btc_candles", ttl_s=3600)
        if rows is None:
            break
        lows += [(r[1], datetime.fromtimestamp(r[0], timezone.utc).date().isoformat()) for r in rows]
        start = end + timedelta(days=1)
    if lows:
        lo = min(lows)
        out["cycle_low_since_top"] = {"price": lo[0], "date": lo[1], "source": "coinbase daily candles"}
        if out.get("btc_price"):
            out["distance_from_cycle_low_pct"] = round((out["btc_price"] / lo[0] - 1) * 100, 2)
    try:
        spec = __import__("importlib.util").util.spec_from_file_location("bb", BLUEPRINT_DIR / "bottom_blueprint.py")
        bb = __import__("importlib.util").util.module_from_spec(spec)
        spec.loader.exec_module(bb)
        out["bottom_blueprint"] = {"clock": bb.clock(), "snapshot_id": json.loads((BLUEPRINT_DIR / "shared_context" / "latest.json").read_text())["snapshot_id"]}
    except Exception as e:  # noqa: BLE001
        out["bottom_blueprint"] = {"error": str(e)[:120]}
    try:
        md = json.loads((MARKET_DIRECTION_DIR / "shared_context" / "market_direction" / "latest.json").read_text())
        out["market_direction"] = {k: md.get(k) for k in ("snapshot_id", "status", "generated_at", "regime", "final_call")}
    except Exception:
        out["market_direction"] = {"status": "MISSING"}
    return out


def liquidity(census: dict | None, cfg: dict) -> dict:
    if not census or not census.get("best"):
        return {"tier": None, "note": "no priced pool found"}
    best = census["best"]
    pool = best["liquidity_usd"]
    t = cfg["liquidity_tiers"]
    tier = [name for name, lo in t["pool_usd"] if pool >= lo][-1]
    return {"main_pool": {"pair": best["pair"], "dex": best["dex"], "liquidity_usd": round(pool), "url": best.get("url")},
            "total_liquidity_usd": round(census["liquidity_usd"]), "pairs_counted": census["counted"],
            "pairs_excluded_as_suspect": census["excluded_as_suspect"],
            "depth_2pct_estimate_usd": round(pool * 0.004975),
            "depth_method": "ESTIMATE: constant-product formula on the main pool (≈0.5% of TVL). Wrong for concentrated-liquidity pools. Not used for the tier.",
            "depth_2pct_measured_usd": None, "tier": tier, "tier_axis": "pool size (no measured depth)"}


def defillama_match(symbol: str, name: str | None, cg_id: str | None, h: Health) -> dict | None:
    protos = h.run("defillama", marketdata.defillama, "/protocols", agent=AGENT) or []
    best = None
    for p in protos:
        score = 0
        if cg_id and p.get("gecko_id") == cg_id:
            score = 3
        elif (p.get("symbol") or "").upper() == symbol and symbol not in ("-", ""):
            score = 2
        elif name and (p.get("name") or "").lower() == name.lower():
            score = 1
        if score and (not best or score > best[0] or (score == best[0] and (p.get("tvl") or 0) > (best[1].get("tvl") or 0))):
            best = (score, p)
    if not best:
        return None
    p = best[1]
    out = {"match": {3: "gecko_id", 2: "symbol", 1: "name"}[best[0]], "name": p.get("name"), "slug": p.get("slug"), "category": p.get("category"),
           "chains": p.get("chains"), "tvl": p.get("tvl"), "change_1d": p.get("change_1d"), "change_7d": p.get("change_7d"), "change_1m": p.get("change_1m"),
           "url": f"https://defillama.com/protocol/{p.get('slug')}"}
    fees = h.run("defillama_fees", marketdata.defillama, f"/summary/fees/{p.get('slug')}?dataType=dailyFees", agent=AGENT)
    if fees:
        out["fees"] = {"24h": fees.get("total24h"), "7d": fees.get("total7d"), "30d": fees.get("total30d")}
    return out


def btc_benchmark(asset: dict, census: dict | None, coin: dict | None, cfg: dict, h: Health) -> dict:
    """BTC Excess Return = token return − BTC return, percentage points, over the SAME period:
    halving → now, or first trading day → now for post-halving assets (the two lenses coincide then)."""
    halving = date.fromisoformat(cfg["btc_benchmark"]["halving_date"])
    first = None
    if census and census.get("oldest_pair_created_ms"):
        first = datetime.fromtimestamp(census["oldest_pair_created_ms"] / 1000, timezone.utc).date()
    if coin and coin.get("genesis_date"):
        g = date.fromisoformat(coin["genesis_date"])
        first = min(first, g) if first else g
    start = max(halving, first) if first else halving
    out = {"window_start": start.isoformat(), "window_rule": "halving→now, or first trading day→now if born after the halving", "method": None}
    now_px = (census or {}).get("price_usd") or ((coin or {}).get("market_data") or {}).get("current_price", {}).get("usd")
    btc_start = h.run("btc_history", marketdata.coinbase_daily_close, "BTC", start.isoformat(), agent=AGENT)
    btc_now = h.run("btc_price", marketdata.btc_spot, agent=AGENT)
    tok_start = None
    best = (census or {}).get("best")
    if best and asset["chain"] in chains.CHAINS:
        candles = h.run("geckoterminal_ohlcv", marketdata.ohlcv, asset["chain"], best["pair"], asset["contract"], "day", 1000, agent=AGENT) or []
        on_or_after = [c for c in candles if datetime.fromtimestamp(c["timestamp"], timezone.utc).date() >= start]
        if on_or_after:
            tok_start = on_or_after[0]["close"]
            out["method"] = "token: GeckoTerminal daily close of the main pool; BTC: Coinbase daily close"
            out["token_start_date"] = datetime.fromtimestamp(on_or_after[0]["timestamp"], timezone.utc).date().isoformat()
    if tok_start is None and coin:
        rng = h.run("coingecko_history", marketdata.coingecko,
                    f"/coins/{coin['id']}/market_chart/range?vs_currency=usd&from={int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp())}"
                    f"&to={int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp()) + 3 * 86400}", agent=AGENT, ttl_s=86400)
        if rng and rng.get("prices"):
            tok_start = rng["prices"][0][1]
            out["method"] = "token: CoinGecko market_chart/range; BTC: Coinbase daily close"
    if tok_start and now_px and btc_start and btc_now:
        tr = (float(now_px) / tok_start - 1) * 100
        br = (btc_now[0] / btc_start - 1) * 100
        out.update(token_return_pct=round(tr, 2), btc_return_pct=round(br, 2), excess_pp=round(tr - br, 2), outperformed_btc=tr > br)
    else:
        out["unavailable"] = ("missing: " + ", ".join(k for k, v in (("token start price", tok_start), ("token price now", now_px),
                                                                       ("BTC start price", btc_start), ("BTC now", btc_now)) if not v)
                              + " (history >365d needs a CoinGecko Pro key for CEX-only coins)")
    return out


def meta_context(categories: list[str]) -> dict | None:
    try:
        st = json.loads((sub("meta") / "state.json").read_text(encoding="utf-8"))
    except Exception:
        return None
    cats = {c.lower() for c in categories}
    hits = [m for m in st.get("metas", []) if any(k in cats for k in (m.get("cg_categories_lc") or []))]
    return {"as_of": st.get("updated_at"), "matching_metas": hits[:5], "top_metas_daily": st.get("top", {}).get("daily", [])[:8]}


def collect(query_s: str, chain_arg: str | None = None, pick: int | None = None) -> dict:
    cfg = load_config()
    h = Health()
    q = parse_query(query_s, chain_arg)
    ident = resolve_identity(q, cfg, h)
    chosen = ident["chosen"]
    if pick:
        if not 1 <= pick <= len(ident["candidates"]):
            raise SystemExit(f"--pick must be 1..{len(ident['candidates'])}")
        chosen = ident["candidates"][pick - 1]
        ident["status"] = "VERIFIED" if chosen["verified"] else "UNRESOLVED"
        ident["picked_by_beekeeper"] = pick
    ev = {"collected_at": now_iso(), "query": q, "identity": {k: v for k, v in ident.items() if k != "chosen"}, "chosen": chosen}
    ev["cycle"] = cycle_context(cfg, h)
    if chosen:
        ck, ca = chosen["chain"], chosen["contract"]
        census = h.run("dexscreener", marketdata.dexscreener_token, ck, ca, agent=AGENT) if ck in chains.CHAINS else None
        coin = None
        cid = chosen.get("coingecko_id") or chosen.get("coingecko_id_from_gt")
        if cid:
            coin = h.run("coingecko", marketdata.coingecko, f"/coins/{cid}?localization=false&tickers=false&community_data=false&developer_data=false", agent=AGENT)
        md = (coin or {}).get("market_data") or {}
        ev["market"] = {
            "price_usd": (census or {}).get("price_usd") or (md.get("current_price") or {}).get("usd"),
            "market_cap_usd": (md.get("market_cap") or {}).get("usd"), "fdv_usd": (md.get("fully_diluted_valuation") or {}).get("usd"),
            "volume_24h_usd": (md.get("total_volume") or {}).get("usd") or chosen.get("ds_volume_24h"),
            "ath": {"usd": (md.get("ath") or {}).get("usd"), "date": (md.get("ath_date") or {}).get("usd"), "from_ath_pct": (md.get("ath_change_percentage") or {}).get("usd")},
            "atl": {"usd": (md.get("atl") or {}).get("usd"), "date": (md.get("atl_date") or {}).get("usd")},
            "circulating_supply": md.get("circulating_supply"), "total_supply": md.get("total_supply"), "max_supply": md.get("max_supply"),
            "price_change_pct": {k: md.get(f"price_change_percentage_{k}") for k in ("24h", "7d", "30d", "1y")},
            "dexscreener": census, "coingecko": {"id": cid, "url": f"https://www.coingecko.com/en/coins/{cid}" if cid else None,
                                                  "categories": (coin or {}).get("categories"), "genesis_date": (coin or {}).get("genesis_date"),
                                                  "homepage": ((coin or {}).get("links") or {}).get("homepage"),
                                                  "twitter": ((coin or {}).get("links") or {}).get("twitter_screen_name"),
                                                  "description": (((coin or {}).get("description") or {}).get("en") or "")[:1500]},
            "geckoterminal": chosen.get("gt_info"),
        }
        ev["liquidity"] = liquidity(census, cfg)
        ev["defillama"] = defillama_match(chosen["symbol"] or "", chosen.get("name"), cid, h)
        ev["coinbase"] = h.run("coinbase", marketdata.coinbase_product, chosen["symbol"] or "", agent=AGENT)
        if ev["coinbase"]:
            ev["coinbase"]["caution"] = "Coinbase lists a product with this TICKER — confirm it is the same asset before using it as evidence"
        if ck in chains.CHAINS and chains.get(ck).get("chain_id") and chains.get(ck).get("evm"):
            ev["security"] = h.run("goplus", marketdata.goplus_security, ck, ca, agent=AGENT)
        ev["btc_benchmark"] = btc_benchmark(chosen, census, coin, cfg, h)
        ev["meta"] = meta_context((coin or {}).get("categories") or (chosen.get("gt_info") or {}).get("categories") or [])
    for k in ("market", "liquidity", "defillama", "coinbase", "security", "btc_benchmark"):
        if chosen and ev.get(k) in (None, {}):
            h.gaps.append(f"{k}: no data (see source_health — a broken source is not the same as 'none exists')")
    ev["source_health"] = h.sources
    ev["gaps"] = h.gaps
    return ev


def scorecard_template(ev: dict) -> dict:
    """Pre-filled with facts; every judgment is left null for the researcher (Claude) to fill WITH evidence."""
    c = ev.get("chosen") or {}
    j = lambda mx: {"score": None, "max": mx, "evidence": [], "note": ""}  # noqa: E731
    return {
        "_how_to": "Fill every null. Each score needs >=1 evidence item {\"source\": url-or-name, \"quote\": ctrl-F-able text}. Unknown = say so in note and score conservatively; never invent. Then: python score.py finalize <this file>",
        "evidence_file": None,
        "asset": {"symbol": c.get("symbol"), "name": c.get("name"), "chain": c.get("chain"), "contract": c.get("contract"),
                  "identity_status": ev["identity"]["status"], "identity_sources": c.get("sources"), "decoys": [x["contract"] for x in ev["identity"]["candidates"]
                                                                                                                if x is not c and x.get("chain") == c.get("chain")],
                  "coingecko_url": ((ev.get("market") or {}).get("coingecko") or {}).get("url"), "website": (c.get("official_sites") or [None])[0],
                  "canonical_pool": ((ev.get("liquidity") or {}).get("main_pool") or {}).get("pair"), "discovery": False},
        "gate": {"ease_of_use": j(10), "hair_on_fire": j(10), "exclusivity": j(10)},
        "cycle": {"regime": None, "regime_options": ["Bull Expansion", "Late Expansion", "Distribution / Transition", "Bear Decline",
                                                     "Capitulation / Bottom Watch", "Recovery / Early Expansion", "Mania / Late Cycle"],
                  "interpretation": None, "broad_or_selective": None, "rotation": None},
        "narrative": {"primary": None, "secondary": [], "perennial_roots": [], "constellation_members": [],
                      "lineage": {"perennial_root": None, "prior_crypto_narrative": None, "current_mutation": None, "asset_expression": None},
                      "status": None, "status_options": ["Emerging", "Rising", "Mature", "Fading", "Revived", "Dead"], "catalysts": []},
        "narrative_power": {k: j(2) for k in ("one_sentence", "perennial_root", "tribe", "face_or_mystery", "fear_envy", "repetition_machine", "action_script")},
        "stage": {"stage": None, "revival": False, "revival_catalyst": None, "evidence": []},
        "curve": {"label": None, "options": ["declining", "flat", "early_rising", "rising", "accelerating", "peaking", "fading", "revival"], "evidence": []},
        "constellation": {**j(5), "expanding": None, "external_catalysts": [], "sharing_assets": []},
        "archetypes": [], "archetype_options": ["Anchor", "Crashed Champion", "Newborn Narrative", "Toll-Taker", "Revival", "Borrowed / Piggyback", "Meme Mutation", "Dead Narrative"],
        "asset_expression": {k: j(2) for k in ("narrative_token_fit", "category_leadership", "distribution_reach", "product_reality", "token_capture")},
        "product_quality": j(10),
        "liquidity": {"tier": (ev.get("liquidity") or {}).get("tier"), "trajectory": j(5), "cycle_relative": None,
                      "cycle_relative_options": ["Underexposed / early", "Normal", "Broadly discovered", "Mature / saturated"]},
        "narrative_conversion": {"state": None, "options": ["None", "Emerging", "Confirmed", "Strong", "Reflexive"], "evidence": []},
        "team": {"founder": {"name": None, "role": "Founder", "high": None, "medium": None, "low": None, "unverifiable": False, "sources": []},
                 "others": [], "_person_score": "high 0-5 + medium 0-3 + low 0-2 = 0-10; prior track record only; pseudonymous = unverifiable (scores 0, flagged)"},
        "smart_money_fit": j(6),
        "security_score": None, "security_note": "0-100: your read of GoPlus (evidence.security) + audits + contract controls. null = unverified (the Trader Bee then asks you before buying).",
        "final_status": None, "final_status_options": ["EARLY ASYMMETRIC", "STRONG ACCUMULATION", "WATCH", "MATURE / LATE", "DEAD NARRATIVE", "SPECULATIVE NARRATIVE"],
        "risk_flags": [], "recheck_triggers": [],
        "decision": {"call": None, "call_options": ["BUY", "WATCH", "PASS"], "why": None},
        "one_sentence_overview": None,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("query", help="TICKER, 'TICKER | chain', or a contract address")
    p.add_argument("--chain", default=None)
    p.add_argument("--pick", type=int, default=None, help="choose a candidate number when identity is AMBIGUOUS/UNRESOLVED")
    p.add_argument("--discovery", action="store_true", help="this token came from the Discovery Scout queue")
    a = p.parse_args()
    ev = collect(a.query, a.chain, a.pick)
    c = ev.get("chosen") or {}
    run = f"{(c.get('symbol') or ev['query'].get('symbol') or 'UNKNOWN')}-{c.get('chain', 'x')}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    d = sub("research", re.sub(r"[^A-Za-z0-9_.-]", "_", run))
    (d / "evidence.json").write_text(json.dumps(ev, indent=1, default=str), encoding="utf-8")
    sc = scorecard_template(ev)
    sc["evidence_file"] = str(d / "evidence.json")
    sc["asset"]["discovery"] = bool(a.discovery)
    (d / "scorecard.json").write_text(json.dumps(sc, indent=1), encoding="utf-8")
    print(json.dumps({"run_dir": str(d), "identity": ev["identity"]["status"],
                      "candidates": [{"#": i + 1, "chain": x["chain"], "contract": x["contract"], "symbol": x["symbol"], "sources": x["sources"],
                                      "verified": x["verified"], "liquidity_usd": round(x["ds_liquidity_usd"])} for i, x in enumerate(ev["identity"]["candidates"][:8])],
                      "liquidity_tier": (ev.get("liquidity") or {}).get("tier"), "btc_benchmark": ev.get("btc_benchmark"),
                      "source_health": ev["source_health"], "gaps": ev["gaps"]}, indent=1, default=str))
    if ev["identity"]["status"] != "VERIFIED":
        print(f"\nIDENTITY {ev['identity']['status']}: research must stop here or the beekeeper picks a candidate with --pick N "
              "(then verify it yourself with the explorer + the official site).", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
