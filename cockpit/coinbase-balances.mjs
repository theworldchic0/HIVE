// Coinbase LIVE BALANCES for the trading dashboard — READ-ONLY.
// Origin (2026-07-22): exchange holdings were invisible on the dashboard — it scanned on-chain wallets only; Coinbase (the exchange
// account) was a basis-history source but never a balance source. This module
// closes that gap.
//
// SOURCE OF TRUTH: /api/v3/brokerage/portfolios/{uuid} breakdown.spot_positions,
// which carries Coinbase's OWN per-asset fiat valuation (total_balance_fiat) —
// the same numbers the Coinbase app shows. Do NOT rebuild this from the
// accounts endpoint + spot prices: verified 2026-07-22 that /accounts omits
// whole assets (retail-wallet holdings) and undercounted the portfolio by
// roughly half vs Coinbase's own valuation.
//
// Auth: same read-only Advanced Trade key + JWT scheme as ledger/sources/
// coinbase.mjs, creds from Portfolio-Tracker/coinbase.json (known open
// portability item: hardcoded absolute path, same as the ledger source).
// Only GET endpoints are ever called; key material never leaves this process
// and is never logged.
import { readFileSync } from "node:fs";
import crypto from "node:crypto";
import https from "node:https";

const HOST = "api.coinbase.com";
// Portability fix 2026-07-24: env-overridable; falls back to cockpit/coinbase.json (portable),
// then the legacy Desktop Portfolio-Tracker location this Mac has always used.
import { existsSync as _ex } from "node:fs";
import { join as _j, dirname as _dn } from "node:path";
import { fileURLToPath as _fu } from "node:url";
const _HERE = _dn(_fu(import.meta.url));
const CREDS_PATH = process.env.COINBASE_VIEW_KEY_FILE
  || (_ex(_j(_HERE, "coinbase.json")) ? _j(_HERE, "coinbase.json")
      : "./coinbase-readonly-key.json");

const b64url = (i) => Buffer.from(i).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

function makeJwt(creds, iss, method, path) {
  const keyName = creds.name || creds.id, privateKey = creds.privateKey;
  const now = Math.floor(Date.now() / 1000);
  const isPem = privateKey.includes("BEGIN"); // old EC key -> ES256
  const header = { alg: isPem ? "ES256" : "EdDSA", kid: keyName, typ: "JWT", nonce: crypto.randomBytes(16).toString("hex") };
  const payload = { sub: keyName, iss, nbf: now, exp: now + 120, uri: `${method} ${HOST}${path}` };
  const si = b64url(JSON.stringify(header)) + "." + b64url(JSON.stringify(payload));
  let sig;
  if (isPem) {
    sig = crypto.sign("SHA256", Buffer.from(si), { key: privateKey, dsaEncoding: "ieee-p1363" });
  } else { // CDP Ed25519 -> EdDSA
    const raw = Buffer.from(privateKey, "base64");
    const jwk = { kty: "OKP", crv: "Ed25519", d: raw.subarray(0, 32).toString("base64url"), x: raw.subarray(32, 64).toString("base64url") };
    sig = crypto.sign(null, Buffer.from(si), crypto.createPrivateKey({ key: jwk, format: "jwk" }));
  }
  return si + "." + b64url(sig);
}

function rawGet(path, headers = {}) {
  return new Promise((res, rej) => {
    const req = https.request({ hostname: HOST, path, method: "GET", timeout: 20000, headers }, (r) => {
      let d = ""; r.on("data", (c) => (d += c)); r.on("end", () => res({ status: r.statusCode, body: d }));
    });
    req.on("timeout", () => req.destroy(new Error("timeout"))); req.on("error", rej); req.end();
  });
}

async function authGet(creds, path) {
  const clean = path.split("?")[0];
  for (const iss of ["cdp", "coinbase-cloud"]) {
    const jwt = makeJwt(creds, iss, "GET", clean);
    const r = await rawGet(path, { Authorization: "Bearer " + jwt, "Content-Type": "application/json" });
    if (r.status !== 401) return r;
  }
  return { status: 401, body: "unauthorized" };
}

// → { ok, totalUsd, assets:[{currency, qty, usd, cash}], portfolios:[names],
//     inaccessible:[names], at, error? }
export async function fetchCoinbaseBalances() {
  let creds;
  try { creds = JSON.parse(readFileSync(CREDS_PATH, "utf8")); }
  catch (e) { return { ok: false, error: "coinbase creds unreadable: " + String(e.message).slice(0, 80) }; }
  try {
    const pr = await authGet(creds, "/api/v3/brokerage/portfolios");
    if (pr.status !== 200) return { ok: false, error: `coinbase portfolios HTTP ${pr.status}` };
    const portfolios = (JSON.parse(pr.body).portfolios || []).filter(p => !p.deleted);
    const assets = [], names = [], inaccessible = [];
    let totalUsd = 0;
    for (const pf of portfolios) {
      const r = await authGet(creds, `/api/v3/brokerage/portfolios/${pf.uuid}`);
      const bd = r.status === 200 ? JSON.parse(r.body)?.breakdown : null;
      if (!bd) { inaccessible.push(pf.name); continue; } // e.g. CONSUMER portfolio a trade key can't read
      names.push(pf.name);
      // Coinbase's own total (matches the app); fall back to summing positions.
      const declared = Number(bd.portfolio_balances?.total_balance?.value);
      let sum = 0;
      for (const s of (bd.spot_positions || [])) {
        const usd = Number(s.total_balance_fiat) || 0;
        sum += usd;
        if (usd <= 0) continue;
        assets.push({ currency: s.asset || "?", qty: Number(s.total_balance_crypto) || 0, usd, cash: !!s.is_cash });
      }
      totalUsd += Number.isFinite(declared) && declared > 0 ? declared : sum;
    }
    assets.sort((x, y) => y.usd - x.usd);
    return { ok: true, totalUsd, assets, portfolios: names, inaccessible, at: new Date().toISOString() };
  } catch (e) { return { ok: false, error: "coinbase: " + String(e.message).slice(0, 80) }; }
}
