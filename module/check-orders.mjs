// ============================================================
// CHECK ORDERS — read-only audit of every 1inch limit order for a wallet,
// classified correctly: FILLED / RESTING / PARTIAL / CANCELLED-EXPIRED.
// Born 2026-07-23 after a throwaway audit script mislabeled two FILLED
// SPACEHOOD buys as "resting" (it never read orderInvalidReason). This is
// the permanent, correct version. Never places, cancels, or signs anything.
//
// Usage:
//   node check-orders.mjs                 # wallet-2 (default), all orders
//   node check-orders.mjs --wallet wallet-1
//   node check-orders.mjs --token AI      # filter one ticker
// ============================================================
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const env = readFileSync(join(HERE, ".env"), "utf8");
const KEY = env.match(/ONEINCH_API_KEY=(.+)/)?.[1]?.trim();
if (!KEY) { console.error("no ONEINCH_API_KEY in module/.env"); process.exit(1); }

const args = {};
const argv = process.argv.slice(2);
for (let i = 0; i < argv.length; i++) if (argv[i].startsWith("--")) { args[argv[i].slice(2)] = argv[i + 1]; i++; }

const wallets = JSON.parse(readFileSync(join(HERE, "..", "cockpit", "wallets.public.json"), "utf8")).wallets;
const wName = args.wallet || wallets.find((w) => w.default)?.name || wallets[0]?.name;   // roster default, never a hardcoded name (2026-07-26)
const MAKER = wallets.find(w => w.name === wName)?.address;
if (!MAKER) { console.error(`wallet ${wName} not in cockpit/wallets.public.json`); process.exit(1); }

const reg = JSON.parse(readFileSync(join(HERE, "registry.json"), "utf8")).tokens;
const byAddr = {};
let dollarTrue = null;
for (const [t, v] of Object.entries(reg)) {
  if (!v || typeof v !== "object" || !v.contract) continue;
  byAddr[v.contract.toLowerCase()] = { t, d: v.decimals ?? 18 };
  if (v.dollarTrue && v.chainId === 4663) dollarTrue = v.contract.toLowerCase();
}

const url = `https://api.1inch.dev/orderbook/v4.0/4663/address/${MAKER}?page=1&limit=100&statuses=1,2,3`;
const resp = await fetch(url, { headers: { Authorization: `Bearer ${KEY}` } });
if (!resp.ok) { console.error("orderbook HTTP", resp.status, (await resp.text()).slice(0, 300)); process.exit(1); }
const orders = await resp.json();

const buckets = { FILLED: [], RESTING: [], PARTIAL: [], "CANCELLED/EXPIRED/INVALID": [] };
for (const o of orders) {
  const d = o.data || {};
  const ma = (d.makerAsset || "").toLowerCase(), ta = (d.takerAsset || "").toLowerCase();
  const mk = byAddr[ma] || { t: ma.slice(0, 8), d: 18 };
  const tk = byAddr[ta] || { t: ta.slice(0, 8), d: 18 };
  const buy = ma === dollarTrue;
  const tokenSym = buy ? tk.t : mk.t;
  if (args.token && tokenSym.toUpperCase() !== args.token.toUpperCase()) continue;
  const making = Number(d.makingAmount) / 10 ** mk.d, taking = Number(d.takingAmount) / 10 ** tk.d;
  const price = buy ? making / taking : taking / making;
  const usd = buy ? making : taking;
  const remaining = o.remainingMakerAmount != null ? Number(o.remainingMakerAmount) / 10 ** mk.d : null;
  const filledPct = remaining != null && making > 0 ? 100 * (1 - remaining / making) : null;

  // classification order matters: the API's own verdict first, then remaining math
  let bucket;
  const reason = o.orderInvalidReason;
  if (reason === "order filled" || (filledPct != null && filledPct >= 99.999)) bucket = "FILLED";
  else if (reason == null && (filledPct == null || filledPct === 0)) bucket = "RESTING";
  else if (reason == null && filledPct > 0) bucket = "PARTIAL";
  else bucket = "CANCELLED/EXPIRED/INVALID";

  buckets[bucket].push(
    `${(buy ? "BUY " : "SELL ") + tokenSym}`.padEnd(17) +
    `@ $${price.toPrecision(4)}`.padEnd(14) +
    `$${usd.toFixed(2)}`.padEnd(9) +
    (filledPct != null ? `filled ${filledPct.toFixed(1)}%`.padEnd(14) : "".padEnd(14)) +
    (reason && reason !== "order filled" ? `[${reason}] ` : "") +
    o.orderHash.slice(0, 12) + "…"
  );
}

console.log(`ORDER AUDIT — ${wName} (${MAKER.slice(0, 8)}…) · ${orders.length} orders on the 4663 book · read-only\n`);
for (const [name, rows] of Object.entries(buckets)) {
  if (!rows.length) continue;
  console.log(`── ${name} (${rows.length}) ──`);
  rows.forEach(r => console.log("  " + r));
  console.log();
}
if (!orders.length) console.log("no orders found for this wallet");
