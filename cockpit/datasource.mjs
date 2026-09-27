// ============================================================
// UNIFIED TRADING DASHBOARD — data source (server-side only).
// READ-ONLY. Never signs, cancels, or transmits keys.
// Reads the execution module's files (registry, orders-log, wallets),
// the CANONICAL LEDGER (../ledger/trades-ledger.jsonl) and the .env
// (ONEINCH_API_KEY + ALCHEMY_API_KEY) which STAYS in this process —
// it is never written into any served HTML/JSON key field.
//
// v2 (2026-07-21, rebuilt on Jesse's direct feedback):
//   1. Cost basis + P&L are computed from the LEDGER: every individual
//      buy and sell lot per position, qty-weighted average cost, money
//      in / money out, still-at-risk vs banked, realized + unrealized
//      P&L, and an honest basis-coverage % (pre-history bags never get
//      a fabricated basis).
//   2. Token→token swap counter-legs (e.g. VIM→KARMA) are resolved via
//      Blockscout tx token-transfers so the received token gets its
//      REAL acquisition lot (qty + implied price).
//   3. Token age from DexScreener pairCreatedAt (GT pool_created_at
//      fallback) → default candle timeframe: <30d = 1h, 30–60d = 4h,
//      >60d = daily. Sent to the page for BOTH the GT embed and the
//      levels canvas.
//   4. Closed / unaccounted positions (fully exited bags) are reported
//      with their own realized math instead of vanishing.
//
// Chains: robinhood (Blockscout) · base (Alchemy) · solana (Alchemy, watch-only).
// Live orders: 1inch orderbook v4.0 on chainIds 4663 + 8453.
// Prices: Blockscout exchange_rate (RH) + DexScreener + CoinGecko (natives).
// ============================================================
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { buildHistoryIndex } from "./history.mjs";
import { fetchCoinbaseBalances } from "./coinbase-balances.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const MODULE = join(HERE, "..", "module");
const LEDGER = join(HERE, "..", "ledger", "trades-ledger.jsonl");

// ---------- cost-basis GAP-FILL cache (history.mjs) ----------
// The ledger + token→token counter-legs above cover most positions, but a bag
// acquired with NATIVE ETH (BASTION) or via a routed/relayer Fusion settlement
// (VEX) has no ledger sell whose counter_token names it, so it falls through with
// avgCost UNKNOWN. history.mjs runs a direct chain net-delta swap-scan (Blockscout
// robinhood + Alchemy base) with native-value/routed-leg enrichment and returns
// verified buy/sell fills. It is HEAVY (~15-40s) → cached 15 min and served stale
// while refreshing so the 25s /api/state stays fast. Only positions still MISSING
// a buy lot get filled, deduped by tx/orderHash/qty — nothing is double-counted.
const enrichCache = { at: 0, ttl: 900_000, data: null, inflight: null };
async function getHistoryIndex(wallets, enrichContracts, ownWallets) {
  const fresh = Date.now() - enrichCache.at < enrichCache.ttl && enrichCache.data;
  if (fresh) return enrichCache.data;
  if (!enrichCache.inflight) {
    enrichCache.inflight = buildHistoryIndex(wallets, enrichContracts, ownWallets)
      .then(d => { enrichCache.data = d; enrichCache.at = Date.now(); return d; })
      .catch(e => { if (enrichCache.data) return enrichCache.data; throw e; })
      .finally(() => { enrichCache.inflight = null; });
  }
  if (enrichCache.data) return enrichCache.data;        // serve stale while refreshing
  return await enrichCache.inflight;                     // first ever call (boot warm)
}

// ---------- config ----------
const CHAINS = {
  robinhood: { gtNetwork: "robinhood", chainId: 4663, blockscout: "https://robinhoodchain.blockscout.com", rpc: "https://rpc.mainnet.chain.robinhood.com", nativeSym: "ETH", nativeCg: "ethereum" },
  base:      { gtNetwork: "base",      chainId: 8453, alchemyNet: "base-mainnet", nativeSym: "ETH", nativeCg: "ethereum" },
};
const ONEINCH_CHAINS = [4663, 8453];
const DUST_USD = 1.0;            // hide sub-$1 balances (kept in counts)

// ============================================================
// PROTECTED HOLDINGS — tokens listed here are NEVER dust, NEVER spam-filtered,
// NEVER auto-hidden, at ANY USD value, in ANY wallet. Use this for long-term
// holdings you always want visible even when they have no priced pool.
// Pin BY CONTRACT you have resolved on-chain via symbol()/name() yourself,
// never by guessed ticker. Valuation honesty still applies: if no real pool
// prices a pinned token, the dashboard shows the balance and labels the price
// "unverified" rather than inventing a dollar value.
// Ships EMPTY — add your own, e.g.:
//   "0x...contract...": { symbol: "mytoken", name: "My Token", chain: "base", decimals: 18 },
const PINNED_HOLDINGS = {};
const isPinned = (contract) => !!PINNED_HOLDINGS[(contract || "").toLowerCase()];

function readJson(p) { return JSON.parse(readFileSync(p, "utf8")); }
function readEnvKey(name) {
  try { return readFileSync(join(MODULE, ".env"), "utf8").match(new RegExp(name + "=(.+)"))?.[1]?.trim() || null; }
  catch { return null; }
}
// ---------- hardened fetch: 5xx / 429 / network errors get retried with
// exponential backoff (2s / 8s / 20s) before we give up. Closes the
// 2026-07-20 22:21 "transient RPC balance-read flake" defect: one blip no
// longer paints an error on a wallet card. 4xx (except 429) never retries.
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const RETRY_BACKOFF = [2000, 8000, 20000];
async function fetchOnce(url, opts = {}, ms = 12000) {
  const ac = new AbortController();
  const t = setTimeout(() => ac.abort(), ms);
  try {
    const r = await fetch(url, { ...opts, signal: ac.signal });
    const text = await r.text();
    let data = null; try { data = JSON.parse(text); } catch {}
    return { ok: r.ok, status: r.status, data, text };
  } catch (e) { return { ok: false, status: 0, data: null, text: String(e?.message || e) }; }
  finally { clearTimeout(t); }
}
function retryable(r) { return r.status === 0 || r.status === 429 || r.status >= 500; }
async function fetchJson(url, opts = {}, ms = 12000, retries = 3) {
  let r = await fetchOnce(url, opts, ms);
  for (let i = 0; i < retries && !r.ok && retryable(r); i++) {
    await sleep(RETRY_BACKOFF[Math.min(i, RETRY_BACKOFF.length - 1)]);
    r = await fetchOnce(url, opts, ms);
  }
  return r;
}

// ---------- static price cache for natives ----------
let nativeCache = { at: 0, eth: null, sol: null };
async function nativePrices() {
  if (Date.now() - nativeCache.at < 60000 && nativeCache.eth) return nativeCache;
  const r = await fetchJson("https://api.coingecko.com/api/v3/simple/price?ids=ethereum,solana&vs_currencies=usd");
  if (r.ok && r.data) nativeCache = { at: Date.now(), eth: r.data.ethereum?.usd ?? null, sol: r.data.solana?.usd ?? null };
  return nativeCache;
}

// ---------- DexScreener (price + pool discovery) ----------
// POISON-PAIR GUARD (2026-07-23, the PONS lesson — FIXES-LOG AD). DexScreener
// sometimes returns a busted pair whose numbers are pure garbage: a PONS/USDG
// pool (0x7A192E71…) reported price $6.36e+26 and $1.27B "liquidity" while the
// other 29 PONS pairs agreed on ~$0.034. "Pick the deepest pool" with no sanity
// check let that one pair become the live price, blank the ladder chart (y-axis
// stretched to e+26), and fake the liq readout. Two rules now apply everywhere
// a best-pair is chosen:
//   1. REGISTRY FIRST: a vetted token's price/pool comes from its registry
//      mainPool outright when that pair is in the response — never re-decided
//      by whoever shouts the biggest liquidity number.
//   2. MEDIAN FILTER: otherwise take the median price across the token's
//      pairs and drop any pair >5x off it (its liquidity claim is a lie too),
//      then pick the deepest survivor. Single-pair tokens pass through — no
//      consensus exists to check them against.
let regPoolsCache = { at: 0, map: {} };
function registryMainPools() {
  if (Date.now() - regPoolsCache.at < 60000) return regPoolsCache.map;
  const map = {};
  try {
    const reg = JSON.parse(readFileSync(join(MODULE, "registry.json"), "utf8"));
    for (const t of Object.values(reg.tokens || {})) {
      if (t?.contract && t?.mainPool) map[t.contract.toLowerCase()] = t.mainPool.toLowerCase();
    }
  } catch { /* no registry → guard degrades to the median filter alone */ }
  regPoolsCache = { at: Date.now(), map };
  return map;
}
function sanePairs(pairs) {
  const px = pairs.map(p => Number(p.priceUsd)).filter(v => v > 0).sort((a, b) => a - b);
  if (px.length < 2) return pairs;
  const med = px[Math.floor(px.length / 2)];
  const ok = pairs.filter(p => { const v = Number(p.priceUsd); return v > 0 && v / med < 5 && v / med > 0.2; });
  return ok.length ? ok : pairs;
}
function bestPair(base, pairs) {
  const regPool = registryMainPools()[base];
  const own = regPool ? pairs.find(p => (p.pairAddress || "").toLowerCase() === regPool) : null;
  if (own) return own;
  const pick = sanePairs(pairs).slice().sort((a, b) => (b.liquidity?.usd || 0) - (a.liquidity?.usd || 0))[0] || null;
  // LIQ FLOOR (2026-07-24, the USXR lesson): a non-registry token whose best pair has
  // under $1K real liquidity gets NO price — a spam airdrop's fake pool (USXR: absurd
  // price, $0 liq, only pair) must never mint a dashboard valuation. The median filter
  // can't help when the fake pool is the ONLY pair; the floor can. Unpriced spam then
  // falls into dust/hidden naturally.
  if (pick && (pick.liquidity?.usd || 0) < 1000) return null;
  return pick;
}
async function dexBatch(contracts) {
  const out = {}, byBase = {};
  for (let i = 0; i < contracts.length; i += 30) {
    const chunk = contracts.slice(i, i + 30);
    const r = await fetchJson("https://api.dexscreener.com/latest/dex/tokens/" + chunk.join(","));
    if (!r.ok || !r.data?.pairs) continue;
    for (const p of r.data.pairs) {
      const base = (p.baseToken?.address || "").toLowerCase();
      if (base) (byBase[base] ||= []).push(p);
    }
  }
  for (const [base, pairs] of Object.entries(byBase)) {
    const p = bestPair(base, pairs);
    if (!p) continue;
    out[base] = { priceUsd: Number(p.priceUsd) || null, symbol: p.baseToken?.symbol, name: p.baseToken?.name, pool: p.pairAddress, liq: p.liquidity?.usd || 0, url: p.url, chainId: p.chainId, pairCreatedAt: p.pairCreatedAt || null };
  }
  return out;
}

