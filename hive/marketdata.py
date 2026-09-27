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

from . import chains, net, secrets

GT = "https://api.geckoterminal.com/api/v2"
CG_PRO = "https://pro-api.coingecko.com/api/v3/onchain"
CG_DEMO = "https://api.coingecko.com/api/v3/onchain"


def _onchain(path: str, agent: str, operation: str, ttl_s: float = 0):
    """CoinGecko onchain (keyed, higher limits) when COINGECKO_API_KEY is set, else keyless GT."""
    key = secrets.get("COINGECKO_API_KEY")
    if key:
        plan = (secrets.get("COINGECKO_API_PLAN") or "pro").lower()
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
