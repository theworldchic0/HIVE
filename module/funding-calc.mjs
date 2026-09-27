// FUNDING-CALC — READ-ONLY order-distance + dynamic-funding calculator.
// Answers Jesse's question: "how close are my orders to executing, and do I need
// to load the wallet with more USDG for them all to fill — accounting for the fact
// that some SELLS lock in before a BUY does and their USDG can fund the buys."
//
// Pulls LIVE resting orders from the 1inch orderbook for every wallet in wallets.json,
// live prices from DexScreener, and live USDG balances on-chain. USD FIRST, always.
// It NEVER signs, submits, cancels, or approves anything. It only reads.
//
// Usage:  node funding-calc.mjs                 (all wallets)
//         node funding-calc.mjs --wallet wallet-2
//         node funding-calc.mjs --json          (machine-readable dump)
import { readFileSync } from "node:fs";
import { JsonRpcProvider, Contract, formatUnits } from "ethers";
import { listWallets, resolveWallet } from "./lib/wallets.mjs";

// ---------- args ----------
const arg = (n, d) => { const i = process.argv.indexOf("--" + n); return i > -1 ? process.argv[i + 1] : d; };
const ONLY_WALLET = arg("wallet", null);
const AS_JSON = process.argv.includes("--json");

// ---------- load config / registry / key (same pattern as arm.mjs & swap.mjs) ----------
const dir = new URL(".", import.meta.url);
const config = JSON.parse(readFileSync(new URL("./config.json", dir), "utf8"));
const registry = JSON.parse(readFileSync(new URL("./registry.json", dir), "utf8"));
const AUTH = readFileSync(new URL("./.env", dir), "utf8").match(/ONEINCH_API_KEY=(.+)/)?.[1]?.trim();
if (!AUTH) { console.error("REFUSED: ONEINCH_API_KEY missing from .env"); process.exit(1); }
const H = { Authorization: `Bearer ${AUTH}`, Accept: "application/json" };

const RH = { rpc: "https://rpc.mainnet.chain.robinhood.com", chainId: 4663 };
const USDG = registry.tokens.USDG;                       // the chain's dollar
const USDG_ADDR = USDG.contract.toLowerCase();

// reverse index: contract -> { name, decimals }
const byContract = {};
for (const [name, t] of Object.entries(registry.tokens)) {
  if (t?.contract) byContract[t.contract.toLowerCase()] = { name, decimals: t.decimals ?? 18, ...t };
}

// ---------- live-price cache (DexScreener highest-liquidity pair, USD) ----------
const priceCache = new Map();
async function priceUsd(contract) {
  const key = contract.toLowerCase();
  if (priceCache.has(key)) return priceCache.get(key);
  let px = null;
  try {
    const r = await fetch(`https://api.dexscreener.com/latest/dex/tokens/${contract}`);
    const p = ((await r.json()).pairs || []).sort((a, b) => (b.liquidity?.usd || 0) - (a.liquidity?.usd || 0))[0];
    px = p ? Number(p.priceUsd) : null;
  } catch { px = null; }
  priceCache.set(key, px);
  return px;
}

// ---------- pull live resting orders for one address ----------
// statuses=1,2 = VALID + TEMPORARILY-INVALID. Status 2 is the important one: a resting
// order that can't currently fill because the maker lacks balance/allowance (e.g. an
// underfunded BUY with $0 USDG). The default (statuses=1) HIDES exactly the order Jesse
// needs to see. Status 3 (filled/expired/cancelled) is excluded.
async function fetchOrders(address) {
  const url = `https://api.1inch.dev/orderbook/v4.0/${RH.chainId}/address/${address}?page=1&limit=100&statuses=1,2`;
  const res = await fetch(url, { headers: H });
  if (!res.ok) throw new Error(`orderbook HTTP ${res.status}: ${(await res.text()).slice(0, 160)}`);
  const body = await res.json();
  return Array.isArray(body) ? body : (body.orders || body.items || []);
}