// ============================================================
// BALANCE SCANS — RPC-FIRST (Jesse doctrine 2026-07-22, the data-freshness
// mandate). ROOT FIX for the stale-balance burn: Blockscout served a stale
// stablecoin balance (the dashboard showed a quarter of what the chain RPC
// returned the same second, 2026-07-22 19:08Z). Balances now come DIRECTLY from the chain's own
// JSON-RPC via batched eth_call balanceOf + eth_getBalance — one HTTP call for
// many balances — against rpc.mainnet.chain.robinhood.com (4663) and Alchemy /
// raw RPC (8453). Blockscout is DEMOTED to DISCOVERY-ONLY (enumerating which
// token contracts a wallet holds) and NEVER touches a returned balance/value.
//
// DISCOVERY (which contracts to balanceOf): registry(chain) ∪ ledger-touched
// contracts ∪ a periodic (hourly) Blockscout sweep whose CONTRACT LIST is cached
// to disk (.discovery-cache.json). A contract-list cache is NOT the last-good
// BALANCE cache that Jesse rejected in FIXES-LOG A-2 — balances are always a live
// RPC read; the cache only decides WHICH contracts to read, so a Blockscout
// outage can never change a number, only (for up to an hour) hide a brand-new
// untracked token. Registry+ledger already cover every tracked position, so the
// only gap is untracked airdrops/dust — acceptable and honest.
//   robinhood: RPC batch balanceOf over the discovery set (PRIMARY) → Alchemy RPC failover
//   base:      Alchemy base-mainnet (a JSON-RPC provider, NOT Blockscout) → raw RPC balanceOf
//   solana:    Alchemy solana-mainnet → public RPC api.mainnet-beta.solana.com
// money data is LIVE or explicitly ERRORED, never silently stale.
// ============================================================

// EVM JSON-RPC body helper
const rpcBody = (method, params) => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }) });

// ---------- DISCOVERY: which token contracts might a wallet hold? ----------
// RPC can read a balance but cannot ENUMERATE a wallet's tokens. The candidate
// contract list is the union of registry (this chain), ledger-touched contracts,
// and an hourly Blockscout sweep cached to disk. Balances are then read via RPC.
const DISCOVERY_CACHE_FILE = join(HERE, ".discovery-cache.json");
const DISCOVERY_TTL = 3_600_000;                 // hourly Blockscout sweep
const discoveryMem = { loaded: false, data: {} }; // { "wallet|chain": { at, contracts:[{contract,symbol,name,decimals}] } }
function loadDiscoveryCache() {
  if (discoveryMem.loaded) return;
  try { discoveryMem.data = JSON.parse(readFileSync(DISCOVERY_CACHE_FILE, "utf8")) || {}; } catch { discoveryMem.data = {}; }
  discoveryMem.loaded = true;
}
function saveDiscoveryCache() {
  try { writeFileSync(DISCOVERY_CACHE_FILE, JSON.stringify(discoveryMem.data)); } catch { /* cache is best-effort; never blocks a balance read */ }
}
// Blockscout token-contract sweep (DISCOVERY ONLY — the balances it returns are
// intentionally IGNORED; we only keep the contract/symbol/name/decimals list and
// re-read every balance via RPC). Runs at most hourly, in the background, and its
// failure falls back to the last cached sweep (∪ registry ∪ ledger).
async function blockscoutDiscover(chainKey, walletName, addr) {
  const key = walletName + "|" + chainKey;
  loadDiscoveryCache();
  const cached = discoveryMem.data[key];
  if (cached && Date.now() - cached.at < DISCOVERY_TTL) return cached.contracts;
  const c = CHAINS[chainKey];
  if (!c?.blockscout) return cached?.contracts || [];
  const r = await fetchJson(`${c.blockscout}/api/v2/addresses/${addr}/token-balances`, {}, 12000, 1);
  if (r.ok && Array.isArray(r.data)) {
    const contracts = r.data.map(it => {
      const t = it.token || {};
      return { contract: (t.address_hash || t.address || "").toLowerCase(), symbol: t.symbol, name: t.name, decimals: Number(t.decimals || 18) };
    }).filter(x => x.contract);
    discoveryMem.data[key] = { at: Date.now(), contracts };
    saveDiscoveryCache();
    return contracts;
  }
  return cached?.contracts || [];   // Blockscout down → last-good CONTRACT LIST (never a stale balance)
}
// Merge registry ∪ ledger ∪ (background) Blockscout sweep into one deduped list.
async function discoverContracts(chainKey, walletName, addr, regTokens, ledgerContracts) {
  const byContract = new Map();
  const add = (contract, meta) => {
    const k = (contract || "").toLowerCase();
    if (!k) return;
    const prev = byContract.get(k) || {};
    byContract.set(k, { contract: k, symbol: meta.symbol ?? prev.symbol, name: meta.name ?? prev.name, decimals: meta.decimals ?? prev.decimals ?? 18 });
  };
  for (const t of regTokens) if (t.chain === chainKey && t.contract) add(t.contract, { symbol: t.symbol, name: t.name, decimals: t.decimals });
  for (const t of (ledgerContracts || [])) add(t.contract, { symbol: t.symbol, name: t.symbol, decimals: t.decimals });
  // PINNED holdings for this chain are ALWAYS discovered (never depend on a sweep)
  for (const [c, p] of Object.entries(PINNED_HOLDINGS)) if (p.chain === chainKey) add(c, { symbol: p.symbol, name: p.name, decimals: p.decimals });
  try { for (const t of await blockscoutDiscover(chainKey, walletName, addr)) add(t.contract, t); } catch { /* sweep optional */ }
  return [...byContract.values()];
}

// ---------- BATCHED JSON-RPC balances (PRIMARY balance path) ----------
// One HTTP POST carries an array of eth_call balanceOf requests (+ optional
// eth_getBalance for native). rpc.mainnet.chain.robinhood.com answers a batch in
// under a second (verified 2026-07-22). Chunked to keep any single request small.
const BAL_SELECTOR = "0x70a08231"; // balanceOf(address)
async function rpcBatchBalances(rpcUrl, addr, contracts, { includeNative = false } = {}) {
  const padded = addr.toLowerCase().replace(/^0x/, "").padStart(64, "0");
  const calls = contracts.map((t) => ({ contract: t.contract, decimals: t.decimals ?? 18, symbol: t.symbol, name: t.name }));
  const out = new Map();     // contract -> raw balance hex
  let nativeHex = null, anyOk = false, lastErr = null;
  // native goes in the first chunk
  for (let i = 0; i < calls.length || (includeNative && i === 0 && !calls.length); i += 90) {
    const slice = calls.slice(i, i + 90);
    const batch = slice.map((t, j) => ({ jsonrpc: "2.0", id: i + j, method: "eth_call", params: [{ to: t.contract, data: BAL_SELECTOR + padded }, "latest"] }));
    if (includeNative && i === 0) batch.push({ jsonrpc: "2.0", id: "native", method: "eth_getBalance", params: [addr, "latest"] });
    if (!batch.length) break;
    const r = await fetchJson(rpcUrl, rpcBody0(batch), 12000, 2);
    if (!r.ok || !Array.isArray(r.data)) { lastErr = `HTTP ${r.status || 0}${r.text ? " " + String(r.text).slice(0, 60) : ""}`; continue; }
    anyOk = true;
    for (const resp of r.data) {
      if (resp.id === "native") { if (resp.result) nativeHex = resp.result; continue; }
      const idx = Number(resp.id);
      const t = calls[idx];
      if (t && resp.result && resp.result !== "0x") out.set(t.contract, resp.result);
    }
  }
  if (!anyOk && calls.length) throw new Error(lastErr || "rpc batch failed");
  const tokens = [];
  for (const t of calls) {
    const hex = out.get(t.contract);
    if (!hex) continue;
    let qty; try { qty = Number(BigInt(hex)) / 10 ** (t.decimals ?? 18); } catch { continue; }
    if (qty <= 0) continue;
    tokens.push({ contract: t.contract, symbol: t.symbol, name: t.name || t.symbol, qty, decimals: t.decimals ?? 18, priceUsd: null, usd: null, src: "rpc-balanceOf" });
  }
  return { tokens, nativeHex };
}
// batch body helper (array payload) — rpcBody() only wraps a single call
const rpcBody0 = (arr) => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(arr) });
// PINNED GUARANTEE — upstream enumerators (Alchemy getTokenBalances) SPAM-FILTER
// some tokens: verified 2026-07-22 in production that Alchemy silently omitted a
// real held token while returning another from the same wallet. Pinned means
// never hidden, so we read every pinned contract's balanceOf DIRECTLY over RPC
// and add any the enumeration missed. This is the single choke point that makes
// "never hidden" true.
async function ensurePinnedTokens(rpcUrl, addr, chainKey, tokens) {
  const have = new Set((tokens || []).map(t => (t.contract || "").toLowerCase()));
  const padded = addr.toLowerCase().replace(/^0x/, "").padStart(64, "0");
  for (const [c, p] of Object.entries(PINNED_HOLDINGS)) {
    if (p.chain !== chainKey || have.has(c)) continue;
    const r = await fetchJson(rpcUrl, rpcBody("eth_call", [{ to: c, data: BAL_SELECTOR + padded }, "latest"]), 12000, 1);
    if (!r.ok || !r.data?.result || r.data.result === "0x") continue;
    let qty; try { qty = Number(BigInt(r.data.result)) / 10 ** (p.decimals ?? 18); } catch { continue; }
    if (qty <= 0) continue;
    tokens.push({ contract: c, symbol: p.symbol, name: p.name, qty, decimals: p.decimals ?? 18, priceUsd: null, usd: null, src: "rpc-balanceOf (pinned guarantee)" });
  }
  return tokens;
}
// price a token list via DexScreener (stables/dollarTrue = $1); leaves priceUsd
// null when no pool exists (honest — step-6 enrichment + PINNED handling follow).
async function priceTokenList(tokens, regByContract) {
  const need = tokens.filter(x => x.priceUsd == null && !isPinned(x.contract));
  if (need.length) {
    const priced = await dexBatch(need.map(x => x.contract));
    for (const x of need) {
      const reg = regByContract[x.contract];
      if (reg?.dollarTrue) { x.priceUsd = 1; x.usd = x.qty; continue; }
      const p = priced[x.contract];
      if (p?.priceUsd != null) { x.priceUsd = p.priceUsd; x.usd = x.qty * p.priceUsd; if (p.pool) x.pool = p.pool; if (p.pairCreatedAt) x.pairCreatedAt = p.pairCreatedAt; if (p.liq != null) x.liq = p.liq; }
    }
  }
  return tokens;
}

