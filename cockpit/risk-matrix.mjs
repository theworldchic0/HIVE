// ============================================================
// RISK MATRIX + SIZING ENGINE (server-side, read-only on markets)
// Spec: proposals/LIQUIDITY-MATRIX-BUILD-SPEC.md Part 2 (Jesse-blessed 2026-07-28).
//
// The chain, per coin with a known pool liquidity:
//   1. depth      real CoinGecko ±2% depth when CG-listed (deepest venue), else
//                 est = pool × depthEstimateRatio, ALWAYS labeled "est"
//   2. tier       pool tier (% of DefiLlama total TVL, cached daily) × depth tier
//                 → grid → L (1 green / 2 yellow / 3 red); per-contract override wins
//   3. curve cap  log-log interpolation through the blessed anchors × portfolio value
//   4. pool cap   poolImpactCapPct% × effective pool
//   5. blueprint  dryPowder × (CCM ÷ ccmDivisor) × basketShare (L^γ ÷ Σ L^γ)
//   6. suggested = min(curve, pool, blueprint), 2 significant figures for display
//
// CEX-anchoring: a CG-listed coin's real depth converts to DEX terms via
// equivalentPool = depth ÷ depthEstimateRatio; the LARGER of on-chain pool and
// equivalentPool drives curve, tier AND the impact cap (that is what makes the
// VIRTUAL worked example land at the 5% ceiling instead of 4% of a $234K pool).
//
// LAWS (spec 2d): suggest never clamp; real-vs-est depth always labeled; no silent
// fallbacks — every degraded source reports {stale/age} loudly in its own block.
// ============================================================
import { readFile, writeFile, copyFile, appendFile } from "node:fs/promises";
import { execFile } from "node:child_process";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const CFG_PATH = join(HERE, "risk-matrix.json");
const CACHE_PATH = join(HERE, "risk-matrix-cache.json");        // TVL daily cache + CG id/depth cache (data, not config)
const OVERRIDE_LOG = join(HERE, "risk-overrides.jsonl");        // overrides logged, not fought
const MD_DIR = join(HERE, "..", "..", "tools", "market-direction");
const MD_JSON = join(MD_DIR, "market-direction.json");
const ENV_PATH = join(HERE, "..", "module", ".env");

const DAY = 24 * 60 * 60 * 1000;

// ---------- tiny .env reader (COINGECKO_API_KEY optional; degrade gracefully) ----------
async function envKey(name) {
  try {
    const txt = await readFile(ENV_PATH, "utf8");
    for (const line of txt.split("\n")) {
      const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.+?)\s*$/);
      if (m && m[1] === name) return m[2];
    }
  } catch (_) {}
  return null;
}

// ---------- config load / validate / save ----------
export async function loadMatrix() {
  const cfg = JSON.parse(await readFile(CFG_PATH, "utf8"));
  const errs = validateMatrix(cfg);
  if (errs.length) throw new Error("risk-matrix.json invalid: " + errs.join("; "));
  return cfg;
}