// ---------- normalize a raw 1inch order into a USD-first view ----------
function normalize(raw) {
  const d = raw.data || raw;
  const makerAsset = (d.makerAsset || "").toLowerCase();
  const takerAsset = (d.takerAsset || "").toLowerCase();
  const makingAmount = BigInt(d.makingAmount);
  const takingAmount = BigInt(d.takingAmount);
  // remainingMakerAmount tracks partial fills; fall back to full making amount
  const remMaker = BigInt(raw.remainingMakerAmount ?? d.makingAmount);
  const remTaking = makingAmount > 0n ? (takingAmount * remMaker) / makingAmount : takingAmount;

  const mkInfo = byContract[makerAsset] || { name: makerAsset.slice(0, 8) + "…", decimals: 18 };
  const tkInfo = byContract[takerAsset] || { name: takerAsset.slice(0, 8) + "…", decimals: 18 };

  const makerIsUsdg = makerAsset === USDG_ADDR;
  const takerIsUsdg = takerAsset === USDG_ADDR;

  const makerBal = raw.makerBalance != null ? BigInt(raw.makerBalance) : null; // maker-asset balance now
  // coverage: fraction of the order the maker can actually back with current balance
  const coverage = (makerBal != null && remMaker > 0n)
    ? Math.min(1, Number(makerBal) / Number(remMaker)) : 1;

  let side, tokenName, tokenContract, tokenDec, limitPriceUsd, usdSize, qtyTokens, usdgFlow;
  if (makerIsUsdg) {
    // BUY token: give USDG, receive TOKEN
    side = "buy";
    tokenName = tkInfo.name; tokenContract = takerAsset; tokenDec = tkInfo.decimals;
    const usdgOut = Number(formatUnits(remMaker, USDG.decimals));        // USDG we must supply
    qtyTokens = Number(formatUnits(remTaking, tokenDec));                 // tokens received
    limitPriceUsd = qtyTokens > 0 ? usdgOut / qtyTokens : 0;
    usdSize = usdgOut;
    usdgFlow = -usdgOut;                                                  // buy CONSUMES USDG
  } else {
    // SELL token: give TOKEN, receive taker (USDG for dollar-true orders)
    side = "sell";
    tokenName = mkInfo.name; tokenContract = makerAsset; tokenDec = mkInfo.decimals;
    qtyTokens = Number(formatUnits(remMaker, tokenDec));
    const takerOut = Number(formatUnits(remTaking, tkInfo.decimals));
    // USD size: if taker is USDG it's dollar-true; otherwise value the token leg at market
    usdSize = takerIsUsdg ? takerOut : 0; // non-USDG: filled after price fetch
    limitPriceUsd = (takerIsUsdg && qtyTokens > 0) ? takerOut / qtyTokens : 0;
    // ONLY USDG-taker sells add spendable USDG, and only for the fraction the maker can cover
    usdgFlow = takerIsUsdg ? takerOut * coverage : 0;
  }

  return {
    orderHash: raw.orderHash, side, tokenName, tokenContract, tokenDec,
    limitPriceUsd, usdSize, qtyTokens, usdgFlow, takerIsUsdg,
    takerName: tkInfo.name, coverage,
    invalidReason: raw.orderInvalidReason || null,
    createDateTime: raw.createDateTime,
  };
}

// ---------- USDG balance for a wallet ----------
const ERC20 = ["function balanceOf(address) view returns (uint256)"];
async function usdgBalance(provider, address) {
  try {
    const bal = await new Contract(USDG.contract, ERC20, provider).balanceOf(address);
    return Number(formatUnits(bal, USDG.decimals));
  } catch { return null; }
}

// ---------- formatting helpers ----------
const usd = (n) => (n < 0 ? "-$" : "$") + Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const pct = (n) => (n >= 0 ? "+" : "") + n.toFixed(1) + "%";
const pad = (s, n) => String(s).padEnd(n);
const padL = (s, n) => String(s).padStart(n);

