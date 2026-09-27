// Environment for the executor: chains, API keys, wallet, journal.
// Keys are read from files at use time and never printed. Same lookup order as hive/secrets.py:
// process env -> <Hive root>/.env -> module/.env (the terminal's file).
import { readFileSync, appendFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Wallet, JsonRpcProvider } from "ethers";

const HERE = dirname(fileURLToPath(import.meta.url));
export const BEE_ROOT = join(HERE, "..", "..");
export const HIVE_ROOT = join(BEE_ROOT, "..", "..");
const MODULE_DIR = join(HIVE_ROOT, "module");

function parseEnv(path) {
  const out = {};
  try {
    for (const line of readFileSync(path, "utf8").split(/\r?\n/)) {
      const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
      if (m) out[m[1]] = m[2].replace(/^["']|["']$/g, "");
    }
  } catch { /* missing file is fine */ }
  return out;
}
const PLACEHOLDER = /PASTE_|YOUR_|REPLACE_ME|</;
export function secret(name) {
  let v = process.env[name];
  if (!v) v = parseEnv(join(HIVE_ROOT, ".env"))[name];
  if (!v) v = parseEnv(join(MODULE_DIR, ".env"))[name];
  return v && !PLACEHOLDER.test(v) ? v.trim() : null;
}

// Protocol constants — mirror of hive/chains.py; module/config.json overrides RPC/slugs when present.
export const CHAINS = {
  base: {
    chainId: 8453, kyberSlug: "base", rpc: "https://mainnet.base.org", rpcEnv: "BASE_RPC_URL",
    stable: { symbol: "USDC", contract: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", decimals: 6 },
  },
  robinhood: {
    chainId: 4663, kyberSlug: "robinhood", rpc: "https://rpc.mainnet.chain.robinhood.com", rpcEnv: "ROBINHOOD_RPC_URL",
    stable: { symbol: "USDG", contract: "0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168", decimals: 6 },
  },
};
try {
  const cfg = JSON.parse(readFileSync(join(MODULE_DIR, "config.json"), "utf8"));
  for (const [k, c] of Object.entries(cfg.chains || {})) {
    if (CHAINS[k]) {
      if (c.rpc) CHAINS[k].rpc = c.rpc;
      if (c.kyberSlug) CHAINS[k].kyberSlug = c.kyberSlug;
    }
  }
} catch { /* terminal not installed alongside: constants above stand */ }

export function chain(name) {
  const c = CHAINS[String(name || "").toLowerCase()];
  if (!c) throw Object.assign(new Error(`unknown chain '${name}' (known: ${Object.keys(CHAINS).join(", ")})`), { fatal: true });
  return c;
}

const providers = {};
export function provider(name) {
  const c = chain(name);
  if (!providers[name]) providers[name] = new JsonRpcProvider(secret(c.rpcEnv) || c.rpc, c.chainId, { staticNetwork: true });
  return providers[name];
}

export const KEY_FILE = process.env.TRADER_BEE_KEY_FILE || join(BEE_ROOT, "secrets", "agent_wallet.key");
export const JOURNAL = process.env.TRADER_BEE_JOURNAL || join(HIVE_ROOT, "hive_data", "trader_bee", "exec-journal.jsonl");

export function loadWallet() {
  if (!existsSync(KEY_FILE)) throw Object.assign(new Error("no Trader Bee wallet: run `python trader.py wallet-new`"), { code: "NO_KEY" });
  const raw = readFileSync(KEY_FILE, "utf8").trim();
  if (!raw || PLACEHOLDER.test(raw)) throw Object.assign(new Error("agent_wallet.key is empty or a placeholder"), { code: "NO_KEY" });
  return new Wallet(raw.startsWith("0x") ? raw : "0x" + raw);
}

export function createWallet() {
  if (existsSync(KEY_FILE)) throw new Error("agent_wallet.key already exists — refusing to overwrite");
  mkdirSync(dirname(KEY_FILE), { recursive: true });
  const w = Wallet.createRandom();
  writeFileSync(KEY_FILE, w.privateKey + "\n", { mode: 0o600, flag: "wx" });
  return w.address;
}

// Every broadcast is journaled BEFORE waiting on the receipt, so a crash mid-wait can be reconciled.
export function journal(entry) {
  try {
    mkdirSync(dirname(JOURNAL), { recursive: true });
    appendFileSync(JOURNAL, JSON.stringify({ ts: new Date().toISOString(), ...entry }) + "\n");
  } catch (e) {
    process.stderr.write(`journal write failed: ${e.message}\n`);
  }
}
