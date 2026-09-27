// ============================================================
// UNIFIED TRADING DASHBOARD — trade history + COST-BASIS engine (server-side, READ-ONLY).
// Never signs, cancels, or transmits keys. Reads only public explorers/RPCs.
//
// Two-tier cost basis (Jesse req #1/#2/#3 — "computed, not unknown"):
//   TIER 1  the canonical all-venue ledger  ledger/trades-ledger.jsonl (975 rows)
//           — already prices VIRTUAL-routed buys; the tested source of truth.
//   TIER 2  a direct chain swap-scan (Blockscout robinhood + Alchemy base) that
//           BACKFILLS fills the ledger missed, deduped against the ledger by
//           tx hash / order hash so nothing is ever double-counted.
//
// Output: per `wallet::contractLower` → { buys[], sells[] } with provenance on
// every fill (source: ledger|chain, confidence: exact|estimate).
// ============================================================
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const MODULE = join(HERE, "..", "module");
const LEDGER = join(HERE, "..", "ledger", "trades-ledger.jsonl");

const RH = { blockscout: "https://robinhoodchain.blockscout.com" };
const STABLES = new Set(["USDG", "USDC", "USDT", "DAI", "USDBC", "USD"]);
const MONEY = new Set([...STABLES, "WETH", "VIRTUAL"]); // tokens that can price a swap

function readEnvKey(name) {
  try { return readFileSync(join(MODULE, ".env"), "utf8").match(new RegExp(name + "=(.+)"))?.[1]?.trim() || null; }
  catch { return null; }
}
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const RETRY_BACKOFF = [2000, 8000, 20000];
async function fetchOnce(url, opts = {}, ms = 15000) {
  const ac = new AbortController(); const t = setTimeout(() => ac.abort(), ms);
  try { const r = await fetch(url, { ...opts, signal: ac.signal }); const text = await r.text();
    let data = null; try { data = JSON.parse(text); } catch {} return { ok: r.ok, status: r.status, data, text };
  } catch (e) { return { ok: false, status: 0, data: null, text: String(e?.message || e) }; }
  finally { clearTimeout(t); }
}
// hardened: 5xx / 429 / network errors retry with 2s/8s/20s backoff
async function fetchJson(url, opts = {}, ms = 15000, retries = 3) {
  let r = await fetchOnce(url, opts, ms);
  for (let i = 0; i < retries && !r.ok && (r.status === 0 || r.status === 429 || r.status >= 500); i++) {
    await sleep(RETRY_BACKOFF[Math.min(i, RETRY_BACKOFF.length - 1)]);
    r = await fetchOnce(url, opts, ms);
  }
  return r;
}

