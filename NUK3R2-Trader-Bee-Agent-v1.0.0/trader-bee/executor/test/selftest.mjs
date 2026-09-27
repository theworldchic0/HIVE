// OFFLINE SELF-TEST — zero network, zero real keys, cannot move money.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, existsSync, statSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { LimitOrder, MakerTraits, Address, randBigInt, getLimitOrderContract } from "@1inch/limit-order-sdk";
import { Wallet } from "ethers";
import { toRaw, fromRaw } from "../lib/units.mjs";
import { pickOrder, spenderAllowed } from "../lib/venues.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const EXEC = join(HERE, "..", "exec.mjs");
let n = 0;
const ok = (name) => { n++; console.log("  ✓", name); };

// units: truncate, never round up
assert.equal(toRaw("1.2345679", 6), 1234567n); ok("toRaw truncates extra precision");
assert.equal(toRaw("10", 6), 10000000n); ok("toRaw whole numbers");
assert.equal(fromRaw(1234567n, 6), "1.234567"); ok("fromRaw");
assert.throws(() => toRaw("1e5", 6)); ok("toRaw rejects exponent notation");

// venue ordering: best live quote first, failures last
const order = pickOrder([{ venue: "1inch", ok: true, raw: "100" }, { venue: "kyber", ok: true, raw: "105" }, { venue: "x", ok: false }]);
assert.deepEqual(order.map(q => q.venue), ["kyber", "1inch", "x"]); ok("race picks the larger output");
assert.equal(pickOrder([{ venue: "1inch", ok: false }, { venue: "kyber", ok: true, raw: "1" }])[0].venue, "kyber"); ok("failed venue never wins");

// pinned spenders
const pins = ["0x111111125421cA6dc452d289314280a0f8842A65"];
assert.ok(spenderAllowed("0x111111125421ca6dc452d289314280a0f8842a65", pins)); ok("pinned spender allowed (case-insensitive)");
assert.ok(!spenderAllowed("0xdeadbeef00000000000000000000000000000000", pins)); ok("unpinned spender refused");

// CLI: wallet-new / address / refuse overwrite, key file private
const dir = mkdtempSync(join(tmpdir(), "bee-"));
const env = { ...process.env, TRADER_BEE_KEY_FILE: join(dir, "agent_wallet.key"), TRADER_BEE_JOURNAL: join(dir, "j.jsonl") };
const run = (cmd, payload = {}) => { try { return JSON.parse(execFileSync("node", [EXEC, cmd], { input: JSON.stringify(payload), env }).toString().trim().split("\n").pop()); }
  catch (e) { return JSON.parse(e.stdout.toString().trim().split("\n").pop()); } };
const noKey = run("address");
assert.equal(noKey.ok, false); assert.equal(noKey.fatal, true); ok("address without a key is a clear fatal error");
const created = run("wallet-new");
assert.ok(created.ok && /^0x[0-9a-fA-F]{40}$/.test(created.address)); ok("wallet-new creates a wallet");
assert.ok(!JSON.stringify(created).includes(readFileSync(env.TRADER_BEE_KEY_FILE, "utf8").trim())); ok("private key never appears in output");
if (process.platform !== "win32") { assert.equal(statSync(env.TRADER_BEE_KEY_FILE).mode & 0o777, 0o600); ok("key file is chmod 600"); }
assert.equal(run("address").address, created.address); ok("address reads the same wallet back");
const again = run("wallet-new");
assert.equal(again.ok, false); ok("wallet-new refuses to overwrite an existing key");
assert.equal(run("nope").fatal, true); ok("unknown command is fatal");

// 1inch limit-order build + EIP-712 signing path (the take-profit path), offline, public test key
const maker = new Wallet("0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80");
for (const chainId of [8453, 4663]) {
  const o = new LimitOrder({ makerAsset: new Address("0x4200000000000000000000000000000000000006"), takerAsset: new Address("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"),
    makingAmount: 10n ** 18n, takingAmount: 2_000_000n, maker: new Address(maker.address) },
    MakerTraits.default().withExpiration(BigInt(Math.floor(Date.now() / 1000) + 3600)).withNonce(randBigInt((1n << 40n) - 1n)));
  const td = o.getTypedData(chainId);
  const sig = await maker.signTypedData(td.domain, { Order: td.types.Order }, td.message);
  assert.equal(sig.length, 132);
  const cfg = JSON.parse(readFileSync(join(HERE, "..", "..", "config", "trader_bee.json"), "utf8"));
  const chainName = chainId === 8453 ? "base" : "robinhood";
  assert.equal(td.domain.verifyingContract.toLowerCase(), getLimitOrderContract(chainId).toLowerCase());
  assert.ok(spenderAllowed(td.domain.verifyingContract, cfg.execution.allowed_spenders[chainName]), `limit-order protocol on ${chainId} must be pinned in config`);
  ok(`limit order signs on chain ${chainId}; protocol ${td.domain.verifyingContract.slice(0, 10)}… is pinned in config`);
}
// take-profit order classification (same rules as the terminal's check-orders.mjs)
const { classifyOrder } = await import("../exec.mjs");
const mk = (making, remaining, reason) => ({ data: { makingAmount: String(making) }, remainingMakerAmount: remaining == null ? undefined : String(remaining), orderInvalidReason: reason });
assert.equal(classifyOrder(mk(1000, 0, "order filled")).status, "FILLED"); ok("orderbook 'order filled' = FILLED");
assert.equal(classifyOrder(mk(1000, 1000, null)).status, "RESTING"); ok("untouched order = RESTING");
const part = classifyOrder(mk(1000, 250, null));
assert.equal(part.status, "PARTIAL"); assert.equal(part.filledPct, 75); ok("partial fill = PARTIAL 75%");
assert.equal(classifyOrder(mk(1000, 1000, "expired")).status, "CLOSED"); ok("expired/cancelled = CLOSED");

console.log(`\nEXECUTOR OFFLINE SELFTEST PASS — ${n} checks, no network touched, nothing can move money.`);
