"""Shared read-only market data for Hive agents (GeckoTerminal / CoinGecko onchain, DexScreener,
GoPlus). No wallet, no signing — this module cannot trade.

Rules carried over from the trading terminal's FIXES-LOG:
  * Poison-pair guard: a pair whose price is >5x or <0.2x the median of the token's pairs is
    excluded before it can set a price or a liquidity figure (FIXES-LOG AD).
  * DexScreener priceUsd is the BASE token's price. If our token is the quote side, its price
    is priceUsd / priceNative.
  * A failed source raises NetError. It is reported as broken, never read as "no data".
"""
from __future__ import annotations

from . import chains, env_keys, net

GT = "https://api.geckoterminal.com/api/v2"
CG_PRO = "https://pro-api.coingecko.com/api/v3/onchain"
CG_DEMO = "https://api.coingecko.com/api/v3/onchain"


def _onchain(path: str, agent: str, operation: str, ttl_s: float = 0):
    """CoinGecko onchain (keyed, higher limits) when COINGECKO_API_KEY is set, else keyless GT."""
    key = env_keys.get("COINGECKO_API_KEY")
    if key:
        plan = (env_keys.get("COINGECKO_API_PLAN") or "pro").lower()
        base, hdr = (CG_DEMO, "x-cg-demo-api-key") if plan == "demo" else (CG_PRO, "x-cg-pro-api-key")
        try:
            return net.fetch_json(base + path, headers={hdr: key}, ttl_s=ttl_s, agent=agent, operation=operation)
        except net.NetError as e:
            if e.status not in (401, 403, 404):
                raise
            # key/plan mismatch: fall through to keyless GT (and it shows in Queen usage as a failure)
    return net.fetch_json(GT + path, ttl_s=ttl_s, agent=agent, operation=operation)


def _addr_from_gt_id(gid: str | None) -> str:
    return (gid or "").split("_", 1)[-1].lower()


def pool_price(chain: str, pool: str, token: str, agent: str = "hive") -> dict:
    """Live USD price of `token` in `pool` from GT/CG onchain."""
    c = chains.get(chain)
    if not c:
        raise ValueError(f"unknown chain {chain}")
    j = _onchain(f"/networks/{c['gt_network']}/pools/{pool.lower()}", agent, "pool_price", ttl_s=30)
    d = (j or {}).get("data") or {}
    a = d.get("attributes") or {}
    rel = d.get("relationships") or {}
    base = _addr_from_gt_id(((rel.get("base_token") or {}).get("data") or {}).get("id"))
    quote = _addr_from_gt_id(((rel.get("quote_token") or {}).get("data") or {}).get("id"))
    t = token.lower()
    if t == base:
        px = a.get("base_token_price_usd")
    elif t == quote:
        px = a.get("quote_token_price_usd")
    else:
        raise net.NetError(f"pool {pool} does not contain token {token}")
    if px is None:
        raise net.NetError(f"pool {pool}: no USD price")
    return {"price_usd": float(px), "reserve_usd": float(a.get("reserve_in_usd") or 0), "pool": pool.lower(),
            "source": "geckoterminal"}