export function validateMatrix(c) {
  const errs = [];
  const num = (v) => typeof v === "number" && Number.isFinite(v);
  if (!c || typeof c !== "object") return ["not an object"];
  const known = new Set(["comment", "poolTiersPctOfTVL", "tvlSourceNote", "depthSplitsUsd", "depthEstimateRatio",
    "grid", "exposureCurveAnchors", "curveRules", "poolImpactCapPct", "blueprint", "overrides"]);
  for (const k of Object.keys(c)) if (!known.has(k)) errs.push(`unknown key "${k}"`);
  const pt = c.poolTiersPctOfTVL || {};
  if (!num(pt.smallBelow) || pt.smallBelow <= 0) errs.push("poolTiersPctOfTVL.smallBelow must be > 0");
  if (!num(pt.largeAbove) || pt.largeAbove <= pt.smallBelow) errs.push("poolTiersPctOfTVL.largeAbove must be > smallBelow");
  const ds = c.depthSplitsUsd || {};
  if (!num(ds.thinBelow) || ds.thinBelow <= 0) errs.push("depthSplitsUsd.thinBelow must be > 0");
  if (!num(ds.deepAbove) || ds.deepAbove <= ds.thinBelow) errs.push("depthSplitsUsd.deepAbove must be > thinBelow");
  if (!num(c.depthEstimateRatio) || c.depthEstimateRatio <= 0 || c.depthEstimateRatio > 1) errs.push("depthEstimateRatio must be in (0,1]");
  for (const p of ["small", "medium", "large"]) for (const d of ["thin", "medium", "deep"]) {
    const L = c.grid?.[p]?.[d];
    if (![1, 2, 3].includes(L)) errs.push(`grid.${p}.${d} must be 1, 2 or 3`);
  }
  const a = c.exposureCurveAnchors;
  if (!Array.isArray(a) || a.length < 2) errs.push("exposureCurveAnchors needs >= 2 anchors");
  else for (let i = 0; i < a.length; i++) {
    if (!num(a[i]?.poolUsd) || a[i].poolUsd <= 0) errs.push(`anchor[${i}].poolUsd must be > 0`);
    if (!num(a[i]?.maxPctOfPortfolio) || a[i].maxPctOfPortfolio <= 0) errs.push(`anchor[${i}].maxPctOfPortfolio must be > 0`);
    if (i && a[i].poolUsd <= a[i - 1].poolUsd) errs.push(`anchor[${i}].poolUsd must ascend`);
    if (i && a[i].maxPctOfPortfolio < a[i - 1].maxPctOfPortfolio) errs.push(`anchor[${i}].maxPctOfPortfolio must not descend`);
  }
  if (!num(c.poolImpactCapPct) || c.poolImpactCapPct <= 0 || c.poolImpactCapPct > 100) errs.push("poolImpactCapPct must be in (0,100]");
  if (!num(c.blueprint?.gamma)) errs.push("blueprint.gamma must be a number");
  if (!num(c.blueprint?.ccmDivisor) || c.blueprint.ccmDivisor <= 0) errs.push("blueprint.ccmDivisor must be > 0");
  const tiers = c.overrides?.tiers;
  if (tiers && typeof tiers === "object") {
    for (const [k, v] of Object.entries(tiers)) if (![1, 2, 3].includes(v)) errs.push(`overrides.tiers["${k}"] must be 1, 2 or 3`);
  } else if (c.overrides != null && tiers != null) errs.push("overrides.tiers must be an object");
  return errs;
}

export async function saveMatrix(candidate) {
  const errs = validateMatrix(candidate);
  if (errs.length) { const e = new Error("validation failed: " + errs.join("; ")); e.code = "INVALID"; throw e; }
  const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\..*/, "");
  await copyFile(CFG_PATH, CFG_PATH + ".bak-" + stamp);
  await writeFile(CFG_PATH, JSON.stringify(candidate, null, 2) + "\n");
  return { ok: true, backup: "risk-matrix.json.bak-" + stamp };
}

// tier override from the card popover: sets overrides.tiers[contract] (or clears with L=null).
// Every change is APPENDED to risk-overrides.jsonl — overrides logged, not fought.
export async function setTierOverride({ contract, ticker, L }) {
  const ck = String(contract || "").toLowerCase();
  if (!ck) throw new Error("contract required");
  if (L != null && ![1, 2, 3].includes(L)) throw new Error("L must be 1, 2, 3 or null (auto)");
  const cfg = await loadMatrix();
  cfg.overrides = cfg.overrides || { tiers: {} };
  cfg.overrides.tiers = cfg.overrides.tiers || {};
  const prev = cfg.overrides.tiers[ck] ?? null;
  if (L == null) delete cfg.overrides.tiers[ck]; else cfg.overrides.tiers[ck] = L;
  const saved = await saveMatrix(cfg);
  await appendFile(OVERRIDE_LOG, JSON.stringify({ time: new Date().toISOString(), contract: ck, ticker: ticker || null, L: L ?? "auto", prev: prev ?? "auto" }) + "\n");
  return { ...saved, contract: ck, L: L ?? null, prev };
}

// ---------- cache file (TVL + CoinGecko id/depth) ----------
async function readCache() { try { return JSON.parse(await readFile(CACHE_PATH, "utf8")); } catch (_) { return {}; } }
async function writeCache(c) { try { await writeFile(CACHE_PATH, JSON.stringify(c, null, 1)); } catch (_) {} }

async function fetchJson(url, headers = {}, timeoutMs = 15000) {
  const ac = new AbortController();
  const t = setTimeout(() => ac.abort(), timeoutMs);
  try {
    const r = await fetch(url, { headers, signal: ac.signal });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return await r.json();
  } finally { clearTimeout(t); }
}

