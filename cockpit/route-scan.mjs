// ROUTE SCAN — READ-ONLY best-execution transparency for the cockpit UI (2026-07-31).
//
// WHY THIS EXISTS
// Jesse: "when I go to execute a trade, I need it to show me basically like a quick scan
// because this has to be satisfying to use... I want people to really know that they're
// getting the best price possible... say, scanned 56 pools for this token, and these are
// your best routing options."
//
// swap.mjs has raced 1inch v6 vs KyberSwap since 2026-07-22 and executes the winner, but it
// printed the result to a console nobody sees and threw the route away. This module surfaces
// the SAME work to the screen.
//
// HARD RULE, stated because these zips ship to Jesse's boss and to members:
// EVERY NUMBER HERE IS REAL AND CLICK-THROUGH VERIFIABLE. The pool count is the actual
// DexScreener pair count. The quotes are live quotes from both aggregators. The winner and
// its edge are computed from those two quotes. The route hops are Kyber's own routeSummary.
// If a source fails we report the failure and mark the field unavailable. We NEVER invent or
// pad a "scanned N pools" number — a fabricated progress counter is a number that lies to
// the user, and it would destroy the exact trust this feature exists to build.
//
// SAFETY: no wallet, no signer, no approvals, no transaction of any kind. It cannot execute.
// It only reads registry.json, DexScreener, and the two aggregator quote endpoints.

import { readFileSync } from "node:fs";

// Native parseUnits/formatUnits so this module has ZERO dependencies. ethers lives in
// module/node_modules and is not resolvable from cockpit/, and pulling it in just for two
// pure-BigInt helpers would be a needless coupling for a read-only display module.
function parseUnits(value, decimals) {
  const s = String(value).trim();
  if (!/^\d*\.?\d*$/.test(s) || s === "" || s === ".") throw new Error(`bad numeric string: ${value}`);
  const [whole = "0", frac = ""] = s.split(".");
  const f = (frac + "0".repeat(decimals)).slice(0, decimals);
  if (frac.length > decimals) {
    // more precision than the token supports: truncate, never round up into a bigger trade
    return BigInt(whole + f);
  }
  return BigInt(whole + f);
}
function formatUnits(value, decimals) {
  const v = BigInt(value);
  const neg = v < 0n;
  const abs = neg ? -v : v;
  const base = 10n ** BigInt(decimals);
  const whole = abs / base;
  const frac = (abs % base).toString().padStart(decimals, "0").replace(/0+$/, "");
  return `${neg ? "-" : ""}${whole}${frac ? "." + frac : ""}`;
}

const MOD = new URL("../module/", import.meta.url);
const config = JSON.parse(readFileSync(new URL("./config.json", MOD), "utf8"));
const registry = JSON.parse(readFileSync(new URL("./registry.json", MOD), "utf8"));
let ONEINCH_KEY = null;
try { ONEINCH_KEY = readFileSync(new URL("./.env", MOD), "utf8").match(/ONEINCH_API_KEY=(.+)/)?.[1]?.trim() || null; } catch { }

const KH = { "x-client-id": "coinpicks-terminal", Accept: "application/json" };
const round = (n, d = 2) => (n == null || !Number.isFinite(n) ? null : Math.round(n * 10 ** d) / 10 ** d);

// ---------- real pool census from DexScreener, with the poison-pair guard ----------
// Same guard as swap.mjs and datasource.mjs bestPair (FIXES-LOG AD): a fake pair claiming
// huge liquidity must never be counted as real depth. We report BOTH numbers honestly:
// how many pairs exist, and how many survived the sanity filter.
async function poolCensus(contract, mainPool) {
  const out = { scanned: null, counted: null, excludedAsSuspect: 0, totalLiqUsd: null, top: [], source: "dexscreener", error: null };
  if (!contract) { out.error = "no contract"; return out; }
  try {
    const r = await fetch("https://api.dexscreener.com/latest/dex/tokens/" + contract, { signal: AbortSignal.timeout(12_000) });
    if (!r.ok) throw new Error("dexscreener HTTP " + r.status);
    const pairs = (await r.json())?.pairs || [];
    out.scanned = pairs.length;
    const px = pairs.map(p => Number(p.priceUsd)).filter(v => v > 0).sort((a, b) => a - b);
    const med = px.length ? px[Math.floor(px.length / 2)] : 0;
    const sane = (px.length >= 2 && med > 0)
      ? pairs.filter(p => { const v = Number(p.priceUsd); return v > 0 && v / med < 5 && v / med > 0.2; })
      : pairs;
    out.counted = sane.length;
    out.excludedAsSuspect = pairs.length - sane.length;
    out.totalLiqUsd = round(sane.reduce((a, p) => a + (p.liquidity?.usd || 0), 0), 0);
    out.top = sane
      .slice()
      .sort((a, b) => (b.liquidity?.usd || 0) - (a.liquidity?.usd || 0))
      .slice(0, 6)
      .map(p => ({
        dex: p.dexId || "unknown",
        pairAddress: p.pairAddress || null,
        isRegistryMainPool: !!(mainPool && (p.pairAddress || "").toLowerCase() === String(mainPool).toLowerCase()),
        liqUsd: round(p.liquidity?.usd ?? null, 0),
        vol24Usd: round(p.volume?.h24 ?? null, 0),
        priceUsd: p.priceUsd != null ? Number(p.priceUsd) : null,
        url: p.url || null,   // click-through proof
      }));
  } catch (e) { out.error = String(e?.message || e).slice(0, 160); }
  return out;
}