// ---------- HISTORICAL ETH price at a tx timestamp ----------
// Native-ETH-paid buys (e.g. BASTION 2026-07-20) must be priced at the ETH
// price WHEN THE TX HAPPENED, not today's. Sources, in order:
//   1. GT hour candle of the Robinhood Chain WETH/USDG pool (deepest ETH/dollar pool on the chain)
//   2. GT day candle of the same pool
//   3. CoinGecko daily history (public endpoint, date-level)
//   4. current ETH price — LAST resort, note says so explicitly
const WETH_USDG_POOL = "0x52e65b17fb6e5ba00ed806f37afcd2daa50271ca"; // USDG/WETH, verified on GT
const ethHistCache = new Map(); // hourBucket -> { price, src } | null
export async function ethUsdAt(ts, pxCurrent) {
  const t = typeof ts === "number" ? ts : Date.parse(ts || "");
  if (!t || Number.isNaN(t)) return { price: pxCurrent ?? null, src: "current-price (no tx timestamp)" };
  const hourBucket = Math.floor(t / 3600000);
  if (ethHistCache.has(hourBucket)) return ethHistCache.get(hourBucket);
  let out = null;
  const sec = Math.floor(t / 1000);
  // 1) GT hour candle containing the tx (before_timestamp returns the candle whose window covers it)
  for (const [tf, maxAgeMs, label] of [["hour", 2 * 3600000, "GT WETH/USDG hour candle"], ["day", 48 * 3600000, "GT WETH/USDG day candle"]]) {
    const r = await fetchJson(`https://api.geckoterminal.com/api/v2/networks/robinhood/pools/${WETH_USDG_POOL}/ohlcv/${tf}?before_timestamp=${sec}&limit=1&currency=usd&token=quote`, { headers: { Accept: "application/json;version=20230302" } });
    const c = r.data?.data?.attributes?.ohlcv_list?.[0];
    if (c && Math.abs(t - c[0] * 1000) <= maxAgeMs && c[4] > 0) { out = { price: c[4], src: `${label} @ tx time` }; break; }
  }
  // 3) CoinGecko daily history
  if (!out) {
    const d = new Date(t);
    const dd = String(d.getUTCDate()).padStart(2, "0"), mm = String(d.getUTCMonth() + 1).padStart(2, "0"), yy = d.getUTCFullYear();
    const r = await fetchJson(`https://api.coingecko.com/api/v3/coins/ethereum/history?date=${dd}-${mm}-${yy}&localization=false`);
    const p = r.data?.market_data?.current_price?.usd;
    if (p > 0) out = { price: p, src: "CoinGecko daily close for the tx date" };
  }
  // 4) honest last resort
  if (!out) out = { price: pxCurrent ?? null, src: "CURRENT ETH price (no historical candle reachable — estimate)" };
  ethHistCache.set(hourBucket, out);
  return out;
}

// ---------- money-leg prices (cached) ----------
let priceCache = { at: 0, eth: null, virtual: null };
async function moneyPrices() {
  if (Date.now() - priceCache.at < 300000 && priceCache.eth) return priceCache;
  const eth = await fetchJson("https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd");
  let ethUsd = eth.data?.ethereum?.usd ?? null;
  // VIRTUAL via DexScreener (base) — best effort, current
  let virtUsd = null;
  const v = await fetchJson("https://api.dexscreener.com/latest/dex/tokens/0x0b3e328455c4059EEb9e3f84b5543F74E24e7E1b");
  if (v.data?.pairs?.length) virtUsd = Number(v.data.pairs.sort((a, b) => (b.liquidity?.usd || 0) - (a.liquidity?.usd || 0))[0]?.priceUsd) || null;
  priceCache = { at: Date.now(), eth: ethUsd, virtual: virtUsd };
  return priceCache;
}
function moneyUsd(sym, amt, px) {
  const s = (sym || "").toUpperCase();
  if (STABLES.has(s)) return amt;               // dollar-true
  if (s === "WETH") return px.eth != null ? amt * px.eth : null;
  if (s === "VIRTUAL") return px.virtual != null ? amt * px.virtual : null;
  return null;
}
// timestamp-aware version: WETH legs get priced at the TX-TIME ETH price
// (GT candle / CG daily), not today's. Stables stay dollar-true.
async function moneyUsdAt(sym, amt, px, ts) {
  const s = (sym || "").toUpperCase();
  if (s === "WETH") {
    const h = await ethUsdAt(ts, px.eth);
    return { usd: h.price != null ? amt * h.price : null, priceSrc: h.src };
  }
  return { usd: moneyUsd(sym, amt, px), priceSrc: STABLES.has(s) ? "dollar-true" : s === "VIRTUAL" ? "current VIRTUAL price (estimate)" : null };
}