// total crypto TVL (DefiLlama), cached daily; fallback to last-known LOUDLY (stale flag + age)
export async function getTvl() {
  const cache = await readCache();
  const c = cache.tvl;
  if (c && Date.now() - c.at < DAY) return { usd: c.usd, asOf: new Date(c.at).toISOString(), stale: false, source: "defillama (daily cache)" };
  try {
    const chains = await fetchJson("https://api.llama.fi/v2/chains");
    const usd = chains.reduce((s, x) => s + (Number(x.tvl) || 0), 0);
    if (!(usd > 1e9)) throw new Error("implausible TVL sum " + usd);
    cache.tvl = { usd, at: Date.now() };
    await writeCache(cache);
    return { usd, asOf: new Date().toISOString(), stale: false, source: "defillama (live)" };
  } catch (e) {
    if (c) return { usd: c.usd, asOf: new Date(c.at).toISOString(), stale: true, source: "defillama LAST-KNOWN (refresh failed: " + e.message + ")" };
    return { usd: null, asOf: null, stale: true, source: "defillama UNAVAILABLE: " + e.message };
  }
}

// CCM from Jesse's market-direction tool; re-run refresh.js if older than 24h (keyless)
function parseMdDate(s) { const d = new Date(String(s || "").replace(" UTC", "Z").replace(" ", "T")); return isNaN(d) ? null : d; }
export async function getCcm() {
  let md = null;
  try { md = JSON.parse(await readFile(MD_JSON, "utf8")); } catch (_) {}
  let at = md ? parseMdDate(md.generated_utc) : null;
  if (!md || !at || Date.now() - at.getTime() > DAY) {
    try {
      await new Promise((res, rej) => execFile("node", ["refresh.js"], { cwd: MD_DIR, timeout: 90_000 }, (err) => err ? rej(err) : res()));
      md = JSON.parse(await readFile(MD_JSON, "utf8"));
      at = parseMdDate(md.generated_utc);
    } catch (e) { /* fall through to last-known, flagged stale below */ }
  }
  if (!md || !Number.isFinite(Number(md.buy_size_multiplier)))
    return { value: null, asOf: null, stale: true, source: "market-direction.json UNAVAILABLE" };
  const ageMs = at ? Date.now() - at.getTime() : null;
  return { value: Number(md.buy_size_multiplier), asOf: at ? at.toISOString() : null, stale: ageMs == null || ageMs > DAY, source: "tools/market-direction" };
}

// ---------- CoinGecko real ±2% depth (Base contracts only; robinhood chain is not a CG platform) ----------
const CG_PLATFORM = { base: "base" };
async function cgHeaders() {
  const key = await envKey("COINGECKO_API_KEY");
  return key ? { "x-cg-demo-api-key": key } : {};
}
// returns {usd, source:"coingecko"|"est", cgId?, venue?} — NEVER throws; est on any failure
export async function resolveDepth(contract, chain, poolUsd, cfg) {
  const est = () => ({ usd: (Number(poolUsd) || 0) * cfg.depthEstimateRatio, source: "est" });
  const platform = CG_PLATFORM[String(chain || "").toLowerCase()];
  const ck = String(contract || "").toLowerCase();
  if (!platform || !ck) return est();
  const cache = await readCache();
  cache.cg = cache.cg || {};
  const hit = cache.cg[ck];
  // id lookup cached 7 days (404s too — a CG listing appearing later re-resolves weekly)
  let cgId = hit?.cgId;
  if (hit == null || Date.now() - (hit.idAt || 0) > 7 * DAY) {
    try {
      const j = await fetchJson(`https://api.coingecko.com/api/v3/coins/${platform}/contract/${ck}`, await cgHeaders());
      cgId = j.id || null;
    } catch (_) { cgId = null; }
    cache.cg[ck] = { ...(hit || {}), cgId, idAt: Date.now() };
    await writeCache(cache);
  }
  if (!cgId) return est();
  // depth cached 1h per coin
  const d = cache.cg[ck];
  if (d.depthUsd != null && Date.now() - (d.depthAt || 0) < 60 * 60 * 1000)
    return { usd: d.depthUsd, source: "coingecko", cgId, venue: d.venue };
  try {
    const j = await fetchJson(`https://api.coingecko.com/api/v3/coins/${cgId}/tickers?depth=true`, await cgHeaders());
    let best = 0, venue = null;
    for (const t of (j.tickers || [])) {
      const up = Number(t.cost_to_move_up_usd), dn = Number(t.cost_to_move_down_usd);
      if (!(up > 0) || !(dn > 0)) continue;
      const both = Math.min(up, dn);          // conservative: the depth you can actually cross both ways
      if (both > best) { best = both; venue = t.market?.name || null; }
    }
    if (!(best > 0)) return est();
    cache.cg[ck] = { ...d, depthUsd: best, depthAt: Date.now(), venue };
    await writeCache(cache);
    return { usd: best, source: "coingecko", cgId, venue };
  } catch (_) {
    if (d.depthUsd != null) return { usd: d.depthUsd, source: "coingecko", cgId, venue: d.venue, staleDepth: true };
    return est();
  }
}

