// TRADER BEE EXECUTOR — the only code in the Hive that can sign.
//
//   node exec.mjs <command>   (JSON payload on stdin, ONE JSON object on the last stdout line)
//
//   wallet-new   create the Bee's own key file (refuses to overwrite)      -> {address}
//   address      -> {address}
//   balances     {chain, tokens:[contract]}                                -> {address, native, tokens:{addr:{amount,decimals,symbol}}}
//   quote        {chain, src, dst, amount}      (human units, read-only)    -> {winner, bestOut, quotes}
//   buy          {intent_id, chain, token, usd, slippagePct, allowedSpenders, approvalMode, minGasNative,
//                 receiptTimeoutS, retryOnce, maxImpactPct?, midPriceUsd?}  -> {sent, txHash, venue, tokensReceived, stableSpent}
//   sell         {intent_id, chain, token, pct|qty, slippagePct, allowedSpenders, dryRun, ...}
//   limit-sell   {intent_id, chain, token, qty, limitPriceUsd, expiryDays}  -> {orderHash}
//   receipt      {chain, txHash}                                           -> {status: 1|0|null}
//
// Safety, in the order it is enforced (adapted from the terminal's swap.mjs / arm.mjs):
//   * Spends ONLY the chain's dollar-true stable (USDC on Base, USDG on Robinhood) on buys.
//   * The spender/router returned by an aggregator must be in allowedSpenders (pinned routers).
//   * Gas floor: refuses if native balance < minGasNative.
//   * Approvals are EXACT-amount by default (approvalMode "exact"), never to an unpinned address.
//   * Winner quote is re-checked against the pool mid (maxImpactPct) right before signing.
//   * estimateGas before send: a doomed tx is refused unsigned (sent:false) — no gas burned.
//   * Every broadcast is journaled before waiting; one fresh-quote retry on revert (FIXES-LOG AI).
//   * Truth = receipt status + wallet balance delta, never the quote.
import { Contract, formatEther } from "ethers";
import { MakerTraits, Address, Sdk, FetchProviderConnector, getLimitOrderContract } from "@1inch/limit-order-sdk";
import { chain, provider, loadWallet, createWallet, journal, secret } from "./lib/env.mjs";
import { race, buildTx, spenderAllowed, spender1inch } from "./lib/venues.mjs";
import { toRaw, fromRaw, num } from "./lib/units.mjs";

const ERC20 = [
  "function balanceOf(address) view returns (uint256)",
  "function allowance(address,address) view returns (uint256)",
  "function approve(address,uint256) returns (bool)",
  "function decimals() view returns (uint8)",
  "function symbol() view returns (string)",
];

// Set the moment a swap/sell tx is broadcast. If ANYTHING throws after that, the result is
// reported as sent+unknown (reconcile against the chain) — never "not sent", which would invite a re-buy.
let LAST_SENT = null;

const out = obj => { process.stdout.write(JSON.stringify(obj, (k, v) => (typeof v === "bigint" ? v.toString() : v)) + "\n"); };

async function readStdin() {
  let s = "";
  for await (const chunk of process.stdin) s += chunk;
  return s.trim() ? JSON.parse(s) : {};
}

const decCache = {};
async function tokenMeta(chainName, addr) {
  const key = chainName + ":" + addr.toLowerCase();
  if (!decCache[key]) {
    const c = chain(chainName);
    if (addr.toLowerCase() === c.stable.contract.toLowerCase()) decCache[key] = { decimals: c.stable.decimals, symbol: c.stable.symbol };
    else {
      const t = new Contract(addr, ERC20, provider(chainName));
      const [d, s] = await Promise.all([t.decimals(), t.symbol().catch(() => "?")]);
      decCache[key] = { decimals: Number(d), symbol: s };
    }
  }
  return decCache[key];
}

// ------------------------------------------------------------------ read-only
async function cmdAddress() { return { ok: true, address: loadWallet().address }; }