// ---------- TIER 1: the ledger ----------
export function parseLedger() {
  const rows = readFileSync(LEDGER, "utf8").trim().split("\n").filter(Boolean).map(l => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
  return rows;
}
function ledgerFills(rows) {
  // per wallet::contractLower -> {buys, sells}; only FILLED rows carry basis
  const idx = {};
  const seenTx = new Set();     // tx_hash|token|side  (dedup key for chain backfill)
  const seenOrder = new Set();  // order_hash
  for (const r of rows) {
    if (r.status !== "filled") continue;
    const contract = (r.contract || "").toLowerCase();
    const key = r.wallet + "::" + contract;
    (idx[key] ||= { buys: [], sells: [], contract, token: r.token, wallet: r.wallet, chain: r.chain });
    const fill = {
      time: r.timestamp, qty: r.qty, priceUsd: r.price_usd, usd: r.usd_value,
      txHash: r.tx_hash || null, orderHash: r.order_hash || null,
      counter: r.counter_token || null, source: "ledger", confidence: r.confidence || "exact",
      side: r.side === "buy" ? "buy" : "sell",   // normalized: consumers (datasource gap-fill) read .side
      kind: r.side === "buy" ? "buy" : "sell", note: r.notes || null,
    };
    (r.side === "buy" ? idx[key].buys : idx[key].sells).push(fill);
    if (r.tx_hash) seenTx.add(r.tx_hash.toLowerCase() + "|" + (r.token || "") + "|" + r.side);
    if (r.order_hash) seenOrder.add(r.order_hash.toLowerCase());
  }
  return { idx, seenTx, seenOrder };
}

// ---------- TIER 2: chain swap reconstruction (Blockscout, Robinhood Chain) ----------
async function rhAllTransfers(addr) {
  let items = [], url = `${RH.blockscout}/api/v2/addresses/${addr}/token-transfers?type=ERC-20`;
  for (let page = 0; page < 8 && url; page++) {
    const r = await fetchJson(url); if (!r.ok || !r.data) break;
    items = items.concat(r.data.items || []);
    if (r.data.next_page_params) { const q = new URLSearchParams(r.data.next_page_params).toString(); url = `${RH.blockscout}/api/v2/addresses/${addr}/token-transfers?type=ERC-20&${q}`; }
    else url = null;
  }
  return items;
}
async function rhTxInfo(hash) { const r = await fetchJson(`${RH.blockscout}/api/v2/transactions/${hash}`); return r.data || null; }
async function rhTxTransfers(hash) { const r = await fetchJson(`${RH.blockscout}/api/v2/transactions/${hash}/token-transfers`); return r.data?.items || []; }

// group a wallet's transfers into per-tx net deltas
function groupByTx(addr, items) {
  const a = addr.toLowerCase(); const seen = new Set(); const byTx = {};
  for (const it of items) {
    const k = it.transaction_hash + ":" + it.log_index; if (seen.has(k)) continue; seen.add(k);
    (byTx[it.transaction_hash] ||= { ts: it.timestamp, legs: [] }).legs.push(it);
  }
  const out = {};
  for (const [tx, { ts, legs }] of Object.entries(byTx)) {
    const net = {};
    for (const t of legs) {
      const c = (t.token?.address_hash || t.token?.address || "").toLowerCase();
      const dec = Number(t.token?.decimals || 18); const val = Number(t.total?.value || 0) / 10 ** dec;
      const from = (t.from?.hash || "").toLowerCase(), to = (t.to?.hash || "").toLowerCase();
      let d = 0; if (to === a) d += val; if (from === a) d -= val;
      net[c] ||= { sym: t.token?.symbol, dec, delta: 0, contract: c };
      net[c].delta += d;
    }
    out[tx] = { ts, net };
  }
  return out;
}

// Robinhood-chain backfill: return fills NOT already in the ledger.
// Two passes: (1) FAST net-delta swaps (no extra HTTP); (2) bounded, PARALLEL per-tx
// enrichment for one-sided router/native/relayer swaps — restricted to `enrichSet`
// (registry contracts) so we never chase dust/airdrops. Cap keeps boot fast.
async function rhBackfill(addr, wallet, ledgerSeenTx, px, enrichSet, ownWallets, cap = 8) {
  const fills = [];
  const transfers = [];
  const items = await rhAllTransfers(addr);
  // INTERNAL TRANSFERS (Jesse consolidation 2026-07-22): a token move where BOTH
  // ends are Jesse's own wallets is a TRANSFER, never a buy/sell. Detect the tx
  // hashes up front and (1) record the transfer edge for the datasource's basis
  // carry, (2) SKIP them below so no phantom buy/sell is ever emitted. A DEX swap
  // trades wallet↔pool, never own↔own, so this discriminator is clean.
  const internalTxs = new Set();
  for (const it of items) {
    const from = (it.from?.hash || "").toLowerCase(), to = (it.to?.hash || "").toLowerCase();
    if (from && to && from !== to && ownWallets.has(from) && ownWallets.has(to)) {
      internalTxs.add((it.transaction_hash || "").toLowerCase());
      const c = (it.token?.address_hash || it.token?.address || "").toLowerCase();
      const dec = Number(it.token?.decimals || 18);
      transfers.push({ chain: "robinhood", contract: c, token: it.token?.symbol || null, fromAddr: from, toAddr: to, qty: Number(it.total?.value || 0) / 10 ** dec, tx: it.transaction_hash, time: it.timestamp });
    }
  }
  const grouped = groupByTx(addr, items);
  const enrichBuys = [], enrichSells = []; // {tx, ts, g|l}
  for (const [tx, { ts, net }] of Object.entries(grouped)) {
    if (internalTxs.has(tx.toLowerCase())) continue;   // own→own transfer: not a trade
    const parts = Object.values(net).filter(v => Math.abs(v.delta) > 1e-9);
    const gained = parts.filter(v => v.delta > 0);
    const lost = parts.filter(v => v.delta < 0);
    const nonMoneyGain = gained.filter(v => !MONEY.has((v.sym || "").toUpperCase()));
    const nonMoneyLoss = lost.filter(v => !MONEY.has((v.sym || "").toUpperCase()));
    const moneyGain = gained.find(v => MONEY.has((v.sym || "").toUpperCase()));
    const moneyLoss = lost.find(v => MONEY.has((v.sym || "").toUpperCase()));

    // Case A — clean swap the wallet both sent+received (no extra HTTP unless a WETH leg needs tx-time pricing)
    if (gained.length && lost.length) {
      for (const g of nonMoneyGain) {
        if (ledgerSeenTx.has(tx.toLowerCase() + "|" + (g.sym || "") + "|buy")) continue;
        const m = moneyLoss ? await moneyUsdAt(moneyLoss.sym, Math.abs(moneyLoss.delta), px, ts) : { usd: null, priceSrc: null };
        const usd = m.usd;
        const conf = moneyLoss && STABLES.has((moneyLoss.sym || "").toUpperCase()) ? "exact" : "estimate";
        fills.push({ wallet, contract: g.contract, token: g.sym, side: "buy", time: ts, qty: g.delta, usd, priceUsd: usd != null ? usd / g.delta : null, txHash: tx, source: "chain", confidence: conf, counter: moneyLoss?.sym || nonMoneyLoss[0]?.sym || null, note: moneyLoss ? `chain swap backfill${m.priceSrc && m.priceSrc !== "dollar-true" ? " (" + m.priceSrc + ")" : ""}` : "chain backfill (token-to-token — qty only, price unknown)" });
      }
      for (const l of nonMoneyLoss) {
        if (ledgerSeenTx.has(tx.toLowerCase() + "|" + (l.sym || "") + "|sell")) continue;
        const m = moneyGain ? await moneyUsdAt(moneyGain.sym, Math.abs(moneyGain.delta), px, ts) : { usd: null, priceSrc: null };
        const usd = m.usd;
        const conf = moneyGain && STABLES.has((moneyGain.sym || "").toUpperCase()) ? "exact" : "estimate";
        fills.push({ wallet, contract: l.contract, token: l.sym, side: "sell", time: ts, qty: -l.delta, usd, priceUsd: usd != null ? usd / (-l.delta) : null, txHash: tx, source: "chain", confidence: conf, counter: moneyGain?.sym || nonMoneyGain[0]?.sym || null, note: moneyGain ? `chain swap backfill${m.priceSrc && m.priceSrc !== "dollar-true" ? " (" + m.priceSrc + ")" : ""}` : "chain backfill (token-to-token — qty only, price unknown)" });
      }
      continue;
    }
    // Case B — one-sided GAIN of one registry token (router/native/relayer paid) → queue for enrichment
    if (nonMoneyGain.length === 1 && !nonMoneyLoss.length && !moneyGain) {
      const g = nonMoneyGain[0];
      if (enrichSet.has((g.contract || "").toLowerCase()) && !ledgerSeenTx.has(tx.toLowerCase() + "|" + (g.sym || "") + "|buy")) enrichBuys.push({ tx, ts, g });
    }
    // Case C — one-sided LOSS of one registry token (routed sell) → queue for enrichment
    if (nonMoneyLoss.length === 1 && !nonMoneyGain.length && !moneyLoss) {
      const l = nonMoneyLoss[0];
      if (enrichSet.has((l.contract || "").toLowerCase()) && !ledgerSeenTx.has(tx.toLowerCase() + "|" + (l.sym || "") + "|sell")) enrichSells.push({ tx, ts, l });
    }
  }

  // ---- bounded, parallel enrichment (registry tokens only) ----
  const bigMoneyLeg = async (tx) => {
    const legs = await rhTxTransfers(tx); const seen = new Set(); const byMoney = {};
    for (const t of legs) { if (seen.has(t.log_index)) continue; seen.add(t.log_index);
      const s = (t.token?.symbol || "").toUpperCase(); if (!MONEY.has(s)) continue;
      const dec = Number(t.token?.decimals || 18); const v = Number(t.total?.value || 0) / 10 ** dec; byMoney[s] = Math.max(byMoney[s] || 0, v); }
    // prefer a DOLLAR-TRUE stable leg (exact) over WETH/VIRTUAL legs (estimates):
    // e.g. the VEX sell routed USDG→WETH→unwrap — the USDG leg IS the true proceeds.
    return Object.entries(byMoney).sort((a, b) => {
      const aStable = STABLES.has(a[0]) ? 1 : 0, bStable = STABLES.has(b[0]) ? 1 : 0;
      if (aStable !== bStable) return bStable - aStable;
      return (moneyUsd(b[0], b[1], px) || 0) - (moneyUsd(a[0], a[1], px) || 0);
    })[0] || null;
  };
  await Promise.all(enrichBuys.slice(0, cap).map(async ({ tx, ts, g }) => {
    const info = await rhTxInfo(tx);
    let usd = null, counter = null, note = null;
    const nativeWei = info?.value ? Number(BigInt(info.value)) / 1e18 : 0;
    if (info?.from?.hash?.toLowerCase() === addr.toLowerCase() && nativeWei > 0) {
      // NATIVE-ETH-PAID BUY (the BASTION case): tx.value is the money leg —
      // price it at the TX-TIME ETH price, never today's.
      const h = await ethUsdAt(ts, px.eth);
      if (h.price != null) { usd = nativeWei * h.price; counter = "ETH"; note = `chain backfill (native ETH paid — ${nativeWei.toFixed(6)} ETH priced via ${h.src})`; }
    } else {
      const best = await bigMoneyLeg(tx);
      if (best) { const m = await moneyUsdAt(best[0], best[1], px, ts); usd = m.usd; counter = best[0]; note = `chain backfill (routed/relayer swap — ${best[0]} money leg${m.priceSrc && m.priceSrc !== "dollar-true" ? ", " + m.priceSrc : ""})`; }
    }
    fills.push({ wallet, contract: g.contract, token: g.sym, side: "buy", time: ts, qty: g.delta, usd, priceUsd: usd != null ? usd / g.delta : null, txHash: tx, source: "chain", confidence: "estimate", counter, note: note || "chain backfill (routed/relayer swap — estimate)" });
  }));
  await Promise.all(enrichSells.slice(0, cap).map(async ({ tx, ts, l }) => {
    const best = await bigMoneyLeg(tx);
    let usd = null, note = "chain backfill (routed sell — estimate)";
    if (best) { const m = await moneyUsdAt(best[0], best[1], px, ts); usd = m.usd; note = `chain backfill (routed sell — ${best[0]} money leg${m.priceSrc && m.priceSrc !== "dollar-true" ? ", " + m.priceSrc : ""})`; }
    fills.push({ wallet, contract: l.contract, token: l.sym, side: "sell", time: ts, qty: -l.delta, usd, priceUsd: usd != null ? usd / (-l.delta) : null, txHash: tx, source: "chain", confidence: "estimate", counter: best?.[0] || null, note });
  }));
  return { fills, transfers };
}

// ---------- Base backfill (Alchemy getAssetTransfers) ----------
async function baseBackfill(addr, wallet, ledgerSeenTx, px, alchemyKey, ownWallets) {
  if (!alchemyKey) return { fills: [], transfers: [] };
  const url = `https://base-mainnet.g.alchemy.com/v2/${alchemyKey}`;
  const common = { fromBlock: "0x0", toBlock: "latest", category: ["erc20"], withMetadata: true, maxCount: "0x3e8" };
  const out = [];
  const transfers = [];
  const internalTxs = new Set();
  const fromR = await fetchJson(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "alchemy_getAssetTransfers", params: [{ ...common, fromAddress: addr }] }) });
  const toR = await fetchJson(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "alchemy_getAssetTransfers", params: [{ ...common, toAddress: addr }] }) });
  const all = [...(fromR.data?.result?.transfers || []), ...(toR.data?.result?.transfers || [])];
  // own→own internal transfers (consolidation) — record + suppress (same as robinhood)
  for (const t of all) {
    const from = (t.from || "").toLowerCase(), to = (t.to || "").toLowerCase();
    if (from && to && from !== to && ownWallets.has(from) && ownWallets.has(to)) {
      internalTxs.add((t.hash || "").toLowerCase());
      transfers.push({ chain: "base", contract: (t.rawContract?.address || "").toLowerCase(), token: t.asset || null, fromAddr: from, toAddr: to, qty: t.value || 0, tx: t.hash, time: t.metadata?.blockTimestamp });
    }
  }
  const a = addr.toLowerCase(); const byTx = {};
  for (const t of all) {
    const tx = t.hash; const c = (t.rawContract?.address || "").toLowerCase();
    const val = t.value || 0; const from = (t.from || "").toLowerCase(), to = (t.to || "").toLowerCase();
    let d = 0; if (to === a) d += val; if (from === a) d -= val; if (!d) continue;
    (byTx[tx] ||= { ts: t.metadata?.blockTimestamp, net: {} });
    byTx[tx].net[c] ||= { sym: t.asset, delta: 0, contract: c }; byTx[tx].net[c].delta += d;
  }
  for (const [tx, { ts, net }] of Object.entries(byTx)) {
    if (internalTxs.has(tx.toLowerCase())) continue;   // own→own transfer: not a trade
    const parts = Object.values(net).filter(v => Math.abs(v.delta) > 1e-12);
    const gained = parts.filter(v => v.delta > 0), lost = parts.filter(v => v.delta < 0);
    if (!gained.length || !lost.length) continue;
    const moneyLoss = lost.find(v => MONEY.has((v.sym || "").toUpperCase()));
    const moneyGain = gained.find(v => MONEY.has((v.sym || "").toUpperCase()));
    for (const g of gained.filter(v => !MONEY.has((v.sym || "").toUpperCase()))) {
      if (ledgerSeenTx.has(tx.toLowerCase() + "|" + (g.sym || "") + "|buy")) continue;
      const usd = moneyLoss ? moneyUsd(moneyLoss.sym, Math.abs(moneyLoss.delta), px) : null;
      out.push({ wallet, contract: g.contract, token: g.sym, side: "buy", time: ts, qty: g.delta, usd, priceUsd: usd != null ? usd / g.delta : null, txHash: tx, source: "chain", confidence: moneyLoss && STABLES.has((moneyLoss.sym || "").toUpperCase()) ? "exact" : "estimate", counter: moneyLoss?.sym || null, note: "base chain backfill" });
    }
    for (const l of lost.filter(v => !MONEY.has((v.sym || "").toUpperCase()))) {
      if (ledgerSeenTx.has(tx.toLowerCase() + "|" + (l.sym || "") + "|sell")) continue;
      const usd = moneyGain ? moneyUsd(moneyGain.sym, Math.abs(moneyGain.delta), px) : null;
      out.push({ wallet, contract: l.contract, token: l.sym, side: "sell", time: ts, qty: -l.delta, usd, priceUsd: usd != null ? usd / (-l.delta) : null, txHash: tx, source: "chain", confidence: moneyGain && STABLES.has((moneyGain.sym || "").toUpperCase()) ? "exact" : "estimate", counter: moneyGain?.sym || null, note: "base chain backfill" });
    }
  }
  return { fills: out, transfers };
}

