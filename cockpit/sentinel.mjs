// ============================================================
// MOONBAG SENTINEL — fill-triggered take-profit top-ups.
// Born 2026-07-22 from Jesse's ruling ("Yes — build the sentinel"), settling
// the moonbag-shape decision: when a pre-approved RESTING LIMIT BUY fills,
// automatically place top-up SELLS on the newly acquired tokens so Jesse's
// TP percentages stay true to the whole bag as it grows.
//
// AUTHORIZATION MODEL (approve-before-spend, kept intact):
//   * The ONLY actions this module can take are the ones pre-approved in
//     sentinel-rules.json — Jesse blessed each rule's exact levels/fractions
//     in chat before it was written. No rule, no trade.
//   * SELLS ONLY. There is no code path here that can buy.
//   * Live placement requires the host process to be ARMED
//     (TRADE_IDEA_ARMED=1) — disarmed instances only log what they WOULD do.
//   * arm.mjs independently re-enforces registry match + the config per-order cap +
//     the --confirm gate. Defence in depth, same as every other path.
//   * Idempotent: every processed fill is recorded in sentinel-state.json
//     (by order hash) before placement is attempted — a fill can never
//     top-up twice, even across restarts.
//   * FULL fills only in v1: an order reported "order filled" by 1inch, or
//     an order that vanished from the book (datasource doctrine: we never
//     cancel, so off-book = inferred filled; basis logged either way).
//     Partial fills are logged as notify-only.
//   * Everything is appended to sentinel-log.jsonl — every tick decision,
//     every placement, every refusal, with timestamps.
// ============================================================
import { readFileSync, writeFileSync, appendFileSync, existsSync } from "node:fs";
import { execFile } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const MODULE = join(HERE, "..", "module");
const RULES_FILE = join(HERE, "sentinel-rules.json");
const STATE_FILE = join(HERE, "sentinel-state.json");
const LOG_FILE = join(HERE, "sentinel-log.jsonl");

const ARMED = process.env.TRADE_IDEA_ARMED === "1";

// taker = the CHAIN'S dollar-true stable (2026-07-26, community report: USDG was hardcoded,
// so Base rules were silently refused by arm.mjs's cross-chain gate). Config is the truth.
let CHAIN_TAKERS = {};
try {
  const _c = JSON.parse(readFileSync(join(MODULE, "config.json"), "utf8"));
  for (const [k, v] of Object.entries(_c.chains || {})) if (v?.dollarTrueToken) CHAIN_TAKERS[k] = v.dollarTrueToken;
} catch {}
const takerFor = (chain) => CHAIN_TAKERS[chain] || "USDG";

function log(ev) {
  try { appendFileSync(LOG_FILE, JSON.stringify({ ts: new Date().toISOString(), ...ev }) + "\n"); } catch {}
}
function loadRules() {
  try { return (JSON.parse(readFileSync(RULES_FILE, "utf8")).rules || []).filter(r => r.enabled); }
  catch (e) { log({ ev: "rules-unreadable", error: String(e.message) }); return []; }
}
function loadState() {
  try { return JSON.parse(readFileSync(STATE_FILE, "utf8")); }
  catch { return { knownOpen: {}, processedFills: {}, lastTick: null }; }
}
function saveState(s) { writeFileSync(STATE_FILE, JSON.stringify(s, null, 1)); }

const round6 = (n) => Number(n.toFixed(6));

function runArm(argv) {
  return new Promise((resolve) => {
    execFile("node", ["arm.mjs", ...argv], { cwd: MODULE, timeout: 120000 }, (err, stdout, stderr) => {
      const out = String(stdout || "");
      resolve({
        ok: !err,
        orderHash: out.match(/orderHash:\s*(0x[0-9a-fA-F]{8,})/)?.[1] || null,
        stdout: out.slice(-1500),
        stderr: String(stderr || "").slice(-500),
        error: err ? String(err.message).slice(0, 200) : null,
      });
    });
  });
}

