// ARM — build, preview, and (only with --confirm GO) sign + submit a 1inch limit order.
// Safety gates, in order: registry match (exact contract, decoy rejection) →
// hard caps from config.json → PREVIEW ALWAYS (USD-first) → explicit --confirm GO
// required for approval tx + signing + submission. Without it: dry run, nothing signed.
//
// Usage (preview):  node arm.mjs --token BASTION --side sell --qty-pct 50 --price-above-pct 2.5 --taker WETH --expiry-hours 48
// Usage (execute):  same + --confirm GO
import { readFileSync, appendFileSync } from "node:fs";
import { Wallet, JsonRpcProvider, Contract, parseUnits, formatUnits, formatEther, MaxUint256 } from "ethers";
import { LimitOrder, MakerTraits, Address, Sdk, randBigInt, FetchProviderConnector } from "@1inch/limit-order-sdk";

// ---------- args ----------
const arg = (name, def) => {
  const i = process.argv.indexOf("--" + name);
  return i > -1 ? process.argv[i + 1] : def;
};
const TOKEN = arg("token"); const SIDE = arg("side", "sell");
const QTY_PCT = Number(arg("qty-pct", "0")); const QTY_RAW = arg("qty", null);
const USD_IN = Number(arg("usd", "0")); // buy side: dollars to spend
const PRICE_ABOVE_PCT = Number(arg("price-above-pct", "2.5"));
const TAKER = arg("taker", "WETH"); const EXPIRY_H = Number(arg("expiry-hours", "48"));
const CONFIRM = arg("confirm", "") === "GO";
if (!TOKEN || !["sell", "buy"].includes(SIDE)) { console.error("usage: --token <REG_NAME> --side sell|buy"); process.exit(1); }
if (SIDE === "buy" && (!USD_IN || !arg("limit-usd", null))) { console.error("buy side requires --usd <dollars> and --limit-usd <price>"); process.exit(1); }

// ---------- load config, registry, key ----------
const dir = new URL(".", import.meta.url);
const config = JSON.parse(readFileSync(new URL("./config.json", dir), "utf8"));
const registry = JSON.parse(readFileSync(new URL("./registry.json", dir), "utf8"));
const env = readFileSync(new URL("./.env", dir), "utf8");
const AUTH_KEY = env.match(/ONEINCH_API_KEY=(.+)/)?.[1]?.trim();
import { resolveWallet } from "./lib/wallets.mjs";
const { wallet, meta: walletMeta } = resolveWallet(arg("wallet", null));

// ---------- GATE 1: registry ----------
const tok = registry.tokens[TOKEN]; const taker = registry.tokens[TAKER];
if (!tok?.contract) { console.error(`REFUSED: ${TOKEN} is not in the verified registry.`); process.exit(1); }
if (!taker?.contract) { console.error(`REFUSED: taker ${TAKER} is not in the verified registry.`); process.exit(1); }
if (tok.chainId !== taker.chainId) { console.error("REFUSED: token and taker on different chains."); process.exit(1); }
// ETH-SPEND is MARKET ORDERS ONLY (Jesse 2026-07-31): a resting limit order locks a
// token-to-ETH exchange rate, so as ETH moves, the effective USD limit price drifts —
// exactly what a limit order exists to prevent. Limit orders stay stable-funded.
const _gasSyms = Object.values(config.ethSpend?.gasTokens?.[String(tok.chainId)] || {});
if (tok.native || taker.native || _gasSyms.includes(TOKEN) || _gasSyms.includes(TAKER)) {
  console.error("REFUSED: ETH (native or wrapped) cannot fund a LIMIT order — the token/ETH rate drifts in USD as ETH moves, which defeats the point of a limit. Use a market order (swap.mjs, ETH-SPEND switch) or a dollar-true taker.");
  process.exit(1);
}
// PROVISIONAL rows (vet-lite) carry their own hard cap — enforced here too (2026-07-26).
const EFF_CAP = (tok?.provisional && tok?.maxOrderUsd)
  ? Math.min(config.limits.maxUsdPerOrder, tok.maxOrderUsd)
  : config.limits.maxUsdPerOrder;
const chainId = tok.chainId;
const chainCfg = Object.values(config.chains).find(c => c.chainId === chainId);

// ---------- live data ----------
const provider = new JsonRpcProvider(chainCfg.rpc || "https://rpc.mainnet.chain.robinhood.com", chainId);
const ERC20 = ["function balanceOf(address) view returns (uint256)", "function allowance(address,address) view returns (uint256)", "function approve(address,uint256) returns (bool)"];
// maker = what WE give; taker asset = what we receive
const makerTok = SIDE === "sell" ? tok : taker;
const takerTok = SIDE === "sell" ? taker : tok;
const makerC = new Contract(makerTok.contract, ERC20, provider);
const balance = await makerC.balanceOf(wallet.address);