// ---------- PUBLIC: build the merged history index ----------
// `enrichContracts` = Set/array of lowercased contract addrs eligible for the
// slow per-tx enrichment pass (pass the registry's AUTHORIZED contracts so we
// only chase real, held tokens — never dust/airdrops).
// `ownWallets` = Set of Jesse's lowercased wallet addresses; a token move where
// BOTH ends are in this set is an INTERNAL TRANSFER (consolidation), recorded in
// `transfers` and NEVER emitted as a buy/sell. Defaults to the passed wallets.
export async function buildHistoryIndex(wallets, enrichContracts, ownWallets) {
  const rows = parseLedger();
  const { idx, seenTx, seenOrder } = ledgerFills(rows);
  const px = await moneyPrices();
  const ALCHEMY = readEnvKey("ALCHEMY_API_KEY");
  const enrichSet = enrichContracts instanceof Set ? enrichContracts : new Set((enrichContracts || []).map(c => (c || "").toLowerCase()));
  const own = ownWallets instanceof Set ? ownWallets : new Set((wallets || []).map(w => (w.address || "").toLowerCase()));
  const nameByAddr = Object.fromEntries((wallets || []).map(w => [(w.address || "").toLowerCase(), w.name]));

  // chain backfill per wallet (defensive; failures don't sink the ledger tier).
  // RETIRING wallets (e.g. wallet-1 after consolidation) are still scanned so
  // their basis'd remnants (BASTION) keep a real chain-verified basis; only a
  // pure external watch address (watchOnly && !retiring, e.g. Solana) is skipped.
  const backfills = [];
  const transfers = [];
  await Promise.all((wallets || []).map(async (w) => {
    if (w.watchOnly && !w.retiring) return;
    try {
      if ((w.chains || []).includes("robinhood")) { const r = await rhBackfill(w.address, w.name, seenTx, px, enrichSet, own); backfills.push(...r.fills); transfers.push(...r.transfers); }
    } catch (e) { /* keep ledger tier */ }
    try {
      if ((w.chains || []).includes("base")) { const r = await baseBackfill(w.address, w.name, seenTx, px, ALCHEMY, own); backfills.push(...r.fills); transfers.push(...r.transfers); }
    } catch (e) { /* keep ledger tier */ }
  }));

  for (const f of backfills) {
    const key = f.wallet + "::" + (f.contract || "").toLowerCase();
    (idx[key] ||= { buys: [], sells: [], contract: (f.contract || "").toLowerCase(), token: f.token, wallet: f.wallet });
    (f.side === "buy" ? idx[key].buys : idx[key].sells).push(f);
  }

  // sort each side by time
  for (const k of Object.keys(idx)) {
    idx[k].buys.sort((a, b) => new Date(a.time) - new Date(b.time));
    idx[k].sells.sort((a, b) => new Date(a.time) - new Date(b.time));
  }
  // dedupe transfers by tx+contract; attach resolved wallet names
  const seenTr = new Set();
  const transfersOut = [];
  for (const t of transfers) {
    const k = (t.tx || "") + "|" + (t.contract || "");
    if (seenTr.has(k)) continue; seenTr.add(k);
    transfersOut.push({ ...t, fromWallet: nameByAddr[t.fromAddr] || null, toWallet: nameByAddr[t.toAddr] || null });
  }
  return { index: idx, prices: px, ledgerRows: rows.length, backfilled: backfills.length, transfers: transfersOut };
}