// ---------- live quote: 1inch Classic Swap v6 ----------
async function quote1inch(chainId, srcC, dstC, amount) {
  const t0 = Date.now();
  if (!ONEINCH_KEY) return { venue: "1inch", ok: false, error: "no ONEINCH_API_KEY in module/.env", ms: 0 };
  try {
    const u = `https://api.1inch.dev/swap/v6.0/${chainId}/quote?src=${srcC}&dst=${dstC}&amount=${amount}&includeProtocols=true`;
    const r = await fetch(u, { headers: { Authorization: `Bearer ${ONEINCH_KEY}`, Accept: "application/json" }, signal: AbortSignal.timeout(12_000) });
    if (!r.ok) throw new Error(`HTTP ${r.status}: ${(await r.text()).slice(0, 120)}`);
    const j = await r.json();
    const raw = j.dstAmount ?? j.toAmount ?? null;
    if (raw == null) throw new Error("no dstAmount in response");
    // protocols comes back as [[[{name,part,fromTokenAddress,toTokenAddress}]]]
    const names = new Set();
    const walk = v => { if (Array.isArray(v)) v.forEach(walk); else if (v && v.name) names.add(v.name); };
    walk(j.protocols || []);
    return { venue: "1inch", ok: true, raw: String(raw), protocols: [...names].slice(0, 12), ms: Date.now() - t0 };
  } catch (e) { return { venue: "1inch", ok: false, error: String(e?.message || e).slice(0, 160), ms: Date.now() - t0 }; }
}

// ---------- live quote: KyberSwap Aggregator (also gives us the real route) ----------
async function quoteKyber(slug, srcC, dstC, amount) {
  const t0 = Date.now();
  if (!slug) return { venue: "kyber", ok: false, error: "no kyberSlug for this chain in config.json", ms: 0 };
  try {
    const u = `https://aggregator-api.kyberswap.com/${slug}/api/v1/routes?tokenIn=${srcC}&tokenOut=${dstC}&amountIn=${amount}`;
    const r = await fetch(u, { headers: KH, signal: AbortSignal.timeout(12_000) });
    if (!r.ok) throw new Error(`HTTP ${r.status}: ${(await r.text()).slice(0, 120)}`);
    const j = await r.json();
    if (j.code !== 0 || !j.data?.routeSummary) throw new Error(`code ${j.code}: ${String(j.message).slice(0, 120)}`);
    const rs = j.data.routeSummary;
    // rs.route = array of splits; each split is an ordered array of hops
    const splits = (rs.route || []).map(seq => (Array.isArray(seq) ? seq : [seq]).map(h => ({
      exchange: h.exchange || h.pool || "unknown",
      pool: h.pool || null,
      tokenIn: h.tokenIn || null,
      tokenOut: h.tokenOut || null,
    })));
    return {
      venue: "kyber", ok: true, raw: String(rs.amountOut),
      splits, splitCount: splits.length,
      hopCount: splits.reduce((a, s) => a + s.length, 0),
      exchanges: [...new Set(splits.flat().map(h => h.exchange))].slice(0, 12),
      gasUsd: rs.gasUsd != null ? round(Number(rs.gasUsd), 4) : null,
      ms: Date.now() - t0,
    };
  } catch (e) { return { venue: "kyber", ok: false, error: String(e?.message || e).slice(0, 160), ms: Date.now() - t0 }; }
}

/**
 * routeScan — read-only. Returns the real best-execution picture for a prospective trade.
 * @param {{srcTicker:string,dstTicker:string,usd?:number,qty?:string}} p
 */
