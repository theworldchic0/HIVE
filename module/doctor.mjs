// ─────────────────────────────────────────────────────────────────────────────
// doctor.mjs — SETUP SELF-CHECK for the Altcoin Trading System.
//
// Run this FIRST on any new machine, before booting the dashboard or trading.
// It checks every requirement and, for each one, either says ✅ with proof or
// ❌ with the exact fix. It makes REAL calls (Alchemy, 1inch, both chains) so a
// wrong or expired key is caught, not just a blank one.
//
//   node doctor.mjs            (human-readable report)
//   node doctor.mjs --json     (machine-readable, for scripts)
//
// Read-only. Never places an order, never moves money, never prints a secret.
// Exit code 0 = all CRITICAL checks passed. Exit code 1 = something to fix.
// ─────────────────────────────────────────────────────────────────────────────

import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..");                 // Trading-Engine/
const JSON_MODE = process.argv.includes("--json");
const NO_NET = process.argv.includes("--offline"); // skip live network checks

// ── tiny ANSI helpers (auto-off when piped / --json) ─────────────────────────
const TTY = process.stdout.isTTY && !JSON_MODE;
const c = (n, s) => (TTY ? `\x1b[${n}m${s}\x1b[0m` : s);
const green = (s) => c(32, s), red = (s) => c(31, s), yellow = (s) => c(33, s);
const dim = (s) => c(2, s), bold = (s) => c(1, s), cyan = (s) => c(36, s);

// ── minimal .env parser (KEY=VALUE, ignores # comments, strips quotes) ───────
function parseEnv(path) {
  const out = {};
  if (!existsSync(path)) return out;
  for (let line of readFileSync(path, "utf8").split("\n")) {
    line = line.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq === -1) continue;
    const k = line.slice(0, eq).trim();
    let v = line.slice(eq + 1).trim();
    if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) v = v.slice(1, -1);
    out[k] = v;
  }
  return out;
}

// values that mean "not actually filled in" (placeholders in the shipped .env)
const PLACEHOLDER = /^$|^(your|paste|replace|changeme|change_me|xxx+|placeholder|<.*>|todo|tbd)/i;
const isSet = (v) => v != null && !PLACEHOLDER.test(String(v).trim());
const mask = (v) => (isSet(v) ? `${String(v).slice(0, 4)}…${String(v).slice(-2)} (${String(v).length} chars)` : "—");

// fetch with a hard timeout so a dead network can't hang the doctor
async function ping(url, opts = {}, ms = 9000) {
  const ac = new AbortController();
  const t = setTimeout(() => ac.abort(), ms);
  try { return await fetch(url, { ...opts, signal: ac.signal }); }
  finally { clearTimeout(t); }
}
async function rpcBlockNumber(url) {
  const r = await ping(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "eth_blockNumber", params: [] }),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const j = await r.json();
  if (j.error) throw new Error(j.error.message || "rpc error");
  if (!j.result || !/^0x[0-9a-f]+$/i.test(j.result)) throw new Error("no block number in reply");
  return parseInt(j.result, 16);
}

// ── load config + env ────────────────────────────────────────────────────────
let cfg = {};
try { cfg = JSON.parse(readFileSync(join(HERE, "config.json"), "utf8")); } catch { /* flagged below */ }
const modEnv = parseEnv(join(HERE, ".env"));       // module/.env  (keys)
const rootEnv = parseEnv(join(ROOT, ".env"));      // Trading-Engine/.env (X token)
// SCREENSHOT-SAFE URLS (2026-07-26, community report): users legitimately put keyed RPC
// endpoints (Alchemy/Infura style) into config.chains[x].rpc — and doctor output is exactly
// what people screenshot into chats for help. Mask any long random path segment before
// printing; the checks themselves still use the real URL.
const maskRpc = (u) => String(u).replace(/(\/)[A-Za-z0-9_-]{16,}(?=\/|$)/g, "$1[KEY_HIDDEN]");
const rpcRobin = cfg?.chains?.robinhood?.rpc || "https://rpc.mainnet.chain.robinhood.com";
const rpcBase = cfg?.chains?.base?.rpc || "https://mainnet.base.org";