// ---------- cost-basis math for one position (weighted average cost) ----------
export function computeBasis(fills, currentQty, currentPrice) {
  const buys = fills?.buys || [], sells = fills?.sells || [];
  const valuedBuys = buys.filter(b => b.usd != null && b.qty > 0);
  const buyQty = valuedBuys.reduce((s, b) => s + b.qty, 0);
  const buyUsd = valuedBuys.reduce((s, b) => s + b.usd, 0);
  const buyQtyAll = buys.reduce((s, b) => s + (b.qty || 0), 0);
  const avgCost = buyQty > 0 ? buyUsd / buyQty : null;
  const sellQty = sells.reduce((s, x) => s + (x.qty || 0), 0);
  const sellUsd = sells.reduce((s, x) => s + (x.usd || 0), 0);
  const avgSell = sellQty > 0 ? sellUsd / sellQty : null;
  const realizedPnl = (avgCost != null && sellQty > 0) ? sellUsd - avgCost * sellQty : null;
  const unrealizedPnl = (avgCost != null && currentQty > 0 && currentPrice != null) ? (currentPrice - avgCost) * currentQty : null;
  const atRisk = avgCost != null ? avgCost * currentQty : null;               // cost still on the table
  const marketValue = currentPrice != null ? currentPrice * currentQty : null;
  // basis quality: coverage of the CURRENT bag by valued buys (net of nothing — avg-cost model)
  const coverage = currentQty > 0 && buyQty > 0 ? Math.min(1, buyQty / (currentQty + sellQty)) : 0;
  const anyEstimate = valuedBuys.some(b => b.confidence !== "exact") || sells.some(s => s.usd != null && s.confidence && s.confidence !== "exact");
  let quality = "unknown", reason = "no priced buy found in ledger or on-chain history";
  if (avgCost != null) {
    if (buyQtyAll > 0 && buyQty / buyQtyAll < 0.999) { quality = "partial"; reason = "some buys on-chain could not be priced"; }
    else if (currentQty > 0 && buyQty + 1e-6 < currentQty + sellQty * 0 && (buyQty < currentQty * 0.95)) { quality = "partial"; reason = "held qty exceeds priced buys (token-to-token or transfer-in)"; }
    else if (anyEstimate) { quality = "estimate"; reason = "priced via on-chain/relayer legs or non-dollar counter (VIRTUAL/WETH)"; }
    else { quality = "exact"; reason = "every buy priced from a dollar leg"; }
  }
  return { buys, sells, valuedBuyQty: buyQty, avgCost, avgSell, buyUsd, sellQty, sellUsd,
    realizedProceeds: sellUsd, realizedPnl, unrealizedPnl, atRisk, marketValue,
    moneyIn: buyUsd, moneyOut: sellUsd, quality, basisReason: reason };
}