export async function routeScan(p = {}) {
  const started = Date.now();
  const SRC = String(p.srcTicker || "").toUpperCase().replace(/^\$/, "");
  const DST = String(p.dstTicker || "").toUpperCase().replace(/^\$/, "");
  const src = registry.tokens?.[SRC], dst = registry.tokens?.[DST];

  if (!src?.contract || !dst?.contract) return { ok: false, error: `not in verified registry: ${!src?.contract ? SRC : DST}` };
  if (src.chainId !== dst.chainId) return { ok: false, error: "src and dst are on different chains" };
  if (src.dollarTrue === true && dst.dollarTrue === true) return { ok: false, error: "stable-to-stable is not a market trade" };
  // ETH-SPEND switch (mirrors swap.mjs, 2026-07-31): with config.ethSpend.enabled, the
  // chain's ETH (native sentinel or wrapped) may replace the stable as the funding leg.
  const ES = config.ethSpend || {};
  const gasMap = (ES.enabled === true && ES.gasTokens?.[String(src.chainId)]) || {};
  const gasSet = Object.values(gasMap);
  const srcIsGas = gasSet.includes(SRC), dstIsGas = gasSet.includes(DST);
  if (src.dollarTrue !== true && dst.dollarTrue !== true && !(srcIsGas !== dstIsGas))
    return { ok: false, error: "one leg must be the chain's dollar-true stable" + (ES.enabled === true ? " (or, ETH-SPEND switch, the chain's ETH on a market order)" : "") };

  const side = (src.dollarTrue === true || (dst.dollarTrue !== true && srcIsGas)) ? "buy" : "sell";
  const token = side === "buy" ? dst : src;          // the non-funding leg
  const fundingIsGas = side === "buy" ? (srcIsGas && src.dollarTrue !== true) : (dstIsGas && dst.dollarTrue !== true);
  const chainId = src.chainId;
  const chainCfg = Object.values(config.chains).find(c => c.chainId === chainId);

  // ---- size the input in src units (mirrors swap.mjs, but never reads a wallet) ----
  let amount, sizeNote = null;
  const census0 = await poolCensus(token.contract, token.mainPool);
  const midUsd = census0.top.find(t => t.isRegistryMainPool)?.priceUsd ?? census0.top[0]?.priceUsd ?? null;

  // funding-leg ETH price via the WRAPPED contract pools (the native sentinel has no pools).
  // DexScreener priceUsd is the BASE token's price; when WETH sits on the QUOTE side its
  // USD price is priceUsd / priceNative. Poison-guarded around the median like everything.
  let fundPx = 1;
  if (fundingIsGas) {
    const wrapped = registry.tokens?.[gasMap.wrapped];
    if (!wrapped?.contract) return { ok: false, error: `ETH-SPEND scan needs '${gasMap.wrapped}' in the registry to price ETH` };
    try {
      const eds = await (await fetch(`https://api.dexscreener.com/latest/dex/tokens/${wrapped.contract}`)).json();
      const w = wrapped.contract.toLowerCase();
      const cands = (eds.pairs || []).map(pp => {
        const pu = Number(pp.priceUsd), pn = Number(pp.priceNative);
        let px = null;
        if ((pp.baseToken?.address || "").toLowerCase() === w && pu > 0) px = pu;
        else if ((pp.quoteToken?.address || "").toLowerCase() === w && pu > 0 && pn > 0) px = pu / pn;
        return px != null && Number.isFinite(px) && px > 0 ? { px, liq: pp.liquidity?.usd || 0 } : null;
      }).filter(Boolean);
      const pxs = cands.map(c => c.px).sort((a, b) => a - b);
      const med = pxs.length ? pxs[Math.floor(pxs.length / 2)] : 0;
      const sane = (pxs.length >= 2 && med > 0) ? cands.filter(c => c.px / med < 5 && c.px / med > 0.2) : cands;
      fundPx = (sane.length ? sane : cands).sort((a, b) => b.liq - a.liq)[0]?.px;
    } catch { fundPx = null; }
    if (!(fundPx > 0)) return { ok: false, error: "ETH-SPEND scan needs a live ETH price; DexScreener returned none for the wrapped pools" };
  }
  try {
    if (side === "buy") {
      const usd = Number(p.usd);
      if (!(usd > 0)) return { ok: false, error: "buy scan needs a positive usd amount" };
      const srcUnits = fundingIsGas ? usd / fundPx : usd;
      amount = parseUnits(srcUnits.toFixed(Math.min(src.decimals, 12)), src.decimals);
      sizeNote = fundingIsGas ? `$${usd} of ${SRC} (≈${srcUnits.toFixed(6)} @ $${fundPx.toFixed(2)} live — ETH-SPEND)` : `$${usd} of ${SRC}`;
    } else if (p.qty != null && String(p.qty).trim() !== "") {
      amount = parseUnits(String(p.qty), src.decimals);
      sizeNote = `${p.qty} ${SRC}`;
    } else {
      const usd = Number(p.usd);
      if (!(usd > 0)) return { ok: false, error: "sell scan needs qty or usd" };
      if (!(midUsd > 0)) return { ok: false, error: "sell-by-usd scan needs a live pool price; DexScreener returned none" };
      amount = parseUnits((usd / midUsd).toFixed(Math.min(src.decimals, 12)), src.decimals);
      sizeNote = `~$${usd} of ${SRC} at the live pool mid`;
    }
  } catch (e) { return { ok: false, error: "sizing failed: " + String(e?.message || e).slice(0, 120) }; }

  // ---- race both aggregators, in parallel, read-only ----
  const [q1, qk] = await Promise.all([
    quote1inch(chainId, src.contract, dst.contract, amount.toString()),
    quoteKyber(chainCfg?.kyberSlug || null, src.contract, dst.contract, amount.toString()),
  ]);

  const human = q => (q.ok ? Number(formatUnits(BigInt(q.raw), dst.decimals)) : null);
  const o1 = human(q1), ok_ = human(qk);
  const live = [q1, qk].filter(q => q.ok);

  let winner = null, edgePct = null, loser = null;
  if (live.length) {
    const best = (ok_ != null && (o1 == null || ok_ > o1)) ? qk : q1;
    const other = best.venue === "kyber" ? q1 : qk;
    winner = best.venue;
    if (other.ok) {
      const bo = human(best), oo = human(other);
      if (bo > 0 && oo > 0) { edgePct = round((bo / oo - 1) * 100, 3); loser = other.venue; }
    }
  }

  // USD value of what comes OUT (Jesse 2026-07-31: "USD first, token amounts second" — a quote
  // shown only as 0.0xxx of the coin is unreadable). Sells pay out the dollar-true stable (≈$1
  // exact). Buys pay out the token: valued at the SAME live DexScreener pool mid the census just
  // pulled — an estimate, so the UI must render it with ≈, never as a promised fill.
  // buys: dst is the token (live pool mid). sells: dst is the stable ($1 exact) or, under
  // the ETH-SPEND switch, the chain's ETH (live fundPx — never the TOKEN's mid).
  const usdPerDstToken = dst.dollarTrue === true ? 1
    : side === "buy" ? (midUsd > 0 ? midUsd : null)
    : (fundingIsGas ? fundPx : null);
  const outUsd = v => (v != null && usdPerDstToken != null) ? round(v * usdPerDstToken, 2) : null;

  return {
    ok: live.length > 0,
    error: live.length ? null : "no venue produced a quote",
    scannedAt: new Date().toISOString(),
    elapsedMs: Date.now() - started,
    side, sizeNote,
    chain: { chainId, name: Object.entries(config.chains).find(([, c]) => c.chainId === chainId)?.[0] || String(chainId) },
    pair: { src: SRC, dst: DST, srcContract: src.contract, dstContract: dst.contract },
    token: { ticker: token.symbol || (side === "buy" ? DST : SRC), contract: token.contract, mainPool: token.mainPool || null, provisional: !!token.provisional },
    pools: census0,
    aggregatorsQueried: 2,
    quotes: [
      { ...q1, out: o1, outUsd: outUsd(o1) },
      { ...qk, out: ok_, outUsd: outUsd(ok_) },
    ],
    winner, loser, edgePct,
    bestOut: winner ? (winner === "kyber" ? ok_ : o1) : null,
    bestOutUsd: winner ? outUsd(winner === "kyber" ? ok_ : o1) : null,
    usdPerDstToken,                                  // 1 for stables, live pool mid for tokens, null if no pool priced it
    usdIsEstimate: dst.dollarTrue !== true,          // buys: USD is mid-based ≈; sells: stable, exact
    dstDecimals: dst.decimals,
    // Honest disclosure the UI must render verbatim when any source failed.
    integrity: {
      poolCountIsReal: census0.error == null,
      quotesLive: live.length,
      quotesFailed: [q1, qk].filter(q => !q.ok).map(q => ({ venue: q.venue, error: q.error })),
      note: "Pool count is the live DexScreener pair count for this token. Quotes are live from each aggregator at scan time. Winner and edge are computed from those quotes. Nothing here is simulated.",
    },
  };
}