// (rpcRegistryTokens removed 2026-07-22: the RPC-first rewrite promoted batched
//  balanceOf over the full discovery set — see rpcBatchBalances — to PRIMARY, so
//  the old per-registry-contract serial scan is superseded.)

// Alchemy EVM token scan (works on robinhood-mainnet AND base-mainnet — verified live).
// Token metadata (decimals/symbol/name) is immutable → cached forever, so the
// fast lane's repeat scans cost 1 balance call + 1 DexScreener batch, not N metadata calls.
const alchemyMetaCache = new Map(); // host:contract -> {decimals, symbol, name}
async function alchemyTokenScan(host, alchemyKey, addr) {
  const base = `https://${host}.g.alchemy.com/v2/${alchemyKey}`;
  const out = [];
  const bal = await fetchJson(base, rpcBody("alchemy_getTokenBalances", [addr, "erc20"]));
  if (!bal.ok || bal.data?.error) throw new Error(`alchemy ${host}: ${bal.data?.error?.message || "HTTP " + bal.status}`);
  const raw = (bal.data?.result?.tokenBalances || []).filter(t => t.tokenBalance && /[1-9a-f]/.test(t.tokenBalance.replace(/^0x0+/, "")));
  const contracts = raw.map(t => t.contractAddress.toLowerCase());
  const priced = contracts.length ? await dexBatch(contracts) : {};
  for (const t of raw) {
    const c = t.contractAddress.toLowerCase();
    const info = priced[c];
    const mk = host + ":" + c;
    let meta = alchemyMetaCache.get(mk);
    if (!meta) {
      const m = await fetchJson(base, rpcBody("alchemy_getTokenMetadata", [t.contractAddress]));
      meta = { decimals: Number(m.data?.result?.decimals ?? 18), symbol: m.data?.result?.symbol, name: m.data?.result?.name };
      if (m.ok) alchemyMetaCache.set(mk, meta);
    }
    const dec = meta.decimals;
    const qty = Number(BigInt(t.tokenBalance)) / 10 ** dec;
    const priceUsd = info?.priceUsd ?? null;
    out.push({ contract: c, symbol: info?.symbol || meta.symbol, name: info?.name || meta.name, qty, decimals: dec, priceUsd, usd: priceUsd != null ? qty * priceUsd : null, pool: info?.pool, pairCreatedAt: info?.pairCreatedAt, src: `alchemy-${host}+dexscreener` });
  }
  return out;
}

// ---------- Robinhood Chain balances: RPC batch (PRIMARY) → Alchemy RPC ----------
// Blockscout is NO LONGER in this path (root fix 2026-07-22). Balances are read
// directly from rpc.mainnet.chain.robinhood.com via batched balanceOf over the
// discovery set; Blockscout only feeds the (background, disk-cached) discovery.
async function rhBalances(addr, alchemyKey, regTokens, walletName, ledgerContracts, regByContract) {
  const c = CHAINS.robinhood;
  const failures = [];
  let tokens = null, src = null, nativeHex = null;

  const discovered = await discoverContracts("robinhood", walletName, addr, regTokens, ledgerContracts);

  // 1) PRIMARY: batched JSON-RPC balanceOf over the discovery set + native gas
  try {
    const r = await rpcBatchBalances(c.rpc, addr, discovered, { includeNative: true });
    tokens = r.tokens; nativeHex = r.nativeHex; src = "rpc-batch (rpc.mainnet.chain.robinhood.com)";
    await priceTokenList(tokens, regByContract);   // DexScreener; stables=$1; pinned left for downstream
  } catch (e) { failures.push("rpc-batch: " + String(e.message).slice(0, 70)); }

  // 2) FAILOVER: Alchemy robinhood-mainnet (also JSON-RPC; discovery+balance in one)
  if (!tokens && alchemyKey) {
    try { tokens = await alchemyTokenScan("robinhood-mainnet", alchemyKey, addr); src = "alchemy-rpc (failover)"; }
    catch (e) { failures.push("alchemy: " + String(e.message).slice(0, 70)); }
  } else if (!tokens) failures.push("alchemy: no key");

  // native balance: from the batch → raw RPC → Alchemy failover
  const np = await nativePrices();
  if (!nativeHex) {
    let nb = await fetchJson(c.rpc, rpcBody("eth_getBalance", [addr, "latest"]));
    if ((!nb.ok || !nb.data?.result) && alchemyKey) nb = await fetchJson(`https://robinhood-mainnet.g.alchemy.com/v2/${alchemyKey}`, rpcBody("eth_getBalance", [addr, "latest"]));
    if (nb.ok && nb.data?.result) nativeHex = nb.data.result;
  }
  let native = null;
  if (nativeHex) { const eth = Number(BigInt(nativeHex)) / 1e18; native = { symbol: "ETH", qty: eth, priceUsd: np.eth, usd: np.eth != null ? eth * np.eth : null }; }

  const ok = tokens != null;
  return { tokens: tokens || [], native, ok, source: src, failures, err: ok ? null : `all live sources failed — ${failures.join("; ")}` };
}

// ---------- Base balances: Alchemy JSON-RPC (PRIMARY, not Blockscout) → raw RPC ----------
const BASE_RPC = "https://mainnet.base.org";
async function baseBalances(addr, alchemyKey, regTokens, walletName, ledgerContracts, regByContract) {
  const failures = [];
  let tokens = null, src = null;
  const regBase = new Set(regTokens.filter(t => t.chain === "base").map(t => t.contract.toLowerCase()));

  // 1) primary: Alchemy base-mainnet (a JSON-RPC provider — NOT Blockscout — that
  //    returns balances directly; retried inside fetchJson)
  if (alchemyKey) {
    try {
      const scanned = await alchemyTokenScan("base-mainnet", alchemyKey, addr);
      // Base is spam-heavy: keep only priceable tokens above dust — EXCEPT registry
      // tokens (real by definition) and PINNED holdings (Jesse's standing order —
      // the creator coins have no pool so they never price, but must never be hidden).
      tokens = scanned.filter(t => (t.priceUsd != null && (t.usd || 0) >= DUST_USD) || regBase.has(t.contract) || isPinned(t.contract));
      src = "alchemy-rpc";
    } catch (e) { failures.push(String(e.message).slice(0, 80)); }
  } else failures.push("alchemy: no key");

  // 2) failover: raw Base RPC balanceOf over the discovery set (registry ∪ ledger ∪ pinned)
  if (!tokens) {
    try {
      const discovered = await discoverContracts("base", walletName, addr, regTokens, ledgerContracts);
      const r = await rpcBatchBalances(BASE_RPC, addr, discovered);
      tokens = r.tokens; src = "rpc-batch (mainnet.base.org, failover)";
      await priceTokenList(tokens, regByContract);
    } catch (e) { failures.push("rpc: " + String(e.message).slice(0, 60)); }
  }

  // native balance: Alchemy → raw Base RPC failover
  let nb = alchemyKey ? await fetchJson(`https://base-mainnet.g.alchemy.com/v2/${alchemyKey}`, rpcBody("eth_getBalance", [addr, "latest"])) : { ok: false };
  if (!nb.ok || !nb.data?.result) nb = await fetchJson(BASE_RPC, rpcBody("eth_getBalance", [addr, "latest"]));
  const np = await nativePrices();
  let native = null;
  if (nb.ok && nb.data?.result) { const eth = Number(BigInt(nb.data.result)) / 1e18; native = { symbol: "ETH", qty: eth, priceUsd: np.eth, usd: np.eth != null ? eth * np.eth : null }; }

  const ok = tokens != null;
  return { tokens: tokens || [], native, ok, source: src, failures, err: ok ? null : `all live sources failed — ${failures.join("; ")}` };
}

// ---------- Solana balances: Alchemy → public RPC (watch-only) ----------
const SOL_PUBLIC_RPC = "https://api.mainnet-beta.solana.com";
async function solBalances(addr, alchemyKey) {
  const np = await nativePrices();
  const endpoints = [];
  if (alchemyKey) endpoints.push({ name: "alchemy", url: `https://solana-mainnet.g.alchemy.com/v2/${alchemyKey}` });
  endpoints.push({ name: "solana-public-rpc", url: SOL_PUBLIC_RPC });
  const failures = [];
  for (const ep of endpoints) {
    const bal = await fetchJson(ep.url, rpcBody("getBalance", [addr]));
    if (!bal.ok || bal.data?.error || !bal.data?.result) { failures.push(`${ep.name}: ${bal.data?.error?.message || (bal.status ? "HTTP " + bal.status : String(bal.text).slice(0, 50))}`); continue; }
    const sol = (bal.data.result.value || 0) / 1e9;
    const native = { symbol: "SOL", qty: sol, priceUsd: np.sol, usd: np.sol != null ? sol * np.sol : null };
    const out = [];
    const acc = await fetchJson(ep.url, rpcBody("getTokenAccountsByOwner", [addr, { programId: "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA" }, { encoding: "jsonParsed" }]));
    const infos = (acc.data?.result?.value || []).map(a => a.account.data.parsed.info).filter(i => Number(i.tokenAmount?.uiAmount) > 0);
    if (infos.length) {
      const priced = await dexBatch(infos.map(i => i.mint));
      for (const i of infos) {
        const p = priced[i.mint.toLowerCase()] || {};
        const qty = Number(i.tokenAmount.uiAmount);
        const usd = p.priceUsd != null ? qty * p.priceUsd : null;
        out.push({ contract: i.mint, symbol: p.symbol || (i.mint.slice(0, 4) + "…"), name: p.name || "SPL token", qty, decimals: i.tokenAmount.decimals, priceUsd: p.priceUsd ?? null, usd, pool: p.pool, pairCreatedAt: p.pairCreatedAt, src: ep.name + "+dexscreener" });
      }
    }
    return { tokens: out, native, ok: true, source: ep.name, failures, err: null };
  }
  return { tokens: [], native: null, ok: false, source: null, failures, err: `all live sources failed — ${failures.join("; ")}` };
}