// ---------- per-wallet analysis ----------
async function analyzeWallet(meta) {
  let address;
  try { address = resolveWallet(meta.name).wallet.address; }
  catch (e) { return { meta, skipped: `key not available (${e.message})` }; }

  const provider = new JsonRpcProvider(RH.rpc, RH.chainId);
  let rawOrders;
  try { rawOrders = await fetchOrders(address); }
  catch (e) { return { meta, address, error: e.message }; }

  const orders = rawOrders.map(normalize);
  // resolve current prices + distance-to-trigger + non-usdg sell USD sizing
  for (const o of orders) {
    o.currentPriceUsd = await priceUsd(o.tokenContract);
    // Only non-USDG SELLS need market-valuing here. A BUY's size is the USDG it commits
    // (already set in normalize) — never re-value it at the token's market price.
    if (o.side === "sell" && !o.takerIsUsdg && o.currentPriceUsd) { o.usdSize = o.qtyTokens * o.currentPriceUsd; }
    // signed % price move required to reach the trigger from current price
    if (o.currentPriceUsd && o.limitPriceUsd) {
      o.distancePct = (o.limitPriceUsd / o.currentPriceUsd - 1) * 100;
    } else o.distancePct = null;
  }
  // sort by closeness to execution (smallest absolute move needed first)
  orders.sort((a, b) => Math.abs(a.distancePct ?? 1e9) - Math.abs(b.distancePct ?? 1e9));

  const usdgBal = await usdgBalance(provider, address);
  const buys = orders.filter(o => o.side === "buy");
  const sells = orders.filter(o => o.side === "sell");
  const totalBuyUsd = buys.reduce((s, o) => s + o.usdSize, 0);
  const totalSellUsdgFlow = sells.reduce((s, o) => s + (o.usdgFlow || 0), 0); // USDG that sells generate

  // ---- dynamic simulation: walk orders nearest-trigger-first ----
  // Rationale (Jesse's nuance): the closer an order is to its trigger, the sooner it is
  // likely to fill. Sells that trigger before a buy ADD USDG that can fund that buy.
  // We track a running USDG balance; the load needed to *guarantee* no buy ever fails is
  // the deepest the running balance dips below zero.
  let running = usdgBal ?? 0;
  let minRunning = running;
  let firstFailBuy = null;
  const walk = [];
  for (const o of orders) {
    const before = running;
    running += o.usdgFlow || 0;
    if (running < minRunning) minRunning = running;
    if (o.side === "buy" && running < 0 && !firstFailBuy) firstFailBuy = { ...o, runningAfter: running };
    walk.push({ ...o, runningBefore: before, runningAfter: running });
  }
  const dynamicLoad = Math.max(0, -minRunning);
  const staticGap = Math.max(0, totalBuyUsd - (usdgBal ?? 0));                       // no sells help
  const bestCaseGap = Math.max(0, totalBuyUsd - (usdgBal ?? 0) - totalSellUsdgFlow); // all sells fill first

  return {
    meta, address, orders, buys, sells, usdgBal,
    totalBuyUsd, totalSellUsdgFlow, staticGap, bestCaseGap, dynamicLoad, firstFailBuy, walk,
  };
}

// ---------- main ----------
const targets = listWallets().filter(w => !w.watchOnly && (!ONLY_WALLET || w.name === ONLY_WALLET));
const results = [];
for (const meta of targets) results.push(await analyzeWallet(meta));

if (AS_JSON) { console.log(JSON.stringify(results, null, 2)); process.exit(0); }

console.log("\n================= ORDER-DISTANCE + FUNDING CALCULATOR =================");
console.log("READ-ONLY. Live 1inch orderbook + DexScreener + on-chain USDG. USD first.");
console.log("Chain: Robinhood (4663). USDG is the chain's dollar (1 USDG ≈ $1).");
console.log(`Generated: ${new Date().toISOString()}`);

