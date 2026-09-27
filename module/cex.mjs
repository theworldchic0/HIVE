// CEX CLI — Coinbase exchange twin of swap.mjs/arm.mjs (VENUES-ROADMAP.md Phase 2).
// Same contract: PREVIEW ALWAYS, explicit --confirm GO to place, whitelist gate,
// per-order USD cap, honest readback from the API after anything executes.
//
//   node cex.mjs --product BTC-USD --side buy  --type market --usd 25            [--confirm GO]
//   node cex.mjs --product BTC-USD --side buy  --type limit  --usd 25 --limit-usd 60000  [--confirm GO]
//   node cex.mjs --product BTC-USD --side sell --type market --qty 3.5           [--confirm GO]
//   node cex.mjs --product BTC-USD --side sell --type limit  --qty 3.5 --limit-usd 12   [--confirm GO]
//   node cex.mjs --orders [--product BTC-USD]     list open orders
//   node cex.mjs --status <orderId>               one order's truth
//   node cex.mjs --cancel <orderId>               cancel (needs trade key)
//   node cex.mjs --balances                       exchange balances
//   node cex.mjs --quote BTC-USD                  price/bid/ask/increments
import * as cb from "./venues/coinbase.mjs";
import { appendFileSync } from "node:fs";

const arg = (n, d) => { const i = process.argv.indexOf("--" + n); return i > -1 ? (process.argv[i + 1] ?? true) : d; };
const has = (n) => process.argv.includes("--" + n);
const die = (m) => { console.error(m); process.exit(1); };

try {
  const mode = cb.keyMode();
  console.log(`COINBASE VENUE — key mode: ${mode.toUpperCase()}${mode === "view-only" ? " (order verbs disabled until module/coinbase-trade.json exists)" : ""}`);

  if (has("balances")) {
    const b = await cb.balances();
    for (const a of b.sort((x, y) => y.available - x.available)) console.log(`${a.currency.padEnd(8)} available ${a.available}${a.hold ? `  (hold ${a.hold})` : ""}`);
    process.exit(0);
  }
  if (has("quote")) {
    console.log(JSON.stringify(await cb.quote(arg("quote")), null, 1)); process.exit(0);
  }
  if (has("orders")) {
    const os = await cb.openOrders(arg("product", null) || undefined);
    if (!os.length) console.log("no OPEN orders" + (arg("product", null) ? ` on ${arg("product")}` : ""));
    for (const o of os) console.log(`${o.orderId}  ${o.productId} ${o.side} ${o.type || ""} ${o.limitPrice != null ? "@ $" + o.limitPrice : ""} base ${o.baseSize ?? "-"} quote ${o.quoteSize ?? "-"} filled ${o.filledPct}%  ${o.createdAt}`);
    process.exit(0);
  }
  if (has("status")) {
    console.log(JSON.stringify(await cb.orderStatus(arg("status")), null, 1)); process.exit(0);
  }
  if (has("cancel")) {
    const r = await cb.cancel(arg("cancel"));
    for (const x of r) console.log(`${x.orderId} ${x.ok ? "CANCELLED" : "FAILED: " + x.reason}`);
    process.exit(0);
  }

  // ---------- order path: preview always, GO to place ----------
  const productId = arg("product") || die("REFUSED: --product PRODUCT-ID required (e.g. BTC-USD)");
  const side = String(arg("side", "")).toUpperCase();
  if (side !== "BUY" && side !== "SELL") die("REFUSED: --side buy|sell required");
  const type = String(arg("type", "")).toLowerCase();
  if (type !== "market" && type !== "limit") die("REFUSED: --type market|limit required");
  const usd = Number(arg("usd", "0")) || null, qty = Number(arg("qty", "0")) || null;
  const limitPrice = Number(arg("limit-usd", "0")) || null;
  if (side === "BUY" && !usd) die("REFUSED: buys size in dollars: --usd N");
  if (side === "SELL" && !qty) die("REFUSED: sells size in base units: --qty N");
  if (type === "limit" && !limitPrice) die("REFUSED: limit orders need --limit-usd PRICE");
  const CONFIRM = arg("confirm", "") === "GO";

  const p = await cb.preview({ productId, side, type, usd, qty, limitPrice });
  console.log("================ COINBASE ORDER PREVIEW ================");
  console.log(`${side} ${type.toUpperCase()}  ${productId}  ${side === "BUY" ? `$${usd}` : `${qty} base`}${limitPrice ? `  @ $${limitPrice}` : ""}`);
  console.log(`LIVE  price $${p.quote.price}  bid $${p.quote.bid}  ask $${p.quote.ask}  24h vol ${p.quote.volume24h}`);
  console.log(`SIZED order_configuration: ${JSON.stringify(p.orderConfiguration)}`);
  console.log(`EST NOTIONAL $${p.estNotionalUsd}  (CEX cap $${cb.CEX_MAX_USD}/order)`);
  if (p.serverPreview && !p.serverPreview.unavailable) {
    const sp = p.serverPreview;
    console.log(`COINBASE PREVIEW  fees $${sp.commission_total ?? "?"}  slippage ${sp.slippage ?? "?"}  ${sp.errs?.length ? "ERRS " + JSON.stringify(sp.errs) : ""}`);
  } else if (p.serverPreview?.unavailable) console.log(`(server-side preview unavailable with this key: ${p.serverPreview.unavailable})`);
  console.log("========================================================");
  if (!CONFIRM) { console.log("\nDRY RUN — re-run with --confirm GO to place."); process.exit(0); }

  const verb = type === "market" ? (side === "BUY" ? cb.marketBuy : cb.marketSell) : (side === "BUY" ? cb.limitBuy : cb.limitSell);
  const r = await verb({ productId, usd, qty, limitPrice, confirm: true });   // CONFIRM was checked above (--confirm GO)
  console.log(`ORDER LIVE ON COINBASE  orderId: ${r.orderId}  clientOrderId: ${r.clientOrderId}`);
  const st = await cb.orderStatus(r.orderId).catch(() => null);
  if (st) console.log(`STATUS ${st.status}  filled ${st.filledSize} @ avg ${st.avgFillPrice ?? "-"}  fees ${st.fee ?? "-"}`);
  appendFileSync(new URL("./orders-log.jsonl", import.meta.url), JSON.stringify({
    time: new Date().toISOString(), venue: "coinbase", type: `cex_${type}_${side.toLowerCase()}`,
    productId, orderId: r.orderId, clientOrderId: r.clientOrderId,
    usd: usd ?? undefined, qty: qty ?? undefined, limitPriceUsd: limitPrice ?? undefined,
    estNotionalUsd: p.estNotionalUsd, status: st?.status || "SUBMITTED",
  }) + "\n");
  console.log("Logged to orders-log.jsonl (venue: coinbase)");
} catch (e) {
  die(String(e.message || e));
}