async function cmdBalances(p) {
  const w = loadWallet();
  const prov = provider(p.chain);
  const native = await prov.getBalance(w.address);
  const tokens = {};
  for (const t of p.tokens || []) {
    const meta = await tokenMeta(p.chain, t);
    const bal = await new Contract(t, ERC20, prov).balanceOf(w.address);
    tokens[t.toLowerCase()] = { amount: num(bal, meta.decimals), raw: bal.toString(), decimals: meta.decimals, symbol: meta.symbol };
  }
  return { ok: true, chain: p.chain, address: w.address, native: Number(formatEther(native)), tokens };
}

async function cmdQuote(p) {
  const [sm, dm] = await Promise.all([tokenMeta(p.chain, p.src), tokenMeta(p.chain, p.dst)]);
  const amountRaw = toRaw(p.amount, sm.decimals);
  if (amountRaw <= 0n) return { ok: false, error: "zero amount" };
  const qs = await race(p.chain, p.src, p.dst, amountRaw.toString());
  const live = qs.filter(q => q.ok);
  return {
    ok: live.length > 0, error: live.length ? null : "no venue produced a quote",
    winner: live[0]?.venue || null, bestOut: live[0] ? num(live[0].raw, dm.decimals) : null, dstDecimals: dm.decimals,
    quotes: qs.map(q => ({ venue: q.venue, ok: q.ok, out: q.ok ? num(q.raw, dm.decimals) : null, error: q.error || null, ms: q.ms })),
  };
}

const TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef";
async function cmdReceipt(p) {
  const r = await provider(p.chain).getTransactionReceipt(p.txHash);
  const res = { ok: true, status: r ? Number(r.status) : null, blockNumber: r?.blockNumber ?? null };
  if (r && r.status === 1 && p.token) { // reconcile the received amount from the receipt's own Transfer logs
    let me = null;
    try { me = loadWallet().address.toLowerCase(); } catch { /* no key: amount stays unknown */ }
    if (me) {
      let raw = 0n;
      for (const lg of r.logs) {
        if (lg.address.toLowerCase() === p.token.toLowerCase() && lg.topics[0] === TRANSFER_TOPIC && lg.topics.length === 3 &&
            ("0x" + lg.topics[2].slice(26)).toLowerCase() === me) raw += BigInt(lg.data);
      }
      const meta = await tokenMeta(p.chain, p.token);
      res.tokensReceived = num(raw, meta.decimals);
    }
  }
  return res;
}

// ------------------------------------------------------------------ swap core
async function ensureAllowance({ chainName, signer, tokenAddr, spender, amountRaw, mode, intentId }) {
  const t = new Contract(tokenAddr, ERC20, signer);
  const have = await t.allowance(signer.address, spender);
  if (have >= amountRaw) return null;
  const amt = mode === "exact" ? amountRaw : amountRaw * 20n; // "capped": 20 trades' worth, never unlimited
  const tx = await t.approve(spender, amt);
  journal({ intent_id: intentId, kind: "approve", stage: "sent", chain: chainName, txHash: tx.hash, spender });
  const rc = await tx.wait(1, 120_000);
  if (!rc || rc.status !== 1) throw new Error(`approval tx reverted: ${tx.hash}`);
  return tx.hash;
}

/**
 * One swap attempt path shared by buy and sell: race -> pinned spender -> approve -> build -> estimate -> send -> receipt.
 * Returns {sent, ok, txHash, venue, error, stage}.
 */