// ── the checklist. each returns {ok, warn?, detail, fix?} ────────────────────
// level: "critical" (system won't work right) | "recommended" (a feature degrades)
const checks = [
  { id: "node", level: "critical", title: "Node.js version", async run() {
    const major = parseInt(process.versions.node.split(".")[0], 10);
    return major >= 18
      ? { ok: true, detail: `v${process.versions.node}` }
      : { ok: false, detail: `v${process.versions.node} — too old`,
          fix: "Install Node LTS (18+) from https://nodejs.org, then re-run." };
  }},

  { id: "deps", level: "critical", title: "Dependencies installed", async run() {
    if (!existsSync(join(HERE, "node_modules"))) {
      return { ok: false, detail: "node_modules missing",
        fix: `Run:  cd "${HERE}" && npm ci   (or npm install)` };
    }
    try { await import("@1inch/limit-order-sdk"); await import("ethers");
      return { ok: true, detail: "@1inch/limit-order-sdk + ethers load OK" };
    } catch (e) {
      return { ok: false, detail: `import failed: ${e.message}`,
        fix: `Run:  cd "${HERE}" && npm ci` };
    }
  }},

  { id: "config", level: "critical", title: "config.json present + valid", async run() {
    return cfg?.chains
      ? { ok: true, detail: `chains: ${Object.keys(cfg.chains).join(", ")}` }
      : { ok: false, detail: "missing or unparseable",
          fix: "config.json must exist in module/ with a chains block. Restore it from the zip." };
  }},

  { id: "registry", level: "critical", title: "Token registry present", async run() {
    try {
      const reg = JSON.parse(readFileSync(join(HERE, "registry.json"), "utf8"));
      const n = Object.keys(reg.tokens || reg || {}).length;
      return n > 0
        ? { ok: true, detail: `${n} vetted tokens` }
        : { ok: false, warn: true, detail: "registry has 0 tokens",
            fix: "Nothing can trade without a registry row. Add vetted tokens before trading." };
    } catch {
      return { ok: false, detail: "registry.json missing/unparseable",
        fix: "Restore registry.json from the zip — the trade whitelist lives here." };
    }
  }},

  { id: "wallet", level: "critical", title: "Wallet key present", async run() {
    const files = ["wallet.key", "wallet-2.key"].filter((f) => existsSync(join(HERE, f)));
    if (!files.length) return { ok: false, detail: "no wallet.key found",
      fix: "Create or import a wallet during setup. Your private key lives ONLY in module/wallet.key on this machine." };
    for (const f of files) {
      const raw = readFileSync(join(HERE, f), "utf8").trim();
      // engine (verify-wallet.mjs) accepts bare 64-hex OR 0x-prefixed; match that.
      if (!/^(0x)?[0-9a-fA-F]{64}$/.test(raw)) {
        return { ok: false, detail: `${f} is not a valid 32-byte private key`,
          fix: `${f} must be 64 hex chars (with or without a leading 0x). Re-import your key (paste it into ${f}, nothing else).` };
      }
    }
    return { ok: true, detail: `${files.join(", ")} — valid format (never printed)` };
  }},

  { id: "oneinch", level: "critical", title: "1inch API key (execution)", async run() {
    const k = modEnv.ONEINCH_API_KEY;
    if (!isSet(k)) return { ok: false, detail: "ONEINCH_API_KEY not set",
      fix: "Get a free key at https://portal.1inch.dev → create an app → paste into module/.env as ONEINCH_API_KEY=..." };
    if (NO_NET) return { ok: true, warn: true, detail: `set ${mask(k)} (offline: not verified)` };
    try {
      const r = await ping("https://api.1inch.dev/swap/v6.0/8453/tokens",
        { headers: { Authorization: `Bearer ${k}`, accept: "application/json" } });
      if (r.status === 401 || r.status === 403)
        return { ok: false, detail: `key rejected (HTTP ${r.status})`,
          fix: "Key is wrong or expired. Re-copy it from https://portal.1inch.dev into module/.env." };
      if (r.ok || r.status === 429)
        return { ok: true, detail: `key accepted by 1inch (HTTP ${r.status})` };
      return { ok: true, warn: true, detail: `inconclusive (HTTP ${r.status}) — key is set but 1inch answered oddly`,
        fix: "Not blocking. If trades fail, re-check the key at https://portal.1inch.dev." };
    } catch (e) {
      return { ok: false, warn: true, detail: `could not reach 1inch: ${e.message}`,
        fix: "Check internet. Key is set but couldn't be verified live." };
    }
  }},

  { id: "alchemy", level: "critical", title: "Alchemy API key (wallet tracking)", async run() {
    const k = modEnv.ALCHEMY_API_KEY || modEnv.ALCHEMY_KEY;
    if (!isSet(k)) return { ok: false, detail: "ALCHEMY_API_KEY not set — wallet/ledger tracking will be BLIND",
      fix: "Get a free key at https://dashboard.alchemy.com (create an app on Base Mainnet) → paste into module/.env as ALCHEMY_API_KEY=..." };
    if (NO_NET) return { ok: true, warn: true, detail: `set ${mask(k)} (offline: not verified)` };
    try {
      const block = await rpcBlockNumber(`https://base-mainnet.g.alchemy.com/v2/${k}`);
      return { ok: true, detail: `key works — Base block #${block.toLocaleString()}` };
    } catch (e) {
      return { ok: false, detail: `key did not work: ${e.message}`,
        fix: "Key is wrong/expired or the app isn't enabled for Base Mainnet. Re-copy from https://dashboard.alchemy.com into module/.env." };
    }
  }},

  { id: "rpc-robin", level: "critical", title: "Robinhood Chain reachable", async run() {
    if (NO_NET) return { ok: true, warn: true, detail: "skipped (offline)" };
    try { const b = await rpcBlockNumber(rpcRobin);
      return { ok: true, detail: `block #${b.toLocaleString()} @ ${maskRpc(rpcRobin)}` };
    } catch (e) { return { ok: false, detail: `unreachable: ${e.message}`,
      fix: `Check internet / that ${maskRpc(rpcRobin)} is up. This is the chainId 4663 RPC.` }; }
  }},

  { id: "rpc-base", level: "critical", title: "Base Chain reachable", async run() {
    if (NO_NET) return { ok: true, warn: true, detail: "skipped (offline)" };
    try { const b = await rpcBlockNumber(rpcBase);
      return { ok: true, detail: `block #${b.toLocaleString()} @ ${maskRpc(rpcBase)}` };
    } catch (e) { return { ok: false, detail: `unreachable: ${e.message}`,
      fix: `Check internet / that ${maskRpc(rpcBase)} is up. This is the chainId 8453 RPC.` }; }
  }},

  { id: "selftest", level: "critical", title: "Order build+sign path", async run() {
    try {
      const { LimitOrder, MakerTraits, Address, randBigInt } = await import("@1inch/limit-order-sdk");
      const { Wallet } = await import("ethers");
      const TEST_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"; // public 1inch test key
      const maker = new Wallet(TEST_KEY);
      const traits = MakerTraits.default()
        .withExpiration(BigInt(Math.floor(Date.now() / 1000)) + 3600n)
        .withNonce(randBigInt((1n << 40n) - 1n));
      const order = new LimitOrder({
        makerAsset: new Address("0xf44702b17d9abD53815F703e772F35E9c71A53af"),
        takerAsset: new Address("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"),
        makingAmount: 10_000_000_000_000_000_000_000n, takingAmount: 20_000_000n,
        maker: new Address(maker.address),
      }, traits);
      for (const chainId of [8453, 4663]) {
        const td = order.getTypedData(chainId);
        const sig = await maker.signTypedData(td.domain, { Order: td.types.Order }, td.message);
        if (!sig || sig.length < 132) throw new Error(`bad signature on chain ${chainId}`);
      }
      return { ok: true, detail: "EIP-712 sign works on both chains (no network, no real key)" };
    } catch (e) {
      return { ok: false, detail: `selftest failed: ${e.message}`,
        fix: `Run:  cd "${HERE}" && npm ci   then re-run the doctor.` };
    }
  }},

  { id: "codex", level: "recommended", title: "Codex API key (suggestions)", async run() {
    const k = modEnv.CODEX_API_KEY;
    return isSet(k)
      ? { ok: true, detail: `set ${mask(k)}` }
      : { ok: false, warn: true, detail: "not set — suggestion/discovery lists will be empty",
          fix: "Optional. Get a key from https://www.codex.io and add CODEX_API_KEY=... to module/.env to enable market discovery." };
  }},

  { id: "xtoken", level: "recommended", title: "X (Twitter) bearer token", async run() {
    const k = rootEnv.X_BEARER_TOKEN;
    return isSet(k)
      ? { ok: true, detail: `set ${mask(k)}` }
      : { ok: false, warn: true, detail: "not set — social/founder tracing disabled",
          fix: "Optional. Add X_BEARER_TOKEN=... to Trading-Engine/.env to enable X lookups." };
  }},
];

