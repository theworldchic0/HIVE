// Venue race: 1inch Classic Swap v6 vs KyberSwap Aggregator — lifted from the terminal's
// cockpit/route-scan.mjs (quotes) and extended with the two BUILD calls swap.mjs made.
// Quotes are not fills (terminal KNOWN-INCOMPLETE §4): the winner is re-checked against the
// pool mid before anything is signed, and the fill is measured by balance delta afterwards.
import { secret, chain } from "./env.mjs";

const KH = { "x-client-id": "nuk3r2-trader-bee", Accept: "application/json" };
const ONEINCH_BASES = ["https://api.1inch.dev", "https://api.1inch.com"];

async function getJson(url, opts = {}) {
  const r = await fetch(url, { ...opts, signal: AbortSignal.timeout(opts.timeoutMs || 15_000) });
  const text = await r.text();
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${text.slice(0, 160)}`);
  try { return JSON.parse(text); } catch { throw new Error(`invalid JSON: ${text.slice(0, 120)}`); }
}

async function oneinch(path) {
  const key = secret("ONEINCH_API_KEY");
  if (!key) throw new Error("no ONEINCH_API_KEY in .env / module/.env");
  let last;
  for (const base of ONEINCH_BASES) {
    try { return await getJson(base + path, { headers: { Authorization: `Bearer ${key}`, Accept: "application/json" } }); }
    catch (e) { last = e; if (!/HTTP (5\d\d|429|404)|fetch failed|timeout/i.test(e.message)) break; }
  }
  throw last;
}

export async function quote1inch(chainName, src, dst, amountRaw) {
  const t0 = Date.now();
  try {
    const c = chain(chainName);
    const j = await oneinch(`/swap/v6.0/${c.chainId}/quote?src=${src}&dst=${dst}&amount=${amountRaw}`);
    const raw = j.dstAmount ?? j.toAmount;
    if (raw == null) throw new Error("no dstAmount in response");
    return { venue: "1inch", ok: true, raw: String(raw), ms: Date.now() - t0 };
  } catch (e) { return { venue: "1inch", ok: false, error: String(e?.message || e).slice(0, 200), ms: Date.now() - t0 }; }
}

export async function quoteKyber(chainName, src, dst, amountRaw) {
  const t0 = Date.now();
  try {
    const c = chain(chainName);
    const j = await getJson(`https://aggregator-api.kyberswap.com/${c.kyberSlug}/api/v1/routes?tokenIn=${src}&tokenOut=${dst}&amountIn=${amountRaw}`, { headers: KH });
    if (j.code !== 0 || !j.data?.routeSummary) throw new Error(`code ${j.code}: ${String(j.message).slice(0, 120)}`);
    return { venue: "kyber", ok: true, raw: String(j.data.routeSummary.amountOut), routeSummary: j.data.routeSummary,
             routerAddress: j.data.routerAddress, ms: Date.now() - t0 };
  } catch (e) { return { venue: "kyber", ok: false, error: String(e?.message || e).slice(0, 200), ms: Date.now() - t0 }; }
}

/** Race both venues in parallel. Returns quotes sorted best-first (live ones only first). */
export async function race(chainName, src, dst, amountRaw) {
  const qs = await Promise.all([quote1inch(chainName, src, dst, amountRaw), quoteKyber(chainName, src, dst, amountRaw)]);
  return pickOrder(qs);
}

export function pickOrder(qs) {
  return [...qs].sort((a, b) => {
    if (a.ok !== b.ok) return a.ok ? -1 : 1;
    if (!a.ok) return 0;
    const x = BigInt(a.raw), y = BigInt(b.raw);
    return x > y ? -1 : x < y ? 1 : 0;
  });
}

export async function spender1inch(chainName) {
  const c = chain(chainName);
  const j = await oneinch(`/swap/v6.0/${c.chainId}/approve/spender`);
  if (!j.address) throw new Error("1inch returned no spender");
  return j.address;
}

/** Build the swap transaction for the chosen venue. Returns {to, data, value, spender, expectedOut}. */
export async function buildTx(chainName, q, { src, dst, amountRaw, from, slippagePct }) {
  const c = chain(chainName);
  if (q.venue === "1inch") {
    const j = await oneinch(`/swap/v6.0/${c.chainId}/swap?src=${src}&dst=${dst}&amount=${amountRaw}&from=${from}&origin=${from}` +
      `&slippage=${slippagePct}&disableEstimate=true`);
    if (!j.tx?.to || !j.tx?.data) throw new Error("1inch swap: no tx in response");
    return { to: j.tx.to, data: j.tx.data, value: BigInt(j.tx.value || 0), spender: j.tx.to, expectedOut: String(j.dstAmount) };
  }
  const bps = Math.round(slippagePct * 100);
  const j = await getJson(`https://aggregator-api.kyberswap.com/${c.kyberSlug}/api/v1/route/build`, {
    method: "POST", headers: { ...KH, "Content-Type": "application/json" },
    body: JSON.stringify({ routeSummary: q.routeSummary, sender: from, recipient: from, slippageTolerance: bps,
                           deadline: Math.floor(Date.now() / 1000) + 600, source: "nuk3r2-trader-bee" }),
  });
  if (j.code !== 0 || !j.data?.data) throw new Error(`kyber build code ${j.code}: ${String(j.message).slice(0, 120)}`);
  return { to: j.data.routerAddress, data: j.data.data, value: BigInt(j.data.transactionValue || 0), spender: j.data.routerAddress,
           expectedOut: String(j.data.amountOut) };
}

export function spenderAllowed(addr, allowed) {
  const a = String(addr || "").toLowerCase();
  return (allowed || []).some(x => String(x).toLowerCase() === a);
}