// ---------- 1inch open orders (chains 4663 + 8453 — both live-order rails) ----------
async function openOrders(addr, oneinchKey) {
  const all = []; let ok = false, status = 0;
  for (const chainId of ONEINCH_CHAINS) {
    const url = `https://api.1inch.dev/orderbook/v4.0/${chainId}/address/${addr}?page=1&limit=100&statuses=1,2,3&sortBy=createDateTime`;
    const r = await fetchJson(url, { headers: { Authorization: `Bearer ${oneinchKey}`, Accept: "application/json" } });
    const arr = Array.isArray(r.data) ? r.data : (r.data?.orders || []);
    if (r.ok) { ok = true; for (const o of (Array.isArray(arr) ? arr : [])) { o._chainId = chainId; all.push(o); } }
    else status = r.status;
  }
  return { ok, status, orders: all };
}

// ---------- registry helpers ----------
function buildRegistryIndex(registry) {
  const byContract = {}, decoyOf = {}, bySymbol = {};
  for (const [sym, t] of Object.entries(registry.tokens || {})) {
    if (!t.contract) continue;
    byContract[t.contract.toLowerCase()] = { symbol: sym, ...t };
    bySymbol[sym] = { symbol: sym, ...t };
    for (const d of t.decoys || []) decoyOf[d.toLowerCase()] = sym;
  }
  return { byContract, decoyOf, bySymbol };
}
function registryStatus(contract, idx) {
  const c = (contract || "").toLowerCase();
  if (idx.decoyOf[c]) return { status: "DECOY", of: idx.decoyOf[c] };
  if (idx.byContract[c]) return { status: "AUTHORIZED", of: idx.byContract[c].symbol };
  return { status: "UNVERIFIED", of: null };
}