// ---------- the pure math ----------
export function curvePct(poolUsd, anchors) {
  const a = anchors;
  if (!(poolUsd > 0)) return a[0].maxPctOfPortfolio;
  if (poolUsd <= a[0].poolUsd) return a[0].maxPctOfPortfolio;                    // FLAT below the first anchor
  if (poolUsd >= a[a.length - 1].poolUsd) return a[a.length - 1].maxPctOfPortfolio; // capped above the last
  for (let i = 1; i < a.length; i++) {
    if (poolUsd <= a[i].poolUsd) {
      const t = (Math.log(poolUsd) - Math.log(a[i - 1].poolUsd)) / (Math.log(a[i].poolUsd) - Math.log(a[i - 1].poolUsd));
      return Math.exp(Math.log(a[i - 1].maxPctOfPortfolio) + t * (Math.log(a[i].maxPctOfPortfolio) - Math.log(a[i - 1].maxPctOfPortfolio)));
    }
  }
  return a[a.length - 1].maxPctOfPortfolio;
}

export function round2sig(n) {
  if (!(n > 0)) return 0;
  const mag = Math.pow(10, Math.floor(Math.log10(n)) - 1);
  return Math.round(n / mag) * mag;
}

export function tierOf(effectivePoolUsd, depthUsd, cfg, tvlUsd, override) {
  if (override != null) return { L: override, poolTier: null, depthTier: null, overridden: true };
  const pt = tvlUsd
    ? (effectivePoolUsd < cfg.poolTiersPctOfTVL.smallBelow * tvlUsd ? "small"
      : effectivePoolUsd > cfg.poolTiersPctOfTVL.largeAbove * tvlUsd ? "large" : "medium")
    : "small"; // no TVL at all → most conservative pool tier, flagged upstream by tvl.stale
  const dt = depthUsd < cfg.depthSplitsUsd.thinBelow ? "thin"
    : depthUsd > cfg.depthSplitsUsd.deepAbove ? "deep" : "medium";
  return { L: cfg.grid[pt][dt], poolTier: pt, depthTier: dt, overridden: false };
}

// one coin through the whole chain. item = {contract, ticker, chain, poolUsd}
// ctx = {cfg, tvl, ccm, portfolioValueUsd, dryPowderUsd, basketL:[{key,L}], overrides}
export function computeSize(item, depth, ctx) {
  const cfg = ctx.cfg;
  const pool = Number(item.poolUsd) || 0;
  const equivalentPool = depth.source === "coingecko" ? depth.usd / cfg.depthEstimateRatio : null;
  const effectivePool = Math.max(pool, equivalentPool || 0);
  const ck = String(item.contract || "").toLowerCase();
  const override = ctx.overrides?.[ck] ?? null;
  const tier = tierOf(effectivePool, depth.usd, cfg, ctx.tvl.usd, override);
  const badge = tier.L === 1 ? "🟢" : tier.L === 2 ? "🟡" : "🔴";

  const pct = curvePct(effectivePool, cfg.exposureCurveAnchors);
  const curveCap = ctx.portfolioValueUsd != null ? (pct / 100) * ctx.portfolioValueUsd : null;
  const poolCap = (cfg.poolImpactCapPct / 100) * effectivePool;

  // blueprint term: dryPowder × (CCM ÷ divisor) × basketShare over open positions + this coin
  const gamma = cfg.blueprint.gamma;
  let blueprint = null, basketShare = null;
  if (ctx.ccm.value != null && ctx.dryPowderUsd != null) {
    const others = (ctx.basketL || []).filter(b => b.key !== ck);
    const sum = others.reduce((s, b) => s + Math.pow(b.L, gamma), 0) + Math.pow(tier.L, gamma);
    basketShare = sum > 0 ? Math.pow(tier.L, gamma) / sum : 1;
    blueprint = ctx.dryPowderUsd * (ctx.ccm.value / cfg.blueprint.ccmDivisor) * basketShare;
  }

  const caps = [
    { name: "curve", usd: curveCap },
    { name: "pool", usd: poolCap },
    { name: "blueprint", usd: blueprint },
  ].filter(c => c.usd != null && Number.isFinite(c.usd));
  const winner = caps.length ? caps.reduce((m, c) => c.usd < m.usd ? c : m) : null;

  return {
    contract: ck || null, ticker: item.ticker || null,
    poolUsd: pool, effectivePoolUsd: effectivePool, equivalentPoolUsd: equivalentPool,
    depth: { usd: depth.usd, source: depth.source, est: depth.source !== "coingecko", venue: depth.venue || null, staleDepth: !!depth.staleDepth },
    L: tier.L, badge, poolTier: tier.poolTier, depthTier: tier.depthTier, overridden: tier.overridden,
    curvePct: pct, caps: { curveUsd: curveCap, poolUsd_cap: poolCap, blueprintUsd: blueprint },
    basketShare, won: winner ? winner.name : null,
    suggestedUsd: winner ? winner.usd : null,
    suggestedDisplayUsd: winner ? round2sig(winner.usd) : null,
  };
}

