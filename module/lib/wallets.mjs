// Multi-wallet loader. Reads wallets.json, resolves a wallet by --wallet name
// (or the default). Key files are read locally only; never printed or transmitted.
import { readFileSync } from "node:fs";
import { Wallet } from "ethers";

const moduleDir = new URL("../", import.meta.url);

export function listWallets() {
  return JSON.parse(readFileSync(new URL("./wallets.json", moduleDir), "utf8")).wallets;
}

export function resolveWallet(name) {
  const ws = listWallets();
  const meta = name ? ws.find(w => w.name === name) : (ws.find(w => w.default) || ws[0]);
  if (!meta) throw new Error(`wallet '${name}' is not in wallets.json (known: ${ws.map(w => w.name).join(", ")})`);
  const raw = readFileSync(new URL("./" + meta.keyFile, moduleDir), "utf8").trim();
  if (!raw || raw.includes("PASTE_YOUR_PRIVATE_KEY"))
    throw new Error(`wallet '${meta.name}': key file ${meta.keyFile} has not been filled yet`);
  return { wallet: new Wallet(raw.startsWith("0x") ? raw : "0x" + raw), meta };
}