// One sentinel pass. `getState` supplies the dashboard's cached /api/state object
// (the host passes its own state builder so we reuse fill detection + never
// double-fetch). Returns a summary for the host's log.
export async function sentinelTick(getState) {
  const rules = loadRules();
  if (!rules.length) return { ok: true, note: "no enabled rules" };
  const st = loadState();
  let state;
  try { state = await getState(); } catch (e) { log({ ev: "state-unavailable", error: String(e.message) }); return { ok: false, error: "state unavailable" }; }

  const actions = [];
  for (const rule of rules) {
    // the rule's position: same token+wallet, AUTHORIZED, never a decoy
    const pos = (state.positions || []).find(p =>
      p.ticker === rule.token && p.wallet === rule.wallet && p.registryStatus === "AUTHORIZED" && !p.isDecoy);
    if (!pos) continue;

    // BAG-FRACTION rules (Jesse 2026-07-24: "sell 15% of the entire bag at this price,
    // but that number changes as the bag grows"): keep frac × current bag offered at the
    // level by ADDING top-up sells as the bag grows. Never cancels; if the bag shrinks
    // (a TP filled, tokens moved out) nothing is added — sells only, as always.
    if (rule.watch === "bag-fraction") {
      await handleBagFraction(rule, pos, st, actions);
      continue;
    }

    // current open resting BUY orders for this rule (placed after the rule was born)
    const openBuys = (pos.openOrders || []).filter(o =>
      (o.side || "").toLowerCase() === "buy" &&
      (!o.createdAt || !rule.createdAfter || new Date(o.createdAt) >= new Date(rule.createdAfter)));

    const key = rule.id;
    const known = st.knownOpen[key] || {};   // orderHash -> {qty, limitPriceUsd, seenAt}
    const nowOpen = {};
    for (const o of openBuys) {
      const h = o.orderHash || null;
      if (!h) continue;
      // datasource semantics: FILLED orders never appear here (they become lots) and
      // CANCELLED ones go to cancelledOrders — openOrders is resting/underfunded/partial.
      nowOpen[h] = { qty: o.qty, limitPriceUsd: o.limitPriceUsd, status: o.status, expiresAt: o.expiresAt || null, seenAt: known[h]?.seenAt || new Date().toISOString() };
    }
    // an order we knew as OPEN that vanished from openOrders either filled or cancelled.
    // Ground truth, in order of strength: (1) a buy LOT carrying that orderHash =
    // datasource-confirmed fill (qty from the lot); (2) presence in cancelledOrders =
    // no action; (3) neither = inferred fill per the never-cancel doctrine.
    for (const [h, rec] of Object.entries(known)) {
      if (nowOpen[h]) continue;
      const cancelled = (pos.cancelledOrders || []).some(c => c.orderHash === h);
      if (cancelled) { log({ ev: "order-cancelled-no-action", rule: key, orderHash: h }); continue; }
      const fillLot = (pos.lots || []).find(l => l.orderHash === h && l.side === "buy");
      if (fillLot) { await handleFill(rule, pos, h, fillLot.qty ?? rec.qty, "confirmed: fill lot on the book (" + (fillLot.note || "1inch-book") + ")", st, actions); continue; }
      // safety (2026-07-23): a vanished order that was past its expiry did NOT fill —
      // inferring a fill here would place TP sells for tokens never bought.
      if (rec.expiresAt && new Date() > new Date(new Date(rec.expiresAt).getTime() - 5 * 60 * 1000)) {
        log({ ev: "order-expired-no-action", rule: key, orderHash: h, expiresAt: rec.expiresAt }); continue;
      }
      await handleFill(rule, pos, h, rec.qty, "inferred: order left the book, no cancel record (we never cancel)", st, actions);
    }
    st.knownOpen[key] = nowOpen;
  }
  st.lastTick = new Date().toISOString();
  saveState(st);
  return { ok: true, actions };
}

async function handleFill(rule, pos, orderHash, filledQty, basis, st, actions) {
  if (st.processedFills[orderHash]) return;               // idempotency — never twice
  st.processedFills[orderHash] = { at: new Date().toISOString(), rule: rule.id, basis };
  saveState(st);                                          // record BEFORE acting
  const qty = Number(filledQty) || 0;
  if (qty <= 0) { log({ ev: "fill-no-qty", rule: rule.id, orderHash, basis }); return; }
  log({ ev: "buy-fill-detected", rule: rule.id, orderHash, filledQty: qty, basis, armed: ARMED });

  for (const lvl of rule.tpLevels) {
    const sellQty = round6(qty * lvl.fracOfFill);
    if (sellQty <= 0) continue;
    const argv = ["--token", rule.token, "--side", "sell", "--qty", String(sellQty),
      "--limit-usd", String(lvl.price), "--taker", takerFor(rule.chain || pos.chain), "--wallet", rule.wallet,
      "--expiry-hours", String(rule.expiryHours || 2400)];
    if (!ARMED) {
      log({ ev: "topup-skipped-disarmed", rule: rule.id, orderHash, level: lvl.price, qty: sellQty, wouldRun: "node arm.mjs " + argv.join(" ") });
      actions.push({ level: lvl.price, qty: sellQty, placed: false, reason: "disarmed" });
      continue;
    }
    const res = await runArm([...argv, "--confirm", "GO"]);
    log({ ev: res.ok ? "topup-placed" : "topup-FAILED", rule: rule.id, sourceBuy: orderHash,
      level: lvl.price, qty: sellQty, orderHash: res.orderHash, error: res.error, stderr: res.stderr || undefined });
    actions.push({ level: lvl.price, qty: sellQty, placed: res.ok, orderHash: res.orderHash });
  }
}