async function swapOnce(p, { src, dst, amountRaw, dstDecimals, sanity }) {
  const w = loadWallet().connect(provider(p.chain));
  const qs = await race(p.chain, src, dst, amountRaw.toString());
  const live = qs.filter(q => q.ok);
  if (!live.length) return { sent: false, ok: false, stage: "quote", error: "no venue produced a quote: " + qs.map(q => `${q.venue}: ${q.error}`).join(" | ") };
  const errors = [];
  for (const q of live) { // winner first; fall back to the other venue only if the winner can't be built safely
    const outHuman = num(q.raw, dstDecimals);
    const bad = sanity ? sanity(outHuman) : null;
    if (bad) { errors.push(`${q.venue}: ${bad}`); continue; }
    let spender;
    try { spender = q.venue === "1inch" ? await spender1inch(p.chain) : q.routerAddress; }
    catch (e) { errors.push(`${q.venue}: spender lookup failed: ${e.message}`); continue; }
    if (!spenderAllowed(spender, p.allowedSpenders)) { errors.push(`${q.venue}: spender ${spender} is NOT in allowedSpenders — refused`); continue; }
    let approveTx = null;
    try { approveTx = await ensureAllowance({ chainName: p.chain, signer: w, tokenAddr: src, spender, amountRaw, mode: p.approvalMode || "exact", intentId: p.intent_id }); }
    catch (e) { return { sent: false, ok: false, stage: "approve", error: `approval failed: ${e.message}` }; }
    let tx;
    try { tx = await buildTx(p.chain, q, { src, dst, amountRaw: amountRaw.toString(), from: w.address, slippagePct: p.slippagePct }); }
    catch (e) { errors.push(`${q.venue}: build failed: ${e.message}`); continue; }
    if (tx.to.toLowerCase() !== spender.toLowerCase() || !spenderAllowed(tx.to, p.allowedSpenders)) { errors.push(`${q.venue}: tx target ${tx.to} != pinned spender — refused`); continue; }
    let gas;
    try { gas = await w.estimateGas({ to: tx.to, data: tx.data, value: tx.value }); }
    catch (e) { errors.push(`${q.venue}: simulation reverted (${String(e.shortMessage || e.message).slice(0, 140)}) — not sent`); continue; }
    const sent = await w.sendTransaction({ to: tx.to, data: tx.data, value: tx.value, gasLimit: (gas * 125n) / 100n });
    LAST_SENT = sent.hash;
    journal({ intent_id: p.intent_id, kind: "swap", stage: "sent", chain: p.chain, txHash: sent.hash, venue: q.venue });
    let rc = null;
    try { rc = await sent.wait(1, (p.receiptTimeoutS || 180) * 1000); }
    catch (e) { rc = e.receipt || null; if (!rc) return { sent: true, ok: false, stage: "receipt", txHash: sent.hash, venue: q.venue, approveTx, error: `no receipt yet: ${e.shortMessage || e.message}` }; }
    if (rc.status === 1) return { sent: true, ok: true, txHash: sent.hash, venue: q.venue, approveTx, quotes: qs.map(x => ({ venue: x.venue, ok: x.ok, out: x.ok ? num(x.raw, dstDecimals) : null })) };
    return { sent: true, ok: false, stage: "revert", txHash: sent.hash, venue: q.venue, approveTx, error: `TX REVERTED ON-CHAIN (no tokens moved, gas only): ${sent.hash}` };
  }
  return { sent: false, ok: false, stage: "route", error: errors.join(" | ") };
}

async function preflight(p, srcAddr, needRaw) {
  const w = loadWallet();
  const prov = provider(p.chain);
  const native = Number(formatEther(await prov.getBalance(w.address)));
  if (native < (p.minGasNative || 0)) return `insufficient gas: ${native} ETH < ${p.minGasNative}`;
  const bal = await new Contract(srcAddr, ERC20, prov).balanceOf(w.address);
  if (bal < needRaw) return `insufficient balance: have ${bal}, need ${needRaw} (raw units)`;
  return null;
}