// ---------- ledger ----------
function readLedgerRows() {
  try {
    return readFileSync(LEDGER, "utf8").trim().split("\n").filter(Boolean)
      .map(l => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
  } catch { return []; }
}

// ---------- token→token counter-leg resolution (Blockscout, cached forever per tx+contract) ----------
const txLegCache = new Map();
async function receivedQtyFromTx(txHash, contract, walletAddr) {
  const key = (txHash + "|" + contract).toLowerCase();
  if (txLegCache.has(key)) return txLegCache.get(key);
  let qty = null;
  const r = await fetchJson(`${CHAINS.robinhood.blockscout}/api/v2/transactions/${txHash}/token-transfers`);
  if (r.ok && Array.isArray(r.data?.items)) {
    let sum = 0, found = false;
    for (const t of r.data.items) {
      const tokAddr = (t.token?.address_hash || t.token?.address || "").toLowerCase();
      const to = (t.to?.hash || "").toLowerCase();
      if (tokAddr === contract.toLowerCase() && to === walletAddr.toLowerCase()) {
        const dec = Number(t.total?.decimals ?? t.token?.decimals ?? 18);
        sum += Number(t.total?.value || 0) / 10 ** dec;
        found = true;
      }
    }
    if (found) qty = sum;
  }
  txLegCache.set(key, qty);
  return qty;
}

// ---------- token age → default candle timeframe (Jesse rule) ----------
// launched <30d → 1h candles · 30–60d → 4h · >60d → daily
const ageCache = new Map(); // contract(lower) -> pairCreatedAt ms | null
function tfForAgeDays(days) {
  if (days == null) return "1h"; // most of these chains are brand-new; honest default
  if (days < 30) return "1h";
  if (days <= 60) return "4h";
  return "1d";
}

// ============================================================
// TWO-LANE STATE PIPELINE (Jesse, 2026-07-21: "wallet values sit frozen";
// 2026-07-22 freshness mandate: "the system must never look fresh when it is not"):
//   FAST lane  — wallet token+native balances (batched RPC, cheap) + current
//                prices. 15s TTL: position balances are now ONE batched RPC call
//                per wallet, so ~15s is affordable and held-token prices stay
//                well under the 2-minute stale line. The UI polls every ~12s.
//   ORDERS lane— 1inch open-orders book. 120s TTL: a 30s cadence would burn
//                ~172K calls/mo if the dashboard stayed open 24/7, breaching
//                the 1inch dev-tier 100K/mo cap; 120s worst-cases at ~86K/mo.
//   HEAVY lane — chain tx-history swap-scan (history.mjs) behind the existing
//                15-min enrichCache; counter-leg + token-age lookups cached
//                forever per tx/contract. Basis/lots math itself is in-memory
//                and re-assembled fresh on every call.
// /api/state merges: fresh balances/prices over cached heavy artifacts, with
// per-section freshness stamps (freshness.balancesAt / pricesAt / ordersAt / scanAt)
// the header renders as visible ages (amber >2min, red >5min).
// Doctrine unchanged: on TTL expiry the lane does a LIVE fetch (with retries
// + failover) — expired data is never served without a live attempt.
// ============================================================
const fastCache   = { at: 0, ttl: 15_000,  data: null, inflight: null };
const ordersCache = { at: 0, ttl: 120_000, data: null, inflight: null };
// Coinbase exchange balances (read-only JWT, see coinbase-balances.mjs) —
// Jesse 2026-07-22: the exchange account is part of the portfolio and must
// show on the dashboard, not just feed cost-basis history.
const coinbaseCache = { at: 0, ttl: 120_000, data: null, inflight: null };
async function laneGet(cache, producer) {
  if (cache.data && Date.now() - cache.at < cache.ttl) return cache.data;
  if (!cache.inflight) {
    cache.inflight = producer()
      .then(d => { cache.data = d; cache.at = Date.now(); return d; })
      .finally(() => { cache.inflight = null; });
  }
  return await cache.inflight; // TTL expired → await the LIVE refresh (single-flight)
}

// FAST lane producer: balances + native + prices for every wallet (no orders)
async function scanWallets(walletsPub, ALCHEMY, regTokensArr, ledgerContractsByKey, regByContract) {
  const walletData = {};
  await Promise.all(walletsPub.map(async (w) => {
    const wd = { name: w.name, address: w.address, note: w.note, watchOnly: !!w.watchOnly, retiring: !!w.retiring, chains: {}, errors: [] };
    const lc = (chain) => ledgerContractsByKey[w.name + "|" + chain] || [];
    for (const chain of w.chains) {
      try {
        if (chain === "robinhood") wd.chains.robinhood = await rhBalances(w.address, ALCHEMY, regTokensArr, w.name, lc("robinhood"), regByContract);
        else if (chain === "base") wd.chains.base = await baseBalances(w.address, ALCHEMY, regTokensArr, w.name, lc("base"), regByContract);
        else if (chain === "solana") wd.chains.solana = await solBalances(w.address, ALCHEMY);
      } catch (e) { wd.errors.push(`${chain}: ${e.message}`); }
    }
    walletData[w.name] = wd;
  }));
  return walletData;
}

// ORDERS lane producer: live 1inch book per executing wallet
async function scanOrders(walletsPub, ONEINCH) {
  const byWallet = {}, errors = {};
  await Promise.all(walletsPub.map(async (w) => {
    if (w.watchOnly || !ONEINCH) { byWallet[w.name] = { ok: true, orders: [], watchOnly: true }; return; }
    try { byWallet[w.name] = await openOrders(w.address, ONEINCH); }
    catch (e) { byWallet[w.name] = { ok: false, orders: [] }; errors[w.name] = "orders: " + e.message; }
  }));
  return { byWallet, errors };
}

// ---------- MAIN ----------
export async function buildState() {
  const registry = readJson(join(MODULE, "registry.json"));
  const walletsPub = readJson(join(HERE, "wallets.public.json")).wallets;
  const idx = buildRegistryIndex(registry);
  const ONEINCH = readEnvKey("ONEINCH_API_KEY");
  const ALCHEMY = readEnvKey("ALCHEMY_API_KEY");
  const addrOf = Object.fromEntries(walletsPub.map(w => [w.name, w.address]));
  const walletNames = new Set(walletsPub.map(w => w.name));
  const regTokensArr = Object.values(idx.bySymbol).filter(t => t.contract);
  // Jesse's own EVM wallets (all of them, incl. the retiring one) — used to
  // classify wallet↔wallet moves as INTERNAL TRANSFERS, not buys/sells.
  const ownWalletAddrs = new Set(walletsPub.filter(w => (w.chains || []).some(c => c !== "solana")).map(w => w.address.toLowerCase()));

  // LEDGER (read ONCE, reused by discovery + basis) — canonical basis source.
  const ledgerRows = readLedgerRows();
  // DISCOVERY hint: contracts each wallet has TOUCHED on-chain per the ledger, so
  // the RPC balance read covers held bags even before the hourly Blockscout sweep.
  const ledgerContractsByKey = {};
  for (const r of ledgerRows) {
    if (r.venue === "coinbase" || !r.contract || !r.wallet || !r.chain) continue;
    const key = r.wallet + "|" + r.chain;
    (ledgerContractsByKey[key] ||= []).push({ contract: r.contract.toLowerCase(), symbol: r.token, decimals: idx.byContract[r.contract.toLowerCase()]?.decimals ?? 18 });
  }

  // orders-log parse (freshness net for trades newer than the last ledger ingest)
  const logLines = readFileSync(join(MODULE, "orders-log.jsonl"), "utf8").trim().split("\n").filter(Boolean).map(l => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);

  // known chain-confirmed fills (hand-pinned tx links for fills the book can't name)
  const CONFIRMED_FILLS = {
    "0x6924fa4f9f2ff06beeb8eb5842b264c9f06d0386fab0b1ca6faa07a3a1b914ee": { fillTxHash: "0x8aee863ec46a6036887df3dad3d2f986cddf48d0a2fe51a1080818457d28301e", note: "BASTION canary — filled 2026-07-20 20:21 UTC during +446% spike; +4.2817 USDG chain-verified" },
  };

  // FAST + ORDERS lanes (each single-flight, live-refreshed on its own TTL)
  const fastScan = await laneGet(fastCache, () => scanWallets(walletsPub, ALCHEMY, regTokensArr, ledgerContractsByKey, idx.byContract));
  const orderScan = await laneGet(ordersCache, () => scanOrders(walletsPub, ONEINCH));
  const coinbase = await laneGet(coinbaseCache, () => fetchCoinbaseBalances());
  // merge into per-call walletData WITHOUT mutating the cached lane objects
  const walletData = {};
  for (const w of walletsPub) {
    const fw = fastScan[w.name] || { name: w.name, address: w.address, chains: {}, errors: ["fast scan missing"] };
    walletData[w.name] = { ...fw, errors: [...(fw.errors || []), ...(orderScan.errors[w.name] ? [orderScan.errors[w.name]] : [])], orders: orderScan.byWallet[w.name] || { ok: false, orders: [] } };
  }

  // ---- positions: key = wallet::contract ----
  const positions = {};
  const ensurePos = (wallet, chain, contract, seed = {}) => {
    const key = wallet + "::" + (contract || "").toLowerCase();
    if (!positions[key]) {
      const rs = registryStatus(contract, idx);
      positions[key] = {
        key, wallet, chain, contract: contract || null,
        ticker: seed.ticker || null, name: seed.name || null,
        gtNetwork: CHAINS[chain]?.gtNetwork || chain,
        pool: seed.pool || null,
        registryStatus: rs.status, registryOf: rs.of,
        isStable: !!(rs.status === "AUTHORIZED" && idx.byContract[(contract || "").toLowerCase()]?.dollarTrue),
        currentQty: 0, priceUsd: null, marketValue: null,
        lots: [], openOrders: [], cancelledOrders: [],
        pairCreatedAt: null,
      };
    }
    const p = positions[key];
    if (seed.ticker && !p.ticker) p.ticker = seed.ticker;
    if (seed.name && !p.name) p.name = seed.name;
    if (seed.pool && !p.pool) p.pool = seed.pool;
    if (seed.pairCreatedAt && !p.pairCreatedAt) p.pairCreatedAt = seed.pairCreatedAt;
    return p;
  };
  const addLot = (p, lot) => { p.lots.push(lot); };

  // 1) balances → current bag
  let dedupedDust = 0;
  for (const w of walletsPub) {
    const wd = walletData[w.name];
    for (const [chain, cd] of Object.entries(wd.chains)) {
      // symbol-squatter dedupe: if this wallet+chain holds the AUTHORIZED contract
      // for a symbol, drop UNVERIFIED same-symbol fragments worth < $1 (e.g. the
      // stray wallet-1 "USDG" qty-2/$0.00 squatter next to the real 21.26 USDG).
      // Registry-flagged DECOYs are NOT dropped — they stay visible as decoys.
      const authorizedSyms = new Set((cd.tokens || [])
        .filter(b => registryStatus(b.contract, idx).status === "AUTHORIZED")
        .map(b => (registryStatus(b.contract, idx).of || "").toUpperCase()));
      for (const b of (cd.tokens || [])) {
        const rs = registryStatus(b.contract, idx);
        const pin = PINNED_HOLDINGS[(b.contract || "").toLowerCase()];
        // PROTECTED HOLDINGS (Jesse's standing order): render as real positions,
        // never dedupe/decoy/dust-hide, never invent a price. This MUST run before
        // the squatter-dedupe and decoy branches so a pinned token can never fall
        // through them.
        if (pin) {
          const p = ensurePos(w.name, chain, b.contract, { ticker: pin.symbol, name: pin.name, pool: b.pool, pairCreatedAt: b.pairCreatedAt });
          p.currentQty = b.qty; p.decimals = b.decimals ?? pin.decimals; p.balanceSrc = b.src;
          p.isPinned = true; p.pinnedNote = "shown by standing order (doctrine 2026-07-22 §5)";
          // valuation honesty: only a REAL pool prices a pinned token; otherwise
          // show the balance and label the price unverified (never MetaMask's fake feed).
          if (b.priceUsd != null && (b.usd || 0) > 0) { p.priceUsd = b.priceUsd; p.marketValue = b.usd; p.priceUnverified = false; }
          else { p.priceUsd = null; p.marketValue = null; p.priceUnverified = true; }
          if (b.liq != null) p.liq = b.liq;
          continue;
        }
        if (rs.status === "UNVERIFIED" && (b.usd || 0) < DUST_USD && authorizedSyms.has((b.symbol || "").toUpperCase())) { dedupedDust++; continue; }
        if (rs.status === "DECOY") { // record but never chart/trade
          const p = ensurePos(w.name, chain, b.contract, { ticker: b.symbol, name: b.name, pool: b.pool });
          p.currentQty = b.qty; p.priceUsd = null; p.marketValue = null; p.isDecoy = true;
          continue;
        }
        const ticker = rs.status === "AUTHORIZED" ? rs.of : b.symbol;
        const reg = idx.bySymbol[ticker];
        const p = ensurePos(w.name, chain, b.contract, { ticker, name: b.name, pool: reg?.mainPool || b.pool, pairCreatedAt: b.pairCreatedAt });
        p.currentQty = b.qty; p.priceUsd = b.priceUsd; p.marketValue = b.usd;
        p.balanceSrc = b.src; p.decimals = b.decimals;
        if (b.liq != null) p.liq = b.liq;
      }
    }
  }

  // 1b) EVERY AUTHORIZED registry token gets a position on the DEFAULT wallet even at
  //     zero balance (2026-07-23, quick-buy-from-suggestions build): the trade panel and
  //     the suggestion-card inline buy resolve tokens by positionKey, so a freshly
  //     vet-lite'd token must exist in state before its first-ever buy. Zero-balance
  //     rows are priced by the normal enrichment below and hidden by the dashboard's
  //     dust filter — they don't clutter the cards.
  {
    const defaultWallet = walletsPub.find(w => w.default) || walletsPub[0];
    if (defaultWallet) for (const t of regTokensArr) {
      if (t.dollarTrue) continue;                        // stables aren't trade targets
      if (!CHAINS[t.chain]) continue;
      if ((defaultWallet.chains || []).includes(t.chain))
        ensurePos(defaultWallet.name, t.chain, t.contract, { ticker: t.symbol, pool: t.mainPool || null });
    }
  }

  // 2) LEDGER → every individual buy & sell lot (source of truth for basis)
  //    (ledgerRows already read once at the top of buildState and reused here)
  const ledgerFilledHashes = new Set();  // order hashes the ledger already accounts for
  const ledgerTxs = new Set();           // tx hashes the ledger already accounts for
  const closed = {};                     // fully-exited / unaccounted bags: key wallet::chain::contract-or-token
  const coinbaseByTicker = {};           // cross-venue hint (Coinbase history for same ticker)
  const ensureClosed = (wallet, chain, token, contract) => {
    const key = wallet + "::" + chain + "::" + ((contract || token || "").toLowerCase());
    if (!closed[key]) closed[key] = { key, wallet, chain, token, contract: contract || null, lots: [] };
    return closed[key];
  };

  const coinbaseFillsByTicker = {};       // detail rows for the basis join (fix: "no unknown cost basis")
  for (const r of ledgerRows) {
    if (r.venue === "coinbase") {
      const t = (r.token || "").toUpperCase();
      if (!coinbaseByTicker[t]) coinbaseByTicker[t] = { buys: 0, buyQty: 0, buyUsd: 0, sells: 0, sellQty: 0, sellUsd: 0, first: r.timestamp, last: r.timestamp };
      const cb = coinbaseByTicker[t];
      if (r.status === "filled") {
        if (r.side === "buy") { cb.buys++; cb.buyQty += r.qty || 0; cb.buyUsd += r.usd_value || 0; }
        else { cb.sells++; cb.sellQty += r.qty || 0; cb.sellUsd += r.usd_value || 0; }
        if (r.timestamp > cb.last) cb.last = r.timestamp;
        if (r.timestamp < cb.first) cb.first = r.timestamp;
        (coinbaseFillsByTicker[t] ||= []).push({ id: r.id, side: r.side, qty: r.qty ?? null, priceUsd: r.price_usd ?? null, usd: r.usd_value ?? null, time: r.timestamp });
      }
      continue;
    }
    if (!walletNames.has(r.wallet)) continue;
    if (r.order_hash) { if (r.status === "filled") ledgerFilledHashes.add(r.order_hash.toLowerCase()); }
    if (r.tx_hash) ledgerTxs.add(r.tx_hash.toLowerCase());
    if (r.status !== "filled") continue; // resting/cancelled state comes from the LIVE book below

    const lot = {
      time: r.timestamp, side: r.side, qty: r.qty ?? null, priceUsd: r.price_usd ?? null,
      usd: r.usd_value ?? null, tx: r.tx_hash || null, orderHash: r.order_hash || null,
      venue: r.venue, source: r.source, confidence: r.confidence,
      counter: r.counter_token || null, note: r.notes || null, ledgerId: r.id,
    };
    // match to a held position by wallet+contract, else wallet+chain+ticker
    let p = null;
    if (r.contract) p = positions[r.wallet + "::" + r.contract.toLowerCase()];
    if (!p) p = Object.values(positions).find(x => x.wallet === r.wallet && x.chain === r.chain && !x.isDecoy && (x.ticker || "").toUpperCase() === (r.token || "").toUpperCase());
    if (p && !p.isDecoy) { addLot(p, lot); continue; }
    if (p && p.isDecoy) continue; // never account decoy dust
    addLot(ensureClosed(r.wallet, r.chain, r.token, r.contract), lot);
  }

  // 3) orders-log market buys newer than the last ledger ingest (dedupe by tx hash)
  for (const rec of logLines) {
    const wallet = rec.wallet || "wallet-1";
    if (rec.type === "market_buy") {
      if (rec.txHash && ledgerTxs.has(rec.txHash.toLowerCase())) continue; // ledger already has it
      const sym = rec.dst; const reg = idx.bySymbol[sym]; if (!reg) continue;
      const p = ensurePos(wallet, reg.chain, reg.contract, { ticker: sym, name: reg.name, pool: reg.mainPool });
      addLot(p, { time: rec.time, side: "buy", qty: rec.received, priceUsd: rec.execPriceUsd, usd: rec.paidUsd, tx: rec.txHash, orderHash: null, venue: "module", source: "orders-log", confidence: "exact", counter: rec.src, note: `market swap via 1inch (exec vs mid ${rec.execVsMidPct != null ? rec.execVsMidPct.toFixed(2) + "%" : "—"})` });
    } else if (rec.orderHash) {
      const sym = rec.token; const reg = idx.bySymbol[sym]; if (!reg) continue;
      const p = ensurePos(wallet, reg.chain, reg.contract, { ticker: sym, name: reg.name, pool: reg.mainPool });
      p._logOrders = p._logOrders || {};
      p._logOrders[rec.orderHash.toLowerCase()] = rec;
    }
  }

  // 4) reconcile orders-log entries against the LIVE 1inch book (open orders + fresh fills)
  for (const w of walletsPub) {
    if (w.watchOnly) continue;
    const wd = walletData[w.name];
    const liveByHash = {};
    for (const o of (wd.orders.orders || [])) liveByHash[o.orderHash.toLowerCase()] = o;

    for (const key of Object.keys(positions)) {
      const p = positions[key];
      if (p.wallet !== w.name || !p._logOrders) continue;
      for (const [hash, rec] of Object.entries(p._logOrders)) {
        const live = liveByHash[hash];
        if (live) {
          const mk = BigInt(live.data.makingAmount), rem = BigInt(live.remainingMakerAmount || live.data.makingAmount);
          const filledPct = mk > 0n ? Number(mk - rem) * 100 / Number(mk) : 0;
          const reason = live.orderInvalidReason;
          // 1inch keeps FILLED orders on the book with orderInvalidReason "order filled".
          const isFilled = (reason && /filled/i.test(reason)) || filledPct >= 99.5;
          const isCancelled = reason && /cancel/i.test(reason);
          if (isFilled) {
            if (!ledgerFilledHashes.has(hash)) { // ledger hasn't ingested this fill yet
              const conf = CONFIRMED_FILLS[hash];
              addLot(p, { time: live.lastChangedTime || rec.time, side: rec.side, qty: rec.qty, priceUsd: rec.limitPriceUsd, usd: rec.orderUsd, tx: conf?.fillTxHash || null, orderHash: hash, venue: "1inch-book", source: "live-book", confidence: "exact", counter: null, note: conf?.note || `1inch book reports "${reason || "filled"}" (${filledPct.toFixed(1)}% filled)` });
            }
            continue;
          }
          if (isCancelled) {
            p.cancelledOrders.push({ orderHash: hash, side: rec.side, qty: rec.qty, limitPriceUsd: rec.limitPriceUsd, usd: rec.orderUsd, time: rec.time, reason });
            continue;
          }
          let status = "resting";
          if (reason && /balance|allowance/i.test(reason)) status = "underfunded";
          else if (reason) status = "blocked";
          if (filledPct > 0.5 && filledPct < 99.5) status = "partial";
          p.openOrders.push({
            orderHash: hash, side: rec.side, qty: rec.qty, limitPriceUsd: rec.limitPriceUsd,
            usd: rec.orderUsd, expiresAt: rec.expiresAt, createdAt: rec.time,
            status, filledPct, reason: reason || null, chainId: live._chainId,
          });
        } else {
          // not on the book → filled (we never cancel; expiries are ~100 days out)
          if (!ledgerFilledHashes.has(hash)) {
            const conf = CONFIRMED_FILLS[hash];
            addLot(p, { time: rec.time, side: rec.side, qty: rec.qty, priceUsd: rec.limitPriceUsd, usd: rec.orderUsd, tx: conf?.fillTxHash || null, orderHash: hash, venue: "1inch-book", source: "live-book", confidence: conf ? "exact" : "estimate", counter: null, note: conf?.note || "inferred filled (dropped off live book)" });
          }
        }
      }
    }
  }

  // 5) token→token counter-legs: held positions with NO buy lots may have been
  //    acquired by disposing another token (e.g. VIM→KARMA). Resolve the real
  //    received qty from the tx so the basis is REAL, not fabricated.
  const STABLE_SYMBOLS = new Set(["USDG", "USDC", "USDT", "DAI", "USDE", "USD"]);
  await Promise.all(Object.values(positions).map(async (p) => {
    if (p.chain !== "robinhood" || p.isDecoy || p.isStable || !p.contract || !p.ticker) return;
    if (STABLE_SYMBOLS.has(p.ticker.toUpperCase())) return; // dollar legs are settlement, not positions needing basis
    if (p.lots.some(l => l.side === "buy")) return;
    const feeders = ledgerRows.filter(r =>
      r.venue !== "coinbase" && r.status === "filled" && r.side === "sell" &&
      r.wallet === p.wallet && r.chain === p.chain && r.tx_hash &&
      (r.counter_token || "").toUpperCase() === (p.ticker || "").toUpperCase());
    for (const r of feeders) {
      try {
        const qty = await receivedQtyFromTx(r.tx_hash, p.contract, addrOf[p.wallet]);
        addLot(p, {
          time: r.timestamp, side: "buy", qty: qty ?? null,
          priceUsd: (qty && r.usd_value != null) ? r.usd_value / qty : null,
          usd: r.usd_value ?? null, tx: r.tx_hash, orderHash: null,
          venue: r.venue, source: "derived-counter-leg", confidence: "estimate", counter: r.token,
          note: `counter leg of ${r.token} sell — received ${p.ticker} in the same swap (qty chain-verified via Blockscout)`,
        });
      } catch {}
    }
  }));

  // 5.5) CHAIN SWAP-SCAN GAP-FILL (history.mjs) — the pieces the ledger + counter-legs
  //      still miss: native-ETH-paid buys (BASTION) and routed/relayer Fusion
  //      settlements (VEX). Only positions that STILL have no buy lot get filled, and
  //      only fills not already present (dedup by tx / orderHash / side+qty≈1%). This
  //      turns their avgCost from UNKNOWN into a real, chain-verified basis.
  let histTransfers = [];
  try {
    const authorizedContracts = Object.values(idx.byContract).map(t => t.contract.toLowerCase());
    const hist = await getHistoryIndex(walletsPub, authorizedContracts, ownWalletAddrs);
    const H = hist?.index || {};
    histTransfers = hist?.transfers || [];
    for (const p of Object.values(positions)) {
      if (p.isDecoy || p.isStable || !p.contract || (p.currentQty || 0) <= 0) continue;
      if (p.lots.some(l => l.side === "buy")) continue; // already has basis; don't touch
      const fills = H[p.key] || Object.values(H).find(f => f.wallet === p.wallet && (f.contract || "") === p.contract);
      if (!fills) continue;
      const dup = (side, qty, tx, orderHash) => p.lots.some(l =>
        (tx && l.tx && l.tx.toLowerCase() === tx.toLowerCase()) ||
        (orderHash && l.orderHash && l.orderHash.toLowerCase() === orderHash.toLowerCase()) ||
        (l.side === side && qty != null && l.qty != null && Math.abs(l.qty - qty) <= Math.abs(qty) * 0.01));
      for (const f of [...(fills.buys || []), ...(fills.sells || [])]) {
        if (dup(f.side, f.qty, f.txHash, f.orderHash)) continue;
        addLot(p, {
          time: f.time, side: f.side, qty: f.qty ?? null, priceUsd: f.priceUsd ?? null, usd: f.usd ?? null,
          tx: f.txHash || null, orderHash: f.orderHash || null,
          venue: f.source === "ledger" ? (f.note && /order/i.test(f.note) ? "1inch" : "ledger") : "chain-scan",
          source: f.source === "ledger" ? "ledger" : "chain-swap-scan", confidence: f.confidence || "estimate",
          counter: f.counter || null, note: f.note || "chain swap-scan gap-fill",
        });
      }
    }
  } catch (e) { /* history unavailable → positions keep honest UNKNOWN basis */ }

  // 5.6) WALLET-CONSOLIDATION BASIS CARRY (Jesse 2026-07-22: moved ALL holdings
  //      into wallet-2; wallet-1 retiring). A token moved between Jesse's OWN
  //      wallets is a TRANSFER, not a buy/sell — cost basis must CARRY to the
  //      destination, realized P&L must stay unchanged, and NO phantom buy/sell
  //      may appear (history.mjs already suppresses the transfer legs; see there).
  //      This re-homes the source wallet's REAL ledger/chain lots onto the holder
  //      of the consolidated bag. It fabricates NOTHING (every lot is a real fill,
  //      just re-attributed) and needs NO ledger schema change. Signal, all from
  //      data already in hand (survives a Blockscout outage):
  //        (a) destination B holds contract C with a bag but no priced buy basis,
  //        (b) another OWN wallet A has lots for C (live or closed),
  //        (c) A now holds ~0 of C, and A's surviving qty (bought−sold) ≈ B's bag.
  //      A chain-verified own→own transfer edge (history.transfers), when present,
  //      upgrades the provenance label; the qty-match gate is what authorizes it.
  {
    const CARRY_TOL = 0.02;                    // 2% qty window (fees/rounding/dust)
    const currentQtyOf = (wallet, contract) => {
      const p = positions[wallet + "::" + (contract || "").toLowerCase()];
      return p ? (p.currentQty || 0) : 0;
    };
    const survivingLots = (rec) => {           // rec = a closed{} or position{} with lots
      const buys = rec.lots.filter(l => l.side === "buy");
      const sells = rec.lots.filter(l => l.side === "sell");
      const bought = buys.reduce((s, l) => s + (l.qty || 0), 0);
      const sold = sells.reduce((s, l) => s + (l.qty || 0), 0);
      return { bought, sold, surviving: bought - sold, lots: rec.lots };
    };
    for (const p of Object.values(positions)) {
      if (p.isDecoy || p.isStable || p.isPinned || !p.contract || (p.currentQty || 0) <= 0) continue;
      if (p.lots.some(l => l.side === "buy")) continue;   // real basis already found upstream
      const cLower = p.contract.toLowerCase();
      // find another own wallet that holds lots for this exact contract (closed first, then a live position)
      const sources = [];
      for (const [key, rec] of Object.entries(closed)) {
        if (rec.wallet === p.wallet) continue;
        if ((rec.contract || "").toLowerCase() !== cLower) continue;
        if (!rec.lots.length) continue;
        sources.push({ where: "closed", key, rec });
      }
      for (const [key, other] of Object.entries(positions)) {
        if (other === p || other.wallet === p.wallet) continue;
        if ((other.contract || "").toLowerCase() !== cLower || !other.lots.length) continue;
        sources.push({ where: "position", key, rec: other });
      }
      let carried = false;
      for (const s of sources) {
        if (carried) break;
        const { surviving } = survivingLots(s.rec);
        const srcNowHolds = currentQtyOf(s.rec.wallet, cLower);
        // A must have essentially emptied this bag AND its surviving qty must match B's bag
        if (srcNowHolds > Math.max(1, p.currentQty * CARRY_TOL)) continue;
        if (surviving <= 0) continue;
        if (Math.abs(surviving - p.currentQty) > Math.max(1, p.currentQty * CARRY_TOL)) continue;
        // chain-verified transfer edge (optional provenance upgrade)
        const edge = histTransfers.find(t => (t.contract || "").toLowerCase() === cLower &&
          t.fromWallet === s.rec.wallet && t.toWallet === p.wallet);
        const prov = edge ? `chain transfer ${String(edge.tx).slice(0, 12)}… verified` : "qty-window match (transfer not chain-confirmed this pass)";
        for (const l of s.rec.lots) {
          addLot(p, { ...l, source: (l.source || "") + "|consolidation-carry",
            note: `carried from ${s.rec.wallet} on wallet consolidation (${prov}) — ${l.note || l.side}` });
        }
        p.basisCarriedFrom = { wallet: s.rec.wallet, surviving, matchedBag: p.currentQty, provenance: prov, tx: edge?.tx || null };
        s.rec.lots = [];                       // emptied — do not double-count in closed/other
        if (s.where === "closed") delete closed[s.key];
        else { s.rec.carriedTo = p.wallet; }
        carried = true;
      }
    }
  }

  // 5.7) COINBASE-WITHDRAWAL BASIS JOIN (Jesse: "you're connected to my Coinbase
  //      account... there should be no unknown cost basis"). For on-chain bags that
  //      STILL have no acquisition record after the ledger, counter-legs, and the
  //      chain swap-scan: match the ticker's Coinbase BUY fills, walking newest-first
  //      until the cumulative bought qty covers the held bag (quantity window). If it
  //      does, inherit the qty-weighted Coinbase cost with the fill refs, labeled
  //      "basis from Coinbase history". If it does NOT (or there are no buys), attach
  //      the candidate fills instead of guessing — NEVER fabricate a number.
  for (const p of Object.values(positions)) {
    if (p.isDecoy || p.isStable || (p.currentQty || 0) <= 0) continue;
    if (p.lots.some(l => l.side === "buy")) continue;       // real basis already found upstream
    const tk = (p.ticker || "").toUpperCase();
    const rows = coinbaseFillsByTicker[tk] || [];
    if (!rows.length) continue;                              // no Coinbase history at all for this ticker
    const buys = rows.filter(r => r.side === "buy" && r.qty > 0 && r.usd != null)
      .sort((a, b) => new Date(b.time) - new Date(a.time)); // newest first — closest to the withdrawal
    let acc = 0, usd = 0; const used = [];
    for (const b of buys) { used.push(b); acc += b.qty; usd += b.usd; if (acc >= p.currentQty * 0.999) break; }
    if (buys.length && acc >= p.currentQty * 0.999) {
      const avg = usd / acc;
      addLot(p, {
        time: used[used.length - 1].time, side: "buy", qty: p.currentQty,
        priceUsd: avg, usd: avg * p.currentQty, tx: null, orderHash: null,
        venue: "coinbase", source: "coinbase-history", confidence: "estimate", counter: "USD",
        note: `basis from Coinbase history — qty-weighted avg of ${used.length} Coinbase buy fill(s) covering this bag (joined by symbol + quantity window, not tx-linked): ${used.map(u => String(u.id).replace("cb:fill:", "").slice(0, 8)).join(", ")}`,
      });
      p.basisFromCoinbase = { nFills: used.length, avgCost: avg, fills: used };
    } else {
      p.coinbaseBasisCandidates = {
        matched: false,
        reason: buys.length
          ? `Coinbase buys cover only ${acc.toFixed(4)} of the held ${p.currentQty.toFixed(4)} ${tk} — ambiguous, candidates shown instead of a guessed basis`
          : `Coinbase shows 0 buy fills for ${tk} (${rows.filter(r => r.side === "sell").length} sells only) — the coins reached Coinbase via convert/transfer, which the fills API cannot see; basis left honestly unknown`,
        fills: rows.slice(0, 12),
      };
    }
  }

  // 6) enrich: DexScreener for missing price/pool + token AGE (cached forever).
  //    BATCHED: one DexScreener call per 30 contracts (fast-lane rate hygiene),
  //    not one call per position.
  const needEnrich = Object.values(positions).filter(p => p.contract && !p.isDecoy && !p.isStable &&
    (p.priceUsd == null || !p.pool || (!p.pairCreatedAt && !ageCache.has(p.contract.toLowerCase()))));
  const enrichContractsList = [...new Set(needEnrich.map(p => p.contract.toLowerCase()))];
  const pairsByContract = {};
  for (let i = 0; i < enrichContractsList.length; i += 30) {
    const r = await fetchJson("https://api.dexscreener.com/latest/dex/tokens/" + enrichContractsList.slice(i, i + 30).join(","));
    for (const pair of (r.data?.pairs || [])) {
      const base = (pair.baseToken?.address || "").toLowerCase();
      if (base) (pairsByContract[base] ||= []).push(pair);
    }
  }
  // DexScreener caps EVERY response at ~30 pairs and silently drops the rest.
  // A batch containing a many-pair contract (NVDA matches dozens of pools across
  // chains) starves low-liquidity contracts out of the response — this is exactly
  // how two real low-liquidity bags priced null and counted $0 in the
  // portfolio (defect found 2026-07-22). Any contract the batch returned NO pairs
  // for gets its own single-contract query before we accept "no market".
  const missedEnrich = enrichContractsList.filter(c => !pairsByContract[c]);
  for (const c of missedEnrich) {
    const r = await fetchJson("https://api.dexscreener.com/latest/dex/tokens/" + c);
    for (const pair of (r.data?.pairs || [])) {
      const base = (pair.baseToken?.address || "").toLowerCase();
      if (base) (pairsByContract[base] ||= []).push(pair);
    }
  }
  for (const p of needEnrich) {
    const pairs = pairsByContract[p.contract.toLowerCase()] || [];
    // registry-mainPool preference + median poison filter (the PONS $6e+26 pair lesson)
    const best = bestPair(p.contract.toLowerCase(), pairs);
    if (!best) { ageCache.set(p.contract.toLowerCase(), null); continue; }
    if (!p.pool && best.pairAddress) p.pool = best.pairAddress;
    if (p.liq == null && best.liquidity?.usd != null) p.liq = best.liquidity.usd;
    if (p.priceUsd == null && best.priceUsd != null) {
      // PINNED tokens only accept a price from a pool with REAL liquidity — a
      // creator coin with no real market stays "price unverified", never a fake feed.
      if (p.isPinned && (best.liquidity?.usd || 0) < 1000) { /* keep unverified */ }
      else {
        p.priceUsd = Number(best.priceUsd);
        p.marketValue = p.currentQty * p.priceUsd;
        p.balanceSrc = (p.balanceSrc || "") + "+dexscreener-price";
        if (p.isPinned) p.priceUnverified = false;
      }
    }
    // age: prefer the pair we actually chart, else the oldest pair (token launch ≈ first pool)
    const chartPair = pairs.find(x => (x.pairAddress || "").toLowerCase() === (p.pool || "").toLowerCase());
    const oldest = pairs.filter(x => x.pairCreatedAt).sort((a, b) => a.pairCreatedAt - b.pairCreatedAt)[0];
    const created = chartPair?.pairCreatedAt || oldest?.pairCreatedAt || null;
    ageCache.set(p.contract.toLowerCase(), created);
  }
  // GT fallback for age when DexScreener has no pairCreatedAt
  await Promise.all(Object.values(positions).map(async (p) => {
    if (p.isDecoy || p.isStable || !p.contract) return;
    if (p.pairCreatedAt == null) p.pairCreatedAt = ageCache.get(p.contract.toLowerCase()) ?? null;
    if (p.pairCreatedAt == null && p.pool) {
      const r = await fetchJson(`https://api.geckoterminal.com/api/v2/networks/${p.gtNetwork}/pools/${p.pool}`, { headers: { Accept: "application/json;version=20230302" } });
      const created = r.data?.data?.attributes?.pool_created_at;
      if (created) { p.pairCreatedAt = Date.parse(created); ageCache.set(p.contract.toLowerCase(), p.pairCreatedAt); }
    }
  }));

  // 7) aggregates per position — EVERY number from the actual lots
  const finalize = (p) => {
    delete p._logOrders;
    p.lots.sort((a, b) => new Date(a.time || 0) - new Date(b.time || 0));
    const buys = p.lots.filter(l => l.side === "buy");
    const sells = p.lots.filter(l => l.side === "sell");
    // qty-weighted average cost from lots that carry BOTH qty and usd
    let bq = 0, bu = 0;
    for (const l of buys) if (l.qty != null && l.usd != null) { bq += l.qty; bu += l.usd; }
    p.qtyBought = bq;
    p.moneyIn = buys.reduce((s, l) => s + (l.usd || 0), 0);
    p.qtySold = sells.reduce((s, l) => s + (l.qty || 0), 0);
    p.moneyOut = sells.reduce((s, l) => s + (l.usd || 0), 0);
    p.avgCost = bq > 0 ? bu / bq : null;
    p.costBasisKnown = p.avgCost != null;
    // realized: proceeds minus avg cost of what was sold (only the tracked part)
    const soldTracked = Math.min(p.qtySold, p.qtyBought);
    p.realizedPnl = (p.avgCost != null && p.qtySold > 0) ? (p.moneyOut - p.avgCost * soldTracked) : null;
    p.soldBeyondTracked = Math.max(0, p.qtySold - p.qtyBought); // sold more than we saw bought
    // basis coverage of the CURRENT bag
    const coveredQty = Math.max(0, p.qtyBought - p.qtySold);
    p.trackedQty = Math.min(p.currentQty || 0, coveredQty);
    p.basisCoverage = (p.currentQty > 0) ? Math.min(1, coveredQty / p.currentQty) : null;
    if (p.basisCoverage != null && p.basisCoverage > 0.98) p.basisCoverage = 1;
    p.untrackedQty = Math.max(0, (p.currentQty || 0) - coveredQty);
    p.unrealizedPnl = (p.avgCost != null && p.priceUsd != null && p.trackedQty > 0) ? (p.priceUsd - p.avgCost) * p.trackedQty : null;
    p.costBasisUsd = p.avgCost != null ? p.avgCost * p.trackedQty : null;
    // money still at risk vs banked
    p.stillAtRisk = Math.max(0, p.moneyIn - p.moneyOut);
    p.banked = Math.max(0, p.moneyOut - p.moneyIn);
    if (p.marketValue == null && p.priceUsd != null && p.currentQty > 0) p.marketValue = p.priceUsd * p.currentQty;
    // token age → default candle timeframe (rule: <30d 1h · 30-60d 4h · >60d 1d)
    p.ageDays = p.pairCreatedAt ? (Date.now() - p.pairCreatedAt) / 86400000 : null;
    p.defaultTf = tfForAgeDays(p.ageDays);
    // cross-venue hint: Coinbase history under the same ticker
    const cb = coinbaseByTicker[(p.ticker || "").toUpperCase()];
    if (cb && (cb.buys || cb.sells)) p.coinbaseHistory = cb;
    return p;
  };
  for (const p of Object.values(positions)) finalize(p);

  // ---------- CEX POSITIONS (VENUES-ROADMAP Phase 3, 2026-07-24) ----------
  // Every product in module/cex-products.json becomes a TRADEABLE position, held or
  // not (a buy needs a card/dropdown row to route from). qty + valuation come from
  // Coinbase's own spot positions; price falls back to a live adapter quote for
  // unheld products. venue:"coinbase" is what routes trade-idea to cex.mjs, and
  // gtNetwork:"coinbase" + pool=productId is what routes charts to Coinbase candles.
  // Realized/closed P&L for CEX fills is NOT wired yet (honest limit, roadmap Phase 2
  // budget item); basis heuristics may show unknown.
  try {
    const cexWl = readJson(join(MODULE, "cex-products.json")).products || {};
    if (Object.keys(cexWl).length) {
      const cbAdapter = await import("../module/venues/coinbase.mjs");
      for (const productId of Object.keys(cexWl)) {
        const sym = productId.split("-")[0];
        const held = (coinbase?.ok ? coinbase.assets : []).find(a => a.currency === sym && !a.cash);
        const qty = held?.qty || 0;
        let priceUsd = qty > 0 && held?.usd ? held.usd / qty : null;
        if (priceUsd == null) { try { priceUsd = (await cbAdapter.quote(productId)).price || null; } catch { /* card ships priceless, trade-idea will refuse sizes it can't compute */ } }
        positions["coinbase::" + productId] = finalize({
          key: "coinbase::" + productId, venue: "coinbase", productId,
          token: sym, ticker: sym, name: `${sym} (Coinbase)`, chain: "coinbase", wallet: "coinbase",
          contract: null, pool: productId, gtNetwork: "coinbase", defaultTf: "1h",
          registryStatus: "AUTHORIZED", registryOf: sym, isCex: true,
          currentQty: qty, priceUsd, currentPrice: priceUsd,
          marketValue: held?.usd ?? (priceUsd != null ? qty * priceUsd : 0),
          lots: [], openOrders: [], cancelledOrders: [], pairCreatedAt: null, ageDays: null,
          balanceSrc: "coinbase-spot-positions",
        });
      }
    }
  } catch (e) { console.error("cex-positions build failed (non-fatal):", String(e.message).slice(0, 120)); }

  // closed / unaccounted bags (no current balance in any scanned wallet)
  const closedList = Object.values(closed).map(c => {
    const p = { ...c, currentQty: 0, priceUsd: null, marketValue: 0, openOrders: [], cancelledOrders: [] };
    finalize(p);
    p.unaccountedQty = Math.max(0, p.qtyBought - p.qtySold); // tokens that left without a tracked sell
    return {
      wallet: p.wallet, chain: p.chain, token: p.token, contract: p.contract,
      nBuys: p.lots.filter(l => l.side === "buy").length, nSells: p.lots.filter(l => l.side === "sell").length,
      qtyBought: p.qtyBought, qtySold: p.qtySold, moneyIn: p.moneyIn, moneyOut: p.moneyOut,
      avgCost: p.avgCost, realizedPnl: p.realizedPnl, unaccountedQty: p.unaccountedQty,
      lastActivity: p.lots.length ? p.lots[p.lots.length - 1].time : null,
      lots: p.lots,
    };
  }).sort((a, b) => (Math.abs(b.moneyOut - b.moneyIn)) - (Math.abs(a.moneyOut - a.moneyIn)));

  // 8) totals
  let portfolioValue = 0, realizedTotal = 0, unrealizedTotal = 0, openCount = 0, openNotional = 0, nativeTotal = 0;
  let moneyInTotal = 0, moneyOutTotal = 0, stillAtRiskTotal = 0;
  for (const w of walletsPub) {
    const wd = walletData[w.name];
    for (const cd of Object.values(wd.chains)) if (cd.native?.usd) nativeTotal += cd.native.usd;
  }
  const posList = Object.values(positions).sort((a, b) => (b.marketValue || 0) - (a.marketValue || 0));
  for (const p of posList) {
    // isCex positions are ALREADY inside coinbase.totalUsd (added below) — adding
    // their marketValue here would double-count the headline portfolio.
    if (p.marketValue && !p.isCex) portfolioValue += p.marketValue;
    if (p.realizedPnl != null) realizedTotal += p.realizedPnl;
    if (p.unrealizedPnl != null) unrealizedTotal += p.unrealizedPnl;
    moneyInTotal += p.moneyIn || 0; moneyOutTotal += p.moneyOut || 0;
    stillAtRiskTotal += p.stillAtRisk || 0;
    for (const o of p.openOrders) { openCount++; openNotional += o.usd || 0; }
  }
  for (const c of closedList) {
    if (c.realizedPnl != null) realizedTotal += c.realizedPnl;
    moneyInTotal += c.moneyIn || 0; moneyOutTotal += c.moneyOut || 0;
  }
  portfolioValue += nativeTotal;
  // Coinbase exchange balances join the headline total ONLY when the live fetch
  // succeeded — a failed fetch is reported as an explicit error, never a silent $0.
  const coinbaseTotal = coinbase?.ok ? coinbase.totalUsd : null;
  if (coinbaseTotal != null) portfolioValue += coinbaseTotal;

  // per-wallet summary — uses step-6 enriched prices so tokens the raw scan
  // couldn't price (Blockscout exchange_rate null → DexScreener fallback) still
  // count in the wallet card, matching the positions grid and the headline total.
  const enrichedPriceByContract = {};
  for (const p of Object.values(positions)) {
    if (!p.isDecoy && p.contract && p.priceUsd != null) enrichedPriceByContract[p.contract.toLowerCase()] = p.priceUsd;
  }
  const walletSummary = walletsPub.map(w => {
    const wd = walletData[w.name];
    let val = 0, errs = [...wd.errors];
    const scanSources = {};
    for (const [chain, cd] of Object.entries(wd.chains)) {
      for (const b of (cd.tokens || [])) {
        if (b.usd) { val += b.usd; continue; }
        const ep = enrichedPriceByContract[(b.contract || "").toLowerCase()];
        if (ep != null && b.qty) val += b.qty * ep;
      }
      if (cd.native?.usd) val += cd.native.usd;
      if (cd.ok === false) errs.push(`${chain} scan: ${String(cd.err || "error").slice(0, 200)}`);
      else if (cd.source) scanSources[chain] = cd.source;   // which LIVE source served this scan (failover-aware)
    }
    if (wd.orders && wd.orders.ok === false && !w.watchOnly) errs.push(`1inch orders: HTTP ${wd.orders.status}`);
    const liveOrders = (wd.orders.orders || []).filter(o => !(o.orderInvalidReason && /filled|cancel/i.test(o.orderInvalidReason))).length;
    return { name: w.name, address: w.address, note: w.note, watchOnly: !!w.watchOnly, value: val, openOrders: liveOrders, chains: w.chains, errors: errs, scanSources };
  });

  return {
    updated: new Date().toISOString(),
    generatedBy: "dashboard datasource v4 (read-only · RPC-first balances · 15s fast / 120s orders / 15min chain-history)",
    // per-section honesty stamps: the UI shows "Xs ago" PER SECTION so the page
    // can never look fresh when it is not. balances+prices are the same fast lane
    // (fetched together) — balancesAt is stamped with its live source for the header.
    freshness: {
      balancesAt: fastCache.at ? new Date(fastCache.at).toISOString() : null, // on-chain balances (RPC-first, 15s lane)
      balancesSource: "RPC",
      pricesAt: fastCache.at ? new Date(fastCache.at).toISOString() : null,    // current prices (DexScreener, same 15s lane)
      ordersAt: ordersCache.at ? new Date(ordersCache.at).toISOString() : null, // 1inch book (120s lane — see FIXES-LOG rate note)
      scanAt: enrichCache.at ? new Date(enrichCache.at).toISOString() : null,   // heavy chain-history swap-scan (15min lane)
    },
    dedupedDust,
    totals: { portfolioValue, realizedTotal, unrealizedTotal, moneyInTotal, moneyOutTotal, stillAtRiskTotal, openCount, openNotional, nativeTotal, coinbaseTotal },
    wallets: walletSummary,
    coinbase,
    positions: posList,
    closedPositions: closedList,
    natives: walletsPub.map(w => ({ wallet: w.name, chains: Object.fromEntries(Object.entries(walletData[w.name].chains).map(([c, cd]) => [c, cd.native])) })),
    registryTokens: Object.keys(registry.tokens || {}),
    dataSources: {
      robinhood: "RPC-FIRST: batched balanceOf over rpc.mainnet.chain.robinhood.com (PRIMARY) → Alchemy RPC failover. Blockscout is DISCOVERY-ONLY (hourly, disk-cached), never in the balance/value path.",
      base: "Alchemy base-mainnet JSON-RPC balances (PRIMARY, not Blockscout) → raw RPC batched balanceOf failover",
      solana: "LIVE failover: Alchemy solana-mainnet → public RPC (watch-only)",
      orders: `1inch orderbook v4.0 chains ${ONEINCH_CHAINS.join("+")} (retry w/ backoff)`,
      basis: "canonical ledger + orders-log freshness net + Blockscout counter-legs + chain swap-scan (native-ETH/routed) + wallet-consolidation carry (own→own transfers) + Coinbase-history join (all labeled)",
      coinbase: "Coinbase Advanced Trade accounts (read-only JWT, 120s lane) + public spot prices",
      prices: "DexScreener / GeckoTerminal / CoinGecko (natives) / GT candles (historical ETH). Blockscout exchange_rate DROPPED from the price path 2026-07-22.",
    },
    pinnedHoldings: Object.entries(PINNED_HOLDINGS).map(([c, p]) => ({ contract: c, symbol: p.symbol, chain: p.chain })),
    keysPresent: { oneinch: !!ONEINCH, alchemy: !!ALCHEMY },
  };
}