// ---------- BAG-FRACTION top-ups (Jesse 2026-07-24) ----------
// State: st.bagPlaced[rule.id] = cumulative qty this rule has placed at its level
// (seeded from the initial standing sell recorded on the rule). Each tick:
//   target = frac × current bag qty; delta = target − placed.
// A top-up is placed only when delta is worth it (≥ minTopUpUsd at the level).
// placed is recorded BEFORE the order attempt (crash can under-sell, never over-sell)
// and rolled back on a failed placement so the next tick retries.
async function handleBagFraction(rule, pos, st, actions) {
  st.bagPlaced = st.bagPlaced || {};
  if (st.bagPlaced[rule.id] == null) {
    st.bagPlaced[rule.id] = Number(rule.initialPlacedQty) || 0;
    saveState(st);
    log({ ev: "bagfrac-rule-seen", rule: rule.id, seededPlacedQty: st.bagPlaced[rule.id], frac: rule.frac, price: rule.price });
  }
  const bag = Number(pos.currentQty) || 0;
  const target = bag * rule.frac;
  const placed = st.bagPlaced[rule.id];
  const delta = target - placed;
  const minUsd = rule.minTopUpUsd ?? 2;
  if (!(delta > 0) || delta * rule.price < minUsd) return;
  const qty = round6(delta);
  const argv = ["--token", rule.token, "--side", "sell", "--qty", String(qty),
    "--limit-usd", String(rule.price), "--taker", takerFor(rule.chain || pos.chain), "--wallet", rule.wallet,
    "--expiry-hours", String(rule.expiryHours || 2400)];
  if (!ARMED) {
    log({ ev: "bagfrac-skipped-disarmed", rule: rule.id, qty, level: rule.price, wouldRun: "node arm.mjs " + argv.join(" ") });
    actions.push({ rule: rule.id, level: rule.price, qty, placed: false, reason: "disarmed" });
    return;
  }
  st.bagPlaced[rule.id] = placed + qty;   // record BEFORE acting (never over-sell on crash)
  saveState(st);
  const res = await runArm([...argv, "--confirm", "GO"]);
  if (!res.ok) { st.bagPlaced[rule.id] = placed; saveState(st); }   // roll back → next tick retries
  log({ ev: res.ok ? "bagfrac-topup-placed" : "bagfrac-topup-FAILED", rule: rule.id,
    qty, level: rule.price, bag: round6(bag), target: round6(target),
    orderHash: res.orderHash, error: res.error, stderr: res.ok ? undefined : res.stderr });
  actions.push({ rule: rule.id, level: rule.price, qty, placed: res.ok, orderHash: res.orderHash });
}

// read-only status for the dashboard (/api/sentinel)
export function sentinelStatus() {
  const st = loadState();
  const rules = loadRules();
  let tail = [];
  try { tail = readFileSync(LOG_FILE, "utf8").trim().split("\n").slice(-12).map(l => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean); } catch {}
  return { armed: ARMED, rules: rules.map(r => ({ id: r.id, token: r.token, wallet: r.wallet,
    watch: r.watch || "resting-limit-buys",
    levels: (r.tpLevels || []).length || (r.watch === "bag-fraction" ? 1 : 0),
    ...(r.watch === "bag-fraction" ? { frac: r.frac, price: r.price, placedQty: (st.bagPlaced || {})[r.id] ?? r.initialPlacedQty ?? 0 } : {}),
    approvedBy: r.approvedBy })), lastTick: st.lastTick, processedFills: Object.keys(st.processedFills || {}).length, recent: tail };
}