// ── run everything ────────────────────────────────────────────────────────────
const results = [];
for (const chk of checks) {
  let r;
  try { r = await chk.run(); }
  catch (e) { r = { ok: false, detail: `check crashed: ${e.message}` }; }
  results.push({ ...chk, ...r });
}

const critFail = results.filter((r) => r.level === "critical" && !r.ok);
const recFail = results.filter((r) => r.level === "recommended" && !r.ok);
const passCount = results.filter((r) => r.ok && !r.warn).length;

// ── installed version (answers "which build am I on?" — the #1 support question)
const VERSION_FILE = join(ROOT, "VERSION");
const INSTALLED_VERSION = existsSync(VERSION_FILE)
  ? readFileSync(VERSION_FILE, "utf8").split("\n")[0].trim()
  : "(no VERSION file — a build older than 2026-07-31)";

// ── output ────────────────────────────────────────────────────────────────────
if (JSON_MODE) {
  console.log(JSON.stringify({
    ok: critFail.length === 0,
    version: INSTALLED_VERSION,
    passed: passCount, total: results.length,
    criticalFailures: critFail.map((r) => r.id),
    checks: results.map((r) => ({ id: r.id, title: r.title, level: r.level, ok: r.ok, warn: !!r.warn, detail: r.detail, fix: r.fix || null })),
  }, null, 2));
} else {
  const line = "─".repeat(64);
  console.log("\n" + bold(cyan("  ALTCOIN TRADING SYSTEM — SETUP DOCTOR")));
  console.log(dim(`  installed version: ${INSTALLED_VERSION}`));
  console.log(dim("  " + line));
  for (const r of results) {
    const icon = r.ok ? (r.warn ? yellow("⚠") : green("✔")) : red("✘");
    const tag = r.level === "recommended" ? dim(" (optional)") : "";
    console.log(`  ${icon}  ${bold(r.title)}${tag}`);
    console.log(`      ${dim(r.detail)}`);
    if (!r.ok && r.fix) console.log(`      ${yellow("→ " + r.fix)}`);
  }
  console.log(dim("  " + line));
  if (critFail.length === 0) {
    console.log("  " + green(bold(`✔ ALL CRITICAL CHECKS PASSED (${passCount}/${results.length} green)`)));
    if (recFail.length) console.log("  " + yellow(`⚠ ${recFail.length} optional item(s) off — some features degrade, safe to trade.`));
    console.log(dim("  You're clear to boot the dashboard.\n"));
  } else {
    console.log("  " + red(bold(`✘ ${critFail.length} CRITICAL problem(s) — do NOT trade yet.`)));
    console.log("  " + red("Fix the ✘ items above (each has a → fix), then run this again:"));
    console.log(dim(`      node "${fileURLToPath(import.meta.url)}"\n`));
  }
}

process.exit(critFail.length === 0 ? 0 : 1);