async function cmdBuy(p) {
  const c = chain(p.chain);
  const stable = c.stable.contract;
  const tm = await tokenMeta(p.chain, p.token);
  const amountRaw = toRaw(Number(p.usd).toFixed(c.stable.decimals), c.stable.decimals);
  const pre = await preflight(p, stable, amountRaw);
  if (pre) return { ok: false, sent: false, stage: "preflight", error: pre };
  const w = loadWallet();
  const prov = provider(p.chain);
  const tok = new Contract(p.token, ERC20, prov), st = new Contract(stable, ERC20, prov);
  const [tb0, sb0] = await Promise.all([tok.balanceOf(w.address), st.balanceOf(w.address)]);
  const sanity = out => {
    if (!(p.midPriceUsd > 0) || !(p.maxImpactPct > 0)) return null;
    const impact = ((Number(p.usd) / out) / p.midPriceUsd - 1) * 100;
    return impact > p.maxImpactPct ? `impact ${impact.toFixed(2)}% vs mid > ${p.maxImpactPct}% at signing time` : null;
  };
  const attempts = [];
  let r = await swapOnce(p, { src: stable, dst: p.token, amountRaw, dstDecimals: tm.decimals, sanity });
  attempts.push(r);
  if (!r.ok && r.stage === "revert" && p.retryOnce) {
    r = await swapOnce(p, { src: stable, dst: p.token, amountRaw, dstDecimals: tm.decimals, sanity }); // fresh quotes, same size, same cap
    attempts.push(r);
  }
  const sent = attempts.some(a => a.sent);
  if (!r.ok) return { ok: false, sent, stage: r.stage, error: r.error, txHash: r.txHash || null, attempts };
  const [tb1, sb1] = await Promise.all([tok.balanceOf(w.address), st.balanceOf(w.address)]);
  return {
    ok: true, sent: true, txHash: r.txHash, venue: r.venue, approveTx: r.approveTx || null, attempts: attempts.length,
    tokensReceived: num(tb1 - tb0, tm.decimals), stableSpent: num(sb0 - sb1, c.stable.decimals), tokenSymbol: tm.symbol, quotes: r.quotes,
  };
}

async function cmdSell(p) {
  const c = chain(p.chain);
  const stable = c.stable.contract;
  const tm = await tokenMeta(p.chain, p.token);
  const w = loadWallet();
  const prov = provider(p.chain);
  const tok = new Contract(p.token, ERC20, prov), st = new Contract(stable, ERC20, prov);
  const bal = await tok.balanceOf(w.address);
  let amountRaw = p.qty != null ? toRaw(String(p.qty), tm.decimals) : (bal * BigInt(Math.round(Number(p.pct) * 100))) / 10000n; // floor, never overshoot
  if (amountRaw > bal) amountRaw = bal;
  if (amountRaw <= 0n) return { ok: false, sent: false, error: "nothing to sell (zero balance)" };
  if (p.dryRun) {
    const q = await cmdQuote({ chain: p.chain, src: p.token, dst: stable, amount: fromRaw(amountRaw, tm.decimals) });
    return { ok: true, sent: false, dryRun: true, preview: `SELL ${fromRaw(amountRaw, tm.decimals)} ${tm.symbol} → ≈${q.bestOut} ${c.stable.symbol} via ${q.winner}`, quote: q };
  }
  const pre = await preflight(p, p.token, amountRaw);
  if (pre) return { ok: false, sent: false, stage: "preflight", error: pre };
  const sb0 = await st.balanceOf(w.address);
  let r = await swapOnce(p, { src: p.token, dst: stable, amountRaw, dstDecimals: c.stable.decimals });
  const attempts = [r];
  if (!r.ok && r.stage === "revert" && p.retryOnce) { r = await swapOnce(p, { src: p.token, dst: stable, amountRaw, dstDecimals: c.stable.decimals }); attempts.push(r); }
  if (!r.ok) return { ok: false, sent: attempts.some(a => a.sent), stage: r.stage, error: r.error, txHash: r.txHash || null };
  const [tb1, sb1] = await Promise.all([tok.balanceOf(w.address), st.balanceOf(w.address)]);
  return { ok: true, sent: true, txHash: r.txHash, venue: r.venue, tokensSold: num(bal - tb1, tm.decimals), stableReceived: num(sb1 - sb0, c.stable.decimals) };
}