let combinedDynamicLoad = 0;
for (const R of results) {
  console.log("\n\n#############################################################");
  console.log(`### WALLET ${R.meta.name}   ${R.address || ""}`);
  if (R.meta.note) console.log(`### ${R.meta.note}`);
  console.log("#############################################################");
  if (R.skipped) { console.log(`  SKIPPED — ${R.skipped}`); continue; }
  if (R.error) { console.log(`  ERROR reading orderbook — ${R.error}`); continue; }
  if (!R.orders.length) { console.log("  No resting orders."); continue; }

  console.log(`\nUSDG on hand: ${R.usdgBal == null ? "UNKNOWN (RPC read failed)" : usd(R.usdgBal)}`);

  // ---- table: every resting order, sorted by closeness to execution ----
  console.log("\nRESTING ORDERS — sorted by CLOSENESS to execution (nearest trigger first):");
  console.log("  " + pad("TOKEN", 12) + pad("SIDE", 6) + padL("LIMIT $", 13) + padL("CURRENT $", 13) + padL("MOVE NEEDED", 14) + padL("USD SIZE", 12) + "  DIRECTION");
  console.log("  " + "-".repeat(84));
  for (const o of R.orders) {
    const move = o.distancePct == null ? "   n/a" : pct(o.distancePct);
    let dir = o.side === "sell"
      ? (o.distancePct != null && o.distancePct <= 0 ? "price AT/ABOVE trigger — fill imminent" : "needs price UP")
      : (o.distancePct != null && o.distancePct >= 0 ? "price AT/BELOW trigger — fill imminent" : "needs price DOWN");
    if (o.side === "buy" && o.invalidReason) dir += `  [UNFUNDABLE NOW: ${o.invalidReason}]`;
    if (o.side === "sell" && o.coverage < 0.999) dir += `  [only ${(o.coverage * 100).toFixed(0)}% covered by token balance]`;
    console.log("  " + pad(o.tokenName, 12) + pad(o.side.toUpperCase(), 6) +
      padL(o.limitPriceUsd ? o.limitPriceUsd.toPrecision(4) : "?", 13) +
      padL(o.currentPriceUsd ? o.currentPriceUsd.toPrecision(4) : "?", 13) +
      padL(move, 14) + padL(usd(o.usdSize), 12) + "  " + dir);
  }

  // ---- BUY funding detail ----
  console.log(`\nBUYS — USDG required vs available:`);
  if (!R.buys.length) console.log("  (no resting buys — nothing to fund)");
  else {
    console.log("  " + pad("TOKEN", 12) + padL("USDG NEEDED", 14) + padL("MOVE NEEDED", 14) + "   note");
    for (const b of R.buys) {
      let note = b.distancePct != null && b.distancePct < 0 ? `token must fall ${Math.abs(b.distancePct).toFixed(1)}% to trigger` : "";
      const sameTokenSells = R.sells.filter(s => s.tokenName === b.tokenName);
      if (sameTokenSells.length) {
        const sellUsd = sameTokenSells.reduce((s, x) => s + (x.usdgFlow || 0), 0);
        note += ` · NOTE: this token's own ${sameTokenSells.length} sell(s) (${usd(sellUsd)}) need price UP and CANNOT fund this buy on its down-move`;
      }
      console.log("  " + pad(b.tokenName, 12) + padL(usd(b.usdSize), 14) +
        padL(b.distancePct == null ? "n/a" : pct(b.distancePct), 14) + (note ? "   " + note : ""));
    }
    console.log(`  ---`);
    console.log(`  Total USDG needed for ALL buys:      ${usd(R.totalBuyUsd)}`);
    console.log(`  USDG on hand now:                    ${R.usdgBal == null ? "?" : usd(R.usdgBal)}`);
    console.log(`  STATIC funding gap (no sells help):  ${usd(R.staticGap)}`);
  }

  // ---- dynamic model ----
  console.log(`\nDYNAMIC MODEL — sells feed buys (Jesse's nuance):`);
  console.log(`  USDG that resting SELLS would generate as they fill: ${usd(R.totalSellUsdgFlow)}`);
  console.log(`  Walking orders nearest-trigger-first, tracking running USDG:`);
  console.log("  " + pad("TOKEN", 12) + pad("SIDE", 6) + padL("USDG Δ", 12) + padL("RUNNING USDG", 16) + "   flag");
  for (const w of R.walk) {
    const flag = (w.side === "buy" && w.runningAfter < 0) ? "  <-- BUY UNDERFUNDED here" : "";
    console.log("  " + pad(w.tokenName, 12) + pad(w.side.toUpperCase(), 6) +
      padL((w.usdgFlow >= 0 ? "+" : "") + w.usdgFlow.toFixed(2), 12) +
      padL(usd(w.runningAfter), 16) + flag);
  }

  // ---- bottom line ----
  console.log(`\n  ----- BOTTOM LINE (${R.meta.name}) -----`);
  if (!R.buys.length) {
    console.log(`  No buys resting → nothing to fund. FULLY FUNDED.`);
  } else if (R.dynamicLoad <= 0.005) {
    console.log(`  FULLY FUNDED even accounting for sells feeding buys — no need to load the wallet.`);
    console.log(`  (Worst case if NO sells fill first: load ${usd(R.staticGap)}.)`);
  } else {
    console.log(`  >>> LOAD ${usd(R.dynamicLoad)} MORE USDG to guarantee every order can fill`);
    console.log(`      (accounting for sells that trigger before each buy).`);
    console.log(`  Range:  best case (all sells fill first) load ${usd(R.bestCaseGap)}  ·  worst case (no sells) load ${usd(R.staticGap)}.`);
    if (R.firstFailBuy) console.log(`  First buy to run dry: ${R.firstFailBuy.tokenName} (${usd(R.firstFailBuy.usdSize)}), running USDG hits ${usd(R.firstFailBuy.runningAfter)}.`);
  }
  combinedDynamicLoad += R.dynamicLoad;
}

if (results.filter(r => r.buys?.length).length) {
  console.log("\n\n=======================================================================");
  console.log("SINGLE NUMBER JESSE ASKED FOR (per-wallet, since USDG can't cross wallets):");
  for (const R of results) {
    if (!R.buys?.length) continue;
    const line = R.dynamicLoad <= 0.005
      ? "fully funded (sells cover the buys)"
      : `load ${usd(R.dynamicLoad)} more USDG`;
    console.log(`  ${pad(R.meta.name, 10)} → ${line}`);
  }
  console.log("=======================================================================");
}
console.log("\nNothing was signed, submitted, or cancelled. Read-only.\n");