def ohlcv(chain: str, pool: str, token: str, timeframe: str = "day", limit: int = 1000, agent: str = "hive",
          ttl_s: float = 6 * 3600) -> list[dict]:
    """Candles (oldest first) priced in `token` (not necessarily the pool's base token)."""
    c = chains.get(chain)
    j = _onchain(f"/networks/{c['gt_network']}/pools/{pool.lower()}/ohlcv/{timeframe}?limit={limit}&currency=usd"
                 f"&token={token.lower()}", agent, "ohlcv", ttl_s=ttl_s)
    rows = (((j or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
    out = [{"timestamp": int(r[0]), "open": float(r[1]), "high": float(r[2]), "low": float(r[3]),
            "close": float(r[4]), "volume": float(r[5] or 0)} for r in rows if r and len(r) >= 6]
    return sorted(out, key=lambda x: x["timestamp"])


def top_pool(chain: str, token: str, agent: str = "hive") -> dict | None:
    """Best pool for a token by reserve, poison-guarded. None when no pool exists."""
    c = chains.get(chain)
    j = _onchain(f"/networks/{c['gt_network']}/tokens/{token.lower()}/pools?page=1", agent, "token_pools", ttl_s=3600)
    rows = []
    for d in (j or {}).get("data") or []:
        a = d.get("attributes") or {}
        rel = d.get("relationships") or {}
        base = _addr_from_gt_id(((rel.get("base_token") or {}).get("data") or {}).get("id"))
        px = a.get("base_token_price_usd") if base == token.lower() else a.get("quote_token_price_usd")
        if px is None:
            continue
        rows.append({"pool": (a.get("address") or "").lower(), "price_usd": float(px),
                     "reserve_usd": float(a.get("reserve_in_usd") or 0)})
    rows = guard(rows, "price_usd")
    return max(rows, key=lambda r: r["reserve_usd"]) if rows else None


def guard(rows: list[dict], key: str) -> list[dict]:
    """The poison-pair guard: drop rows priced >5x or <0.2x the median (needs >=2 priced rows)."""
    px = sorted(r[key] for r in rows if r.get(key) and r[key] > 0)
    if len(px) < 2:
        return [r for r in rows if r.get(key) and r[key] > 0]
    med = px[len(px) // 2]
    return [r for r in rows if r.get(key) and 0.2 < r[key] / med < 5]


def dexscreener_token(chain: str, token: str, agent: str = "hive") -> dict:
    """Pool census for a token on one chain: counted (post-guard) pairs, total liquidity, best
    pair, price (quote-side aware), pair age. Raises NetError when DexScreener is down."""
    c = chains.get(chain)
    j = net.fetch_json(f"https://api.dexscreener.com/latest/dex/tokens/{token}", agent=agent,
                       operation="token_pairs", ttl_s=20)
    t = token.lower()
    rows = []
    for p in (j or {}).get("pairs") or []:
        if (p.get("chainId") or "").lower() != c["dexscreener"]:
            continue
        pu, pn = float(p.get("priceUsd") or 0), float(p.get("priceNative") or 0)
        if (p.get("baseToken") or {}).get("address", "").lower() == t:
            px = pu
        elif (p.get("quoteToken") or {}).get("address", "").lower() == t and pu > 0 and pn > 0:
            px = pu / pn
        else:
            continue
        rows.append({"pair": (p.get("pairAddress") or "").lower(), "dex": p.get("dexId"), "price_usd": px,
                     "liquidity_usd": float((p.get("liquidity") or {}).get("usd") or 0),
                     "volume_24h": float((p.get("volume") or {}).get("h24") or 0),
                     "created_at_ms": p.get("pairCreatedAt"), "url": p.get("url"),
                     "symbol": (p.get("baseToken") or {}).get("symbol") if (p.get("baseToken") or {}).get("address", "").lower() == t else (p.get("quoteToken") or {}).get("symbol")})
    sane = guard(rows, "price_usd")
    best = max(sane, key=lambda r: r["liquidity_usd"]) if sane else None
    created = [r["created_at_ms"] for r in sane if r.get("created_at_ms")]
    return {"scanned": len(rows), "counted": len(sane), "excluded_as_suspect": len(rows) - len(sane),
            "liquidity_usd": sum(r["liquidity_usd"] for r in sane), "best": best,
            "price_usd": best["price_usd"] if best else None,
            "oldest_pair_created_ms": min(created) if created else None, "pairs": sane[:10]}


def dexscreener_symbol_clones(chain: str, symbol: str, contract: str, agent: str = "hive") -> list[dict]:
    """Same-ticker tokens on the same chain at a DIFFERENT contract (the VEX/DRB/WOOD failure)."""
    c = chains.get(chain)
    j = net.fetch_json(f"https://api.dexscreener.com/latest/dex/search?q={symbol}", agent=agent,
                       operation="symbol_search", ttl_s=600)
    seen = {}
    for p in (j or {}).get("pairs") or []:
        if (p.get("chainId") or "").lower() != c["dexscreener"]:
            continue
        b = p.get("baseToken") or {}
        if (b.get("symbol") or "").upper() == symbol.upper() and (b.get("address") or "").lower() != contract.lower():
            a = b["address"].lower()
            seen[a] = max(seen.get(a, 0), float((p.get("liquidity") or {}).get("usd") or 0))
    return [{"contract": a, "liquidity_usd": v} for a, v in sorted(seen.items(), key=lambda x: -x[1])]


def goplus_security(chain: str, token: str, agent: str = "hive") -> dict | None:
    """GoPlus token security (keyless). None when GoPlus does not cover the chain/token —
    that is 'unverifiable', which the caller must treat as a finding, not a pass."""
    c = chains.get(chain)
    j = net.fetch_json(f"https://api.gopluslabs.io/api/v1/token_security/{c['chain_id']}?contract_addresses={token.lower()}",
                       agent=agent, operation="token_security", ttl_s=3600)
    res = ((j or {}).get("result") or {}).get(token.lower())
    if not res:
        return None
    flag = lambda k: str(res.get(k, "0")) == "1"  # noqa: E731
    tax = lambda k: float(res.get(k) or 0)  # noqa: E731
    return {
        "is_honeypot": flag("is_honeypot"), "cannot_sell_all": flag("cannot_sell_all"),
        "is_blacklisted": flag("is_blacklisted"), "transfer_pausable": flag("transfer_pausable"),
        "owner_change_balance": flag("owner_change_balance"), "hidden_owner": flag("hidden_owner"),
        "is_mintable": flag("is_mintable"), "buy_tax": tax("buy_tax"), "sell_tax": tax("sell_tax"),
        "is_open_source": flag("is_open_source"), "source": "goplus",
    }


# ------------------------------------------------------------------ research adapters (all read-only)
CG_PUBLIC = "https://api.coingecko.com/api/v3"


def coingecko(path: str, agent: str = "hive", ttl_s: float = 300):
    """CoinGecko REST (not on-chain). Pro/Demo key when set; otherwise the keyless public API (paced 2.6 s)."""
    key = env_keys.get("COINGECKO_API_KEY")
    if key:
        plan = (env_keys.get("COINGECKO_API_PLAN") or "pro").lower()
        base, hdr = (CG_PUBLIC, "x-cg-demo-api-key") if plan == "demo" else ("https://pro-api.coingecko.com/api/v3", "x-cg-pro-api-key")
        try:
            return net.fetch_json(base + path, headers={hdr: key}, ttl_s=ttl_s, agent=agent, operation="coingecko")
        except net.NetError as e:
            if e.status not in (401, 403):
                raise
    return net.fetch_json(CG_PUBLIC + path, ttl_s=ttl_s, agent=agent, operation="coingecko")


def defillama(path: str, agent: str = "hive", ttl_s: float = 1800):
    return net.fetch_json("https://api.llama.fi" + path, ttl_s=ttl_s, agent=agent, operation="defillama", timeout=30)


def coinbase_product(symbol: str, agent: str = "hive") -> dict | None:
    """Coinbase Exchange public market data (keyless). None = not listed as <SYMBOL>-USD."""
    try:
        st = net.fetch_json(f"https://api.exchange.coinbase.com/products/{symbol.upper()}-USD/stats", ttl_s=300, agent=agent, operation="coinbase_stats")
    except net.NetError as e:
        if e.status in (404, 400):
            return None
        raise
    return {"product": f"{symbol.upper()}-USD", "last": float(st.get("last") or 0) or None, "volume_24h_base": float(st.get("volume") or 0),
            "high_24h": float(st.get("high") or 0) or None, "low_24h": float(st.get("low") or 0) or None}


def coinbase_daily_close(symbol: str, day: str, agent: str = "hive") -> float | None:
    """Close of <SYMBOL>-USD on a UTC day (YYYY-MM-DD) from Coinbase daily candles. None if not listed then."""
    try:
        rows = net.fetch_json(f"https://api.exchange.coinbase.com/products/{symbol.upper()}-USD/candles?granularity=86400&start={day}T00:00:00Z&end={day}T23:59:59Z",
                              ttl_s=86400, agent=agent, operation="coinbase_candles")
    except net.NetError as e:
        if e.status in (404, 400):
            return None
        raise
    return float(rows[0][4]) if rows else None  # [time, low, high, open, close, volume]


def btc_spot(agent: str = "hive") -> tuple[float, str]:
    """BTC/USD now: Coinbase first, CoinGecko fallback. Returns (price, source)."""
    try:
        t = net.fetch_json("https://api.exchange.coinbase.com/products/BTC-USD/ticker", ttl_s=60, agent=agent, operation="btc_ticker")
        return float(t["price"]), "coinbase"
    except (net.NetError, KeyError, TypeError, ValueError):
        j = coingecko("/simple/price?ids=bitcoin&vs_currencies=usd", agent=agent, ttl_s=60)
        return float(j["bitcoin"]["usd"]), "coingecko"


def blockscout_token(chain: str, token: str, agent: str = "hive") -> dict | None:
    """Explorer confirmation of a contract (keyless Blockscout). None = chain has no Blockscout configured."""
    c = chains.get(chain)
    if not c or not c.get("blockscout"):
        return None
    try:
        j = net.fetch_json(f"{c['blockscout']}/tokens/{token}", ttl_s=3600, agent=agent, operation="explorer_token")
    except net.NetError as e:
        if e.status == 404:
            return {"exists": False}
        raise
    return {"exists": True, "name": j.get("name"), "symbol": j.get("symbol"), "decimals": j.get("decimals"), "holders": j.get("holders") or j.get("holders_count"),
            "total_supply": j.get("total_supply"), "type": j.get("type")}


def geckoterminal_token_info(chain: str, token: str, agent: str = "hive") -> dict | None:
    c = chains.get(chain)
    try:
        j = _onchain(f"/networks/{c['gt_network']}/tokens/{token}/info", agent, "token_info", ttl_s=3600)
    except net.NetError as e:
        if e.status == 404:
            return None
        raise
    a = ((j or {}).get("data") or {}).get("attributes") or {}
    return {"name": a.get("name"), "symbol": a.get("symbol"), "websites": a.get("websites") or [], "twitter": a.get("twitter_handle"),
            "telegram": a.get("telegram_handle"), "discord": a.get("discord_url"), "description": (a.get("description") or "")[:1500],
            "gt_score": a.get("gt_score"), "coingecko_coin_id": a.get("coingecko_coin_id"), "categories": a.get("categories") or [],
            "holders": (a.get("holders") or {}).get("count")}


def dexscreener_search(query: str, agent: str = "hive") -> list[dict]:
    j = net.fetch_json(f"https://api.dexscreener.com/latest/dex/search?q={query}", ttl_s=120, agent=agent, operation="search")
    return (j or {}).get("pairs") or []