// ---------- context builder + batch API ----------
// state = the dashboard's /api/state payload (positions carry liq + isStable + marketValue)
export async function riskContext(state) {
  const cfg = await loadMatrix();
  const [tvl, ccm] = await Promise.all([getTvl(), getCcm()]);
  const positions = (state?.positions || []);
  const dryPowderUsd = positions.filter(p => p.isStable).reduce((s, p) => s + (Number(p.marketValue) || 0), 0);
  const portfolioValueUsd = Number(state?.totals?.portfolioValue) ?? null;
  const overrides = {};
  for (const [k, v] of Object.entries(cfg.overrides?.tiers || {})) overrides[k.toLowerCase()] = v;
  // the basket: every open non-stable, non-decoy position worth >= $9 (the dust floor).
  // DEX positions get L from their live pool liq (est depth — cheap, labeled); CEX
  // (coinbase venue, no pool) get L=1 (exchange-listed = deep, labeled "cex est");
  // unknown-liq DEX bags get L=3 (conservative: shrinks every OTHER share, incl. the
  // coin being sized — errs small, never big).
  const basketL = [];
  for (const p of positions) {
    if (p.isStable || p.isDecoy) continue;
    if (!((Number(p.marketValue) || 0) >= 9)) continue;
    const ck = String(p.contract || p.key || "").toLowerCase();
    let L, how;
    if (String(p.chain) === "coinbase") { L = 1; how = "cex est"; }
    else if (p.liq != null) {
      const est = { usd: p.liq * cfg.depthEstimateRatio, source: "est" };
      L = (overrides[ck] != null) ? overrides[ck] : tierOf(p.liq, est.usd, cfg, tvl.usd, null).L;
      how = overrides[ck] != null ? "override" : "est";
    } else { L = 3; how = "unknown liq → conservative 3"; }
    basketL.push({ key: ck, ticker: p.ticker, L, how, valueUsd: Number(p.marketValue) || 0 });
  }
  return { cfg, tvl, ccm, portfolioValueUsd, dryPowderUsd, basketL, overrides };
}

export async function sizeItems(items, state) {
  const ctx = await riskContext(state);
  const out = [];
  for (const item of (items || []).slice(0, 200)) {
    if (!(Number(item.poolUsd) > 0)) { out.push({ contract: item.contract || null, ticker: item.ticker || null, error: "poolUsd required (> 0)" }); continue; }
    const depth = await resolveDepth(item.contract, item.chain, item.poolUsd, ctx.cfg);
    out.push(computeSize(item, depth, ctx));
  }
  return {
    context: {
      tvl: ctx.tvl, ccm: ctx.ccm,
      portfolioValueUsd: ctx.portfolioValueUsd, dryPowderUsd: ctx.dryPowderUsd,
      gamma: ctx.cfg.blueprint.gamma, ccmDivisor: ctx.cfg.blueprint.ccmDivisor,
      basket: ctx.basketL,
    },
    results: out,
  };
}