const ds = await (await fetch(`https://api.dexscreener.com/latest/dex/tokens/${tok.contract}`)).json();
const pair = (ds.pairs || []).sort((a, b) => (b.liquidity?.usd || 0) - (a.liquidity?.usd || 0))[0];
if (!pair) { console.error("REFUSED: no live pair found for price."); process.exit(1); }
if (pair.quoteToken.address.toLowerCase() !== taker.contract.toLowerCase())
  console.log(`NOTE: main pool quote (${pair.quoteToken.symbol}) differs from taker asset ${TAKER}; fills route extra hops.`);
const priceUsd = Number(pair.priceUsd);          // token in USD
const priceNative = Number(pair.priceNative);    // token in quote units (WETH)

// ---------- amounts ----------
const LIMIT_USD = arg("limit-usd", null);
const wethUsd = priceUsd / priceNative; // USD price of the pool's quote asset
// Dollar-true taker = the chain's real dollar settlement asset: USDG on Robinhood (4663), USDC on Base (8453).
// Generalized via the registry dollarTrue flag; USDG kept as explicit fallback so Robinhood behavior is unchanged.
const isStableTaker = TAKER === "USDG" || taker.dollarTrue === true;
let limitPriceUsd, effAbovePct;
if (LIMIT_USD) {
  limitPriceUsd = Number(LIMIT_USD);
  effAbovePct = (limitPriceUsd / priceUsd - 1) * 100;
} else {
  limitPriceUsd = priceUsd * (1 + PRICE_ABOVE_PCT / 100);
  effAbovePct = PRICE_ABOVE_PCT;
}

let makingAmount, takingAmount, qtyFloat, orderUsd;
if (SIDE === "sell") {
  if (QTY_RAW) makingAmount = parseUnits(QTY_RAW, tok.decimals);
  else if (QTY_PCT > 0) makingAmount = (balance * BigInt(Math.round(QTY_PCT * 100))) / 10000n;
  else { console.error("Provide --qty-pct or --qty."); process.exit(1); }
  if (makingAmount <= 0n) { console.error("REFUSED: zero balance/amount."); process.exit(1); }
  if (makingAmount > balance) { console.error("REFUSED: amount exceeds balance."); process.exit(1); }
  qtyFloat = Number(formatUnits(makingAmount, tok.decimals));
  // taking in taker units: USDG = 1:1 dollars (dollar-true); else convert via quote's CURRENT USD (drifts)
  const takingFloat = isStableTaker ? qtyFloat * limitPriceUsd : (qtyFloat * limitPriceUsd) / wethUsd;
  takingAmount = parseUnits(takingFloat.toFixed(taker.decimals > 12 ? 12 : taker.decimals), taker.decimals);
  orderUsd = qtyFloat * limitPriceUsd;
} else {
  // BUY: we give TAKER currency (must be USDG for dollar-true buys), we receive TOKEN at limit price
  if (!isStableTaker) { console.error("REFUSED: buy side requires a dollar-true taker (USDG on Robinhood Chain, USDC on Base)."); process.exit(1); }
  makingAmount = parseUnits(USD_IN.toFixed(taker.decimals), taker.decimals);
  qtyFloat = USD_IN / limitPriceUsd; // tokens we will receive if filled
  takingAmount = parseUnits(qtyFloat.toFixed(12), tok.decimals);
  orderUsd = USD_IN;
  if (makingAmount > balance)
    console.log(`⚠ FUNDING: wallet holds ${formatUnits(balance, taker.decimals)} ${TAKER} but this buy needs ${USD_IN}. Order will rest anyway (1inch fills partially against available balance) — load the wallet to make it fully executable.`);
}

// ---------- GATE 2: caps ----------
if (orderUsd > EFF_CAP) { console.error(`REFUSED: $${orderUsd.toFixed(2)} exceeds the per-order cap $${EFF_CAP}${tok?.provisional ? " (PROVISIONAL vet-lite row — full token-vetter lifts it)" : ""}.`); process.exit(1); }
if (EXPIRY_H * 60 < config.limits.minExpiryMinutes || EXPIRY_H > config.limits.maxExpiryDays * 24) { console.error("REFUSED: expiry outside configured bounds."); process.exit(1); }

