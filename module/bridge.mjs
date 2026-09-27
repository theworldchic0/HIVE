// ============================================================
// BRIDGE — cross-chain transfer + optional bridge-to-buy, via the LI.FI route
// aggregator (li.quest). LI.FI compares Across / Stargate / Relay / CCIP on every
// transfer and returns the single best signable route, so "find the best route"
// is the aggregator's job, not a hardcoded ETH hop. Born 2026-07-23 (Jesse).
//
// SAME SAFETY MODEL AS swap.mjs / arm.mjs:
//   * PREVIEW BY DEFAULT. Nothing is signed or sent without --confirm GO.
//   * Registry-gated: the destination token (and the buy target) must be an exact
//     match in registry.json — refuses unknown/scam contracts.
//   * USD cap: honors config.limits.maxUsdPerOrder (if set) on the amount bridged.
//   * The private key is read locally at signing time only, never printed.
//   * Every action appended to bridges-log.jsonl with timestamps + tx hashes.
//   * Claude stages/previews; JESSE runs the --confirm GO. (Bridging money is the
//     same hard line as trading — the tool exists so HE fires it, one command.)
//
// BRIDGE ONLY:
//   node bridge.mjs --from base --to robinhood --src USDC --dst USDG --amount 150 --wallet wallet-2 [--confirm GO]
// BRIDGE-TO-BUY (bridge, wait for arrival, then venue-race buy on the dst chain):
//   node bridge.mjs --from base --to robinhood --src USDC --amount 150 --buy AI --wallet wallet-2 [--confirm GO]
//     (--dst defaults to the dst chain's dollar-true stable = USDG on 4663 / USDC on 8453)
// ============================================================
import { readFileSync, appendFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { Wallet, JsonRpcProvider, Contract, parseUnits, formatUnits } from "ethers";
import { resolveWallet } from "./lib/wallets.mjs";

const dir = new URL(".", import.meta.url);
const config = JSON.parse(readFileSync(new URL("./config.json", dir), "utf8"));
const registry = JSON.parse(readFileSync(new URL("./registry.json", dir), "utf8"));
const arg = (n, d) => { const i = process.argv.indexOf("--" + n); return i > -1 ? process.argv[i + 1] : d; };

const FROM = arg("from"), TO = arg("to");
const SRC = arg("src"), BUY = arg("buy", null);
const AMOUNT_RAW = arg("amount", null), USE_ALL = process.argv.includes("--use-all");
const SLIP = Number(arg("slippage", "1"));      // percent
const CONFIRM = arg("confirm", "") === "GO";
const LIFI = "https://li.quest/v1";

// ---------- resolve chains ----------
function chainCfg(name) {
  const c = config.chains[name];
  if (!c) { console.error(`REFUSED: unknown chain '${name}'. Known: ${Object.keys(config.chains).join(", ")}`); process.exit(1); }
  return c;
}
const fromCfg = chainCfg(FROM), toCfg = chainCfg(TO);
if (fromCfg.chainId === toCfg.chainId) { console.error("REFUSED: --from and --to are the same chain (use swap.mjs for same-chain)."); process.exit(1); }

// ---------- resolve tokens (registry, chain-correct) ----------
// A token key is valid for a chain only if its registry chainId matches.
function tokenOnChain(sym, chainId, role) {
  const t = registry.tokens[sym];
  if (!t?.contract) { console.error(`REFUSED: ${role} token '${sym}' not in verified registry.`); process.exit(1); }
  if (t.chainId !== chainId) { console.error(`REFUSED: ${role} '${sym}' is registered on chainId ${t.chainId}, not ${chainId}. Pass the chain-correct key (e.g. WETH_BASE on Base).`); process.exit(1); }
  return t;
}
function dollarTrueOn(chainId) {
  for (const [sym, t] of Object.entries(registry.tokens))
    if (t && typeof t === "object" && t.dollarTrue === true && t.chainId === chainId) return sym;
  return null;
}
const srcTok = tokenOnChain(SRC, fromCfg.chainId, "src");
// dst token: explicit --dst, else the destination chain's dollar-true stable
const DST = arg("dst", dollarTrueOn(toCfg.chainId));
if (!DST) { console.error(`REFUSED: no --dst and no dollar-true stable found for chain ${TO}.`); process.exit(1); }
const dstTok = tokenOnChain(DST, toCfg.chainId, "dst");
const buyTok = BUY ? tokenOnChain(BUY, toCfg.chainId, "buy") : null;

// ---------- provider + wallet ----------
const { wallet: rawWallet, meta: walletMeta } = resolveWallet(arg("wallet", null));
const provider = new JsonRpcProvider(fromCfg.rpc, fromCfg.chainId);
const signer = rawWallet.connect(provider);
const ERC20 = ["function balanceOf(address) view returns (uint256)", "function allowance(address,address) view returns (uint256)", "function approve(address,uint256) returns (bool)"];
const srcC = new Contract(srcTok.contract, ERC20, provider);

// ---------- sizing ----------
let amount;
if (USE_ALL) amount = await srcC.balanceOf(rawWallet.address);
else if (AMOUNT_RAW != null) amount = parseUnits(String(AMOUNT_RAW), srcTok.decimals);
else { console.error("REFUSED: give --amount <tokens> or --use-all."); process.exit(1); }
if (amount <= 0n) { console.error("REFUSED: zero amount (wallet empty or bad --amount)."); process.exit(1); }
const bal = await srcC.balanceOf(rawWallet.address);
if (amount > bal) { console.error(`REFUSED: amount ${formatUnits(amount, srcTok.decimals)} ${SRC} exceeds balance ${formatUnits(bal, srcTok.decimals)}.`); process.exit(1); }
const amountF = Number(formatUnits(amount, srcTok.decimals));

// ---------- LI.FI quote (best route across all bridges) ----------
const qs = new URLSearchParams({
  fromChain: String(fromCfg.chainId), toChain: String(toCfg.chainId),
  fromToken: srcTok.contract, toToken: dstTok.contract,
  fromAmount: amount.toString(),
  fromAddress: rawWallet.address, toAddress: rawWallet.address,
  slippage: String(SLIP / 100),
});
const qr = await fetch(`${LIFI}/quote?${qs}`, { headers: { accept: "application/json" } });
if (!qr.ok) { console.error(`REFUSED: LI.FI quote ${qr.status}: ${(await qr.text()).slice(0, 250)}`); process.exit(1); }
const quote = await qr.json();
const est = quote.estimate || {}, txReq = quote.transactionRequest || {};
const bridgeTool = quote.tool || quote.toolDetails?.name || "?";
const outF = Number(formatUnits(est.toAmount || "0", dstTok.decimals));
const outMinF = Number(formatUnits(est.toAmountMin || est.toAmount || "0", dstTok.decimals));
const fromUsd = Number(est.fromAmountUSD || amountF);
const toUsd = Number(est.toAmountUSD || outF);
const feeUsd = [...(est.feeCosts || []), ...(est.gasCosts || [])].reduce((s, f) => s + Number(f.amountUSD || 0), 0);
const durationS = est.executionDuration ?? "?";
const approvalAddr = est.approvalAddress || txReq.to;

// ---------- USD cap ----------
const cap = config.limits?.maxUsdPerOrder;
if (cap && fromUsd > cap) { console.error(`REFUSED: $${fromUsd.toFixed(2)} exceeds the configured cap of $${cap}. Raise limits.maxUsdPerOrder to bridge more.`); process.exit(1); }

// ---------- PREVIEW (USD first) ----------
console.log("================ BRIDGE PREVIEW ================");
console.log(`LEG 1  BRIDGE  ${amountF.toLocaleString("en-US", { maximumFractionDigits: 4 })} ${SRC} (${FROM}) → ${DST} (${TO})`);
console.log(`ROUTE  best of LI.FI = ${String(bridgeTool).toUpperCase()}  (compared Across/Stargate/Relay/CCIP)`);
console.log(`IN     $${fromUsd.toFixed(2)}  (${amountF} ${SRC})`);
console.log(`OUT    ~$${toUsd.toFixed(2)}  (${outF.toLocaleString("en-US", { maximumFractionDigits: 4 })} ${DST}, min ${outMinF.toLocaleString("en-US", { maximumFractionDigits: 4 })})`);
console.log(`COST   ~$${feeUsd.toFixed(2)} all-in (${(fromUsd > 0 ? (feeUsd / fromUsd * 100) : 0).toFixed(2)}%)  |  ~${durationS}s  |  slippage cap ${SLIP}%`);
console.log(`WALLET ${walletMeta.name} ${rawWallet.address}  (same address both chains)`);
console.log(`DST TOKEN ${dstTok.contract} ✓ registry`);
if (buyTok) {
  console.log(`LEG 2  BUY     after ${DST} lands, market-buy ${BUY} with the received ${DST} (swap.mjs 1inch-vs-Kyber race)`);
  console.log(`BUY TOKEN ${buyTok.contract} ✓ registry`);
}
console.log("===============================================");
if (!CONFIRM) { console.log(`\nDRY RUN — nothing signed, nothing sent. Re-run with --confirm GO to execute${buyTok ? " (both legs)" : ""}.`); process.exit(0); }

const log = (rec) => appendFileSync(new URL("./bridges-log.jsonl", dir), JSON.stringify({ time: new Date().toISOString(), ...rec }) + "\n");

// ---------- LEG 1: approve (if needed) + send the bridge tx ----------
if ((await srcC.allowance(rawWallet.address, approvalAddr)) < amount) {
  console.log(`\napproving ${SRC} for LI.FI router ${approvalAddr}…`);
  const atx = await srcC.connect(signer).approve(approvalAddr, amount);
  await atx.wait();
  console.log("approved:", atx.hash);
}
// destination balance BEFORE (to detect arrival independently of LI.FI)
const dstProvider = new JsonRpcProvider(toCfg.rpc, toCfg.chainId);
const dstC = new Contract(dstTok.contract, ERC20, dstProvider);
const dstBefore = await dstC.balanceOf(rawWallet.address);

console.log("\nsending bridge tx on", FROM, "…");
const sent = await signer.sendTransaction({
  to: txReq.to, data: txReq.data, value: BigInt(txReq.value || 0),
  ...(txReq.gasLimit ? { gasLimit: BigInt(txReq.gasLimit) } : {}),
});
console.log("bridge tx:", sent.hash);
await sent.wait();
console.log("source tx confirmed. waiting for", DST, "to land on", TO, "…");
log({ event: "bridge_sent", from: FROM, to: TO, src: SRC, dst: DST, amountIn: amountF, srcTx: sent.hash, bridge: bridgeTool });

// ---------- wait for arrival (poll destination balance) ----------
let landed = 0n;
for (let i = 0; i < 60; i++) {                        // up to ~5 min
  await new Promise(r => setTimeout(r, 5000));
  const now = await dstC.balanceOf(rawWallet.address);
  if (now > dstBefore) { landed = now - dstBefore; break; }
  if (i % 6 === 5) console.log(`  …still waiting (${(i + 1) * 5}s)`);
}
if (landed <= 0n) {
  console.log("⚠ bridge sent but destination balance hasn't increased yet. It may still be in flight — check bridges-log.jsonl + the wallet on", TO, "shortly.");
  log({ event: "bridge_pending", srcTx: sent.hash });
  process.exit(0);
}
const landedF = Number(formatUnits(landed, dstTok.decimals));
console.log(`✅ ${landedF.toLocaleString("en-US", { maximumFractionDigits: 4 })} ${DST} landed on ${TO}.`);
log({ event: "bridge_landed", dst: DST, received: landedF, srcTx: sent.hash });

// ---------- LEG 2 (optional): bridge-to-buy via swap.mjs venue race ----------
if (buyTok) {
  console.log(`\nLEG 2 — market-buying ${BUY} with ${landedF.toFixed(2)} ${DST} (venue race)…`);
  try {
    const out = execFileSync("node", ["swap.mjs", "--src", DST, "--dst", BUY, "--usd", String(landedF.toFixed(2)), "--slippage", String(SLIP), "--wallet", walletMeta.name, "--confirm", "GO"],
      { cwd: dir.pathname || new URL(".", import.meta.url).pathname, encoding: "utf8", timeout: 180000 });
    console.log(out.split("\n").slice(-14).join("\n"));
    log({ event: "bridge_to_buy_done", buy: BUY, spentUsdg: landedF });
  } catch (e) {
    console.error("LEG 2 buy failed:", String(e.message).slice(0, 300));
    console.error(`The ${DST} is safe in the wallet — you can buy ${BUY} manually with: node swap.mjs --src ${DST} --dst ${BUY} --usd ${landedF.toFixed(2)} --wallet ${walletMeta.name} --confirm GO`);
    log({ event: "bridge_to_buy_FAILED", buy: BUY, error: String(e.message).slice(0, 200) });
  }
}
console.log("\nDONE. Logged to bridges-log.jsonl.");