// ------------------------------------------------------------------ resting take-profit (adapted from module/arm.mjs)
async function cmdLimitSell(p) {
  const c = chain(p.chain);
  const key = secret("ONEINCH_API_KEY");
  if (!key) return { ok: false, sent: false, error: "no ONEINCH_API_KEY for the 1inch orderbook" };
  const tm = await tokenMeta(p.chain, p.token);
  const w = loadWallet().connect(provider(p.chain));
  const tok = new Contract(p.token, ERC20, w);
  const bal = await tok.balanceOf(w.address);
  let making = toRaw(String(p.qty), tm.decimals);
  if (making > bal) making = bal;
  if (making <= 0n) return { ok: false, sent: false, error: "nothing to sell" };
  const takingHuman = Number(fromRaw(making, tm.decimals)) * Number(p.limitPriceUsd);
  const taking = toRaw(takingHuman.toFixed(c.stable.decimals), c.stable.decimals);
  const expiration = BigInt(Math.floor(Date.now() / 1000) + Math.round(Number(p.expiryDays || 60) * 86400));
  // Orders MUST be built via sdk.createOrder (fee extension) and MUST allow partial + multiple fills (arm.mjs, 2026-07-20).
  const sdk = new Sdk({ authKey: key, networkId: c.chainId, httpConnector: new FetchProviderConnector() });
  const order = await sdk.createOrder({ makerAsset: new Address(p.token), takerAsset: new Address(c.stable.contract), makingAmount: making,
    takingAmount: taking, maker: new Address(w.address) }, MakerTraits.default().withExpiration(expiration).allowPartialFills().allowMultipleFills());
  const typed = order.getTypedData(c.chainId);
  const spender = typed.domain.verifyingContract;
  // The protocol address must match 1inch's own SDK constant for this chain AND the beekeeper's pinned list.
  if (spender.toLowerCase() !== getLimitOrderContract(c.chainId).toLowerCase() || !spenderAllowed(spender, p.allowedSpenders))
    return { ok: false, sent: false, error: `limit-order protocol ${spender} is not the pinned 1inch deployment for chain ${c.chainId} — refused` };
  const approveTx = await ensureAllowance({ chainName: p.chain, signer: w, tokenAddr: p.token, spender, amountRaw: making, mode: "exact", intentId: p.intent_id });
  const signature = await w.signTypedData(typed.domain, { Order: typed.types.Order }, typed.message);
  await sdk.submitOrder(order, signature);
  const orderHash = order.getOrderHash(c.chainId);
  journal({ intent_id: p.intent_id, kind: "limit-sell", stage: "submitted", chain: p.chain, orderHash });
  return { ok: true, sent: true, orderHash, approveTx, qty: fromRaw(making, tm.decimals), limitPriceUsd: p.limitPriceUsd,
           expiresAt: new Date(Number(expiration) * 1000).toISOString() };
}

// ------------------------------------------------------------------ dispatch
const COMMANDS = {
  "wallet-new": async () => ({ ok: true, address: createWallet(), created: true }),
  address: cmdAddress, balances: cmdBalances, quote: cmdQuote, buy: cmdBuy, sell: cmdSell, "limit-sell": cmdLimitSell, receipt: cmdReceipt,
};

const cmd = process.argv[2];
try {
  if (!COMMANDS[cmd]) throw Object.assign(new Error(`unknown command '${cmd}' (${Object.keys(COMMANDS).join(", ")})`), { fatal: true });
  out(await COMMANDS[cmd](await readStdin()));
} catch (e) {
  const error = String(e?.shortMessage || e?.message || e).slice(0, 400);
  if (LAST_SENT) out({ ok: false, sent: true, stage: "unknown", txHash: LAST_SENT, error: `error AFTER broadcast (reconcile against the chain): ${error}` });
  else out({ ok: false, sent: false, fatal: !!e.fatal || e.code === "NO_KEY", error });
  process.exitCode = 1;
}