// ---------- PREVIEW (USD first, always) ----------
const expiration = BigInt(Math.floor(Date.now() / 1000)) + BigInt(EXPIRY_H * 3600);
console.log("================ ORDER PREVIEW ================");
if (SIDE === "sell") {
  console.log(`SELL  $${orderUsd.toFixed(2)} of ${TOKEN}  (${qtyFloat.toLocaleString("en-US", { maximumFractionDigits: 2 })} tokens, ${QTY_PCT ? QTY_PCT + "% of bag" : "custom qty"})`);
  console.log(`FOR   ~$${orderUsd.toFixed(2)} in ${TAKER}  (${formatUnits(takingAmount, taker.decimals)} ${TAKER})`);
} else {
  console.log(`BUY   $${orderUsd.toFixed(2)} of ${TOKEN}  (~${qtyFloat.toLocaleString("en-US", { maximumFractionDigits: 2 })} tokens if fully filled)`);
  console.log(`PAY   ${formatUnits(makingAmount, taker.decimals)} ${TAKER}`);
}
console.log(`LIMIT $${limitPriceUsd.toFixed(8)} per token  (${effAbovePct >= 0 ? "+" : ""}${effAbovePct.toFixed(1)}% vs market $${priceUsd.toFixed(8)})`);
console.log(`EXPIRES in ${(EXPIRY_H / 24).toFixed(0)} days (${new Date(Number(expiration) * 1000).toISOString()}) — expiry is free, cancel costs gas`);
console.log(`WALLET ${walletMeta.name}  ${wallet.address}`);
console.log(`CHAIN  ${tok.chain} (${chainId})`);
console.log(`TOKEN CONTRACT  ${tok.contract}  ✓ registry`);
console.log(`TAKER CONTRACT  ${taker.contract}  ✓ registry`);
if (isStableTaker) console.log(`FILLS DIRECTLY IN DOLLARS (USDG) — dollar-true limit, no ETH drift, no sweep needed`);
else console.log(`⚠ ${TAKER}-denominated: USD fill value drifts with ${TAKER}'s price over the order's life. AFTER FILL: sweep ${TAKER} → USDG (Jesse's OK per sweep)`);
console.log("===============================================");

if (!CONFIRM) { console.log("\nDRY RUN — nothing signed, nothing submitted. Re-run with --confirm GO to execute."); process.exit(0); }

// ---------- EXECUTE: approval if needed, then sign + submit ----------
// Orders MUST be built via sdk.createOrder (attaches the required fee extension)
// and MUST allow partial + multiple fills (orderbook rejects bit-invalidator
// nonce mode for non-RFQ orders). Learned empirically 2026-07-20.
const sdk = new Sdk({ authKey: AUTH_KEY, networkId: chainId, httpConnector: new FetchProviderConnector() });
const order = await sdk.createOrder({
  makerAsset: new Address(makerTok.contract),
  takerAsset: new Address(takerTok.contract),
  makingAmount, takingAmount,
  maker: new Address(wallet.address),
}, MakerTraits.default().withExpiration(expiration).allowPartialFills().allowMultipleFills());

const typed = order.getTypedData(chainId);
const spender = typed.domain.verifyingContract;
const allowance = await makerC.allowance(wallet.address, spender);
if (allowance < makingAmount) {
  console.log(`\nApproval needed: allowing 1inch router ${spender} to pull ${makerTok===tok?TOKEN:TAKER}…`);
  const signer = wallet.connect(provider);
  const tx = await makerC.connect(signer).approve(spender, MaxUint256); // one-time unlimited: multi-order ladders share one allowance
  console.log("approval tx:", tx.hash);
  await tx.wait();
  console.log("approval confirmed.");
}

const signature = await wallet.signTypedData(typed.domain, { Order: typed.types.Order }, typed.message);
await sdk.submitOrder(order, signature);
const record = {
  time: new Date().toISOString(), chainId, wallet: walletMeta.name, token: TOKEN, side: SIDE,
  orderHash: order.getOrderHash(chainId), qty: qtyFloat, limitPriceUsd,
  takingAmount: formatUnits(takingAmount, taker.decimals) + " " + TAKER,
  orderUsd: Number(orderUsd.toFixed(2)), expiresAt: new Date(Number(expiration) * 1000).toISOString(),
};
appendFileSync(new URL("./orders-log.jsonl", dir), JSON.stringify(record) + "\n");
console.log("\n✅ ORDER LIVE ON 1INCH ORDERBOOK");
console.log("orderHash:", record.orderHash);
console.log("Logged to orders-log.jsonl. Mac can now be closed — resting + filling is server-side.");
