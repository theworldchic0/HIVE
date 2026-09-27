// ============================================================
// UNIFIED TRADING DASHBOARD — server (localhost only, READ-ONLY).
// Holds the keys server-side (datasource reads module/.env in-process);
// the browser only ever sees aggregated JSON — never a key.
// It NEVER signs, places, cancels, or edits any order.
//
//   GET  /                     → dashboard.html
//   GET  /api/state            → aggregated portfolio/orders state (cached ~25s)
//   GET  /api/funding          → funding-calc.mjs --json output    (cached ~2min)
//   POST /api/feedback         → append {time,context,text} to feedback-log.jsonl
//   /api/trade-request, /trade-requests, /trade-responses → 410 GONE (the unreviewed
//                                file-queue was removed 2026-07-21 on arming; the token-gated
//                                /api/trade-idea/* engine is the only execution path)
//   GET  /api/trade-idea/log   → parsed trade-idea-log.jsonl, newest first, optional
//                                ?ticker=X filter. READ-ONLY: feeds the per-card history
//                                threads on the dashboard. No side effects.
//   POST /api/ingest           → re-run the READ-ONLY ledger ingest (robinhood+base+solana)
//                                so fresh on-chain trades get real basis; 5-min cooldown
//   POST /api/triage           → append a Suggested-Plays YES/NO/trigger decision to
//                                triage-decisions.jsonl (append-only training data) and
//                                rebuild exclusions.json for the list generators
//   GET  /api/triage           → all triage decisions (suggested.html renders its lists from this)
//   POST /api/research-request → append {ts,ticker,contract,chain,tier,source_list} to
//                                research-requests.jsonl (Add-to-Database queue; a Claude
//                                session fulfills it and writes research-results.jsonl)
//   GET  /api/research-status  → {requests, results} from the two research jsonl files
//                                (UI shows queued badges + Notion links; queue-and-display only)
//   GET  /api/trade-idea/config → { armed, maxUsdPerOrder, ... } — is the live path enabled?
//   POST /api/trade-idea/analyze→ {positionKey,text,mode} → scenario analysis + confirm token
//   POST /api/trade-idea/execute→ {confirmToken,dryRun} → invoke arm.mjs/swap.mjs (child proc),
//                                stream result back. FORCED dry-run unless TRADE_IDEA_ARMED=1.
//   POST /api/trade-idea/context→ {logRef,context} → attach post-trade "why did we make this
//                                trade" onto a trade-idea-log.jsonl row. WRITE-LIMITED, no exec.
//   POST /api/play-candidate    → append a Jesse-described candidate play to
//                                doctrine/play-candidates.jsonl (append-only, no exec).
//   GET  /api/registry-decoys   → flattened lowercased decoy contracts (card grid hides them)
//   GET  /api/risk-matrix       → risk-matrix.json config + live context (TVL/CCM/powder/basket)
//   POST /api/risk-matrix       → validate + save the FULL config (timestamped .bak first)
//   POST /api/risk-matrix/override → set/clear one per-contract tier override (logged to
//                                risk-overrides.jsonl — overrides logged, not fought)
//   POST /api/risk-matrix/size  → {items:[{contract,ticker,chain,poolUsd}]} → 🟢🟡🔴 tier +
//                                three caps + suggested $ per item (ALL sizing math lives here;
//                                display + prefill only — suggest-never-clamp, no gate touched)
//   static files               → whitelisted extensions from this folder only
//
// Start:  node dashboard-server.mjs     (or double-click ~/Desktop/TRADING-DASHBOARD.command)
// ============================================================
import http from "node:http";
import { readFile, appendFile, writeFile, mkdir } from "node:fs/promises";
import { execFile } from "node:child_process";
import { randomBytes } from "node:crypto";
import { fileURLToPath } from "node:url";
import { dirname, join, extname, normalize } from "node:path";
import { buildState } from "./datasource.mjs";
import { analyzeIdea, executeConfirm, executeProgress, tradeConfig, attachTradeContext, appendPlayCandidate } from "./trade-idea.mjs";
import { sentinelTick, sentinelStatus } from "./sentinel.mjs";
import { vetLite, applyVetLiteRow } from "./vetlite.mjs";
import { saveMatrix, setTierOverride, riskContext, sizeItems } from "./risk-matrix.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const MODULE = join(HERE, "..", "module");
const LEDGER_DIR = join(HERE, "..", "ledger");
// Default 8789 (the launcher + live process are unaffected). DASH_PORT lets a reviewer run a
// SECOND instance on another port to verify code changes without touching the running 8789.
const PORT = process.env.DASH_PORT ? Number(process.env.DASH_PORT) : 8789;
const MIME = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml" };

// ---------- cached, single-flight state ----------
const cache = {
  // state ttl is a thin request-coalescing layer only: real freshness now lives
  // in datasource's two-lane caches (fast balances/prices ≈30s, orders 120s,
  // heavy chain-history 15min) with per-section freshness stamps in the payload.
  // 5s here just stops N open tabs from stampeding buildState.
  //
  // maxStale (2026-07-27, Jesse: "it should never open up with stale stuff. Every
  // time I press refresh, it should refresh"): the OLD code was unconditional
  // stale-while-revalidate, so ANY request past ttl got the PREVIOUS snapshot and
  // only kicked a background rebuild — the fresh data landed on the NEXT press.
  // That is why a fresh page load showed 16-hour-old numbers while the port
  // happily answered 200. Now there are three bands:
  //   age < ttl        → serve cache (request coalescing, unchanged)
  //   ttl..maxStale    → stale-while-revalidate (cheap, keeps tabs responsive)
  //   age > maxStale   → AWAIT the rebuild; never hand back data this old
  // and force=true (the refresh button, and first paint) always awaits.
  state:   { at: 0, ttl: 5_000,   maxStale: 60_000,  data: null, inflight: null, err: null },
  funding: { at: 0, ttl: 120_000, maxStale: 600_000, data: null, inflight: null, err: null },
};
async function cached(slot, producer, { force = false } = {}) {
  const c = cache[slot];
  const age = Date.now() - c.at;
  if (!force && c.data && age < c.ttl) return { data: c.data, stale: false, age, err: c.err };
  if (!c.inflight) {
    c.inflight = producer()
      .then(d => { c.data = d; c.at = Date.now(); c.err = null; return d; })
      .catch(e => {
        c.err = e.message;
        if (!c.data) throw e;
        console.error(`[dashboard] ${slot} refresh failed, serving stale:`, e.message);
        return c.data;
      })
      .finally(() => { c.inflight = null; });
  }
  // Wait for real data when the caller demanded it, when we hold nothing, or when
  // what we hold is older than maxStale. A failed rebuild still reports err so the
  // page can SAY it is stale instead of quietly showing yesterday's numbers.
  if (force || !c.data || age > c.maxStale) {
    const data = await c.inflight;
    return { data, stale: Boolean(c.err), age: Date.now() - c.at, err: c.err };
  }
  return { data: c.data, stale: true, age, err: c.err };
}

function runFundingCalc() {
  return new Promise((resolve, reject) => {
    execFile("node", ["funding-calc.mjs", "--json"], { cwd: MODULE, timeout: 90_000, maxBuffer: 8 * 1024 * 1024 }, (err, stdout) => {
      if (err) return reject(new Error("funding-calc: " + err.message));
      try { resolve(JSON.parse(stdout)); } catch (e) { reject(new Error("funding-calc: bad JSON output")); }
    });
  });
}

function json(res, code, obj) {
  res.writeHead(code, { "Content-Type": "application/json", "Cache-Control": "no-store" });
  res.end(JSON.stringify(obj));
}

function readBody(req, max = 100_000) {   // per-route override: ladder-design carries a canvas PNG
  return new Promise((resolve, reject) => {
    let body = "";
    req.on("data", c => { body += c; if (body.length > max) { req.destroy(); reject(new Error("body too large")); } });
    req.on("end", () => resolve(body));
    req.on("error", reject);
  });
}

async function readJsonl(file, since) {
  let text = "";
  try { text = await readFile(join(HERE, file), "utf8"); } catch { return []; }
  const rows = text.split("\n").filter(Boolean).map(l => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
  return since ? rows.filter(r => (r.time || "") > since) : rows;
}

// ---------- ledger ingest runner (READ-ONLY scan; single-flight; 5-min cooldown) ----------
const ingest = { running: false, lastAt: 0, lastResult: null };
async function runIngest() {
  ingest.running = true;
  try {
    const result = await new Promise((resolve) => {
      execFile("node", ["ingest.mjs", "--source", "robinhood,base,solana"], { cwd: LEDGER_DIR, timeout: 300_000, maxBuffer: 8 * 1024 * 1024 }, (err, stdout) => {
        resolve({ ok: !err, note: err ? String(err.message).slice(0, 200) : (String(stdout).trim().split("\n").pop() || "ok").slice(0, 200) });
      });
    });
    ingest.lastAt = Date.now();
    ingest.lastResult = { time: new Date().toISOString(), ...result };
    cache.state.at = 0; // force fresh state so new lots/basis show immediately
    return ingest.lastResult;
  } finally { ingest.running = false; }
}

// ---------- GeckoTerminal OHLCV proxy (added 2026-07-21, CW-sessionB-uifix) ----------
// The levels charts fetch candles HERE instead of hitting GT from the browser: batch
// screen jobs on this machine burn the per-IP quota, and GT's CORS-less 429 responses
// surface in the page as a bare "Failed to fetch". One server-side cache + global pacing
// means the page never competes with batch jobs and always has last-good candles to serve.
// READ-ONLY market data. Self-contained — touches nothing else.
//
// KEYED as of 2026-07-29 (Jesse: "why wouldn't we wire in the key?"). The keyless public GT host
// handed us a SUSTAINED 429 wall that morning — every chart on the page blank, 429 still returned
// on probes at +45s/+90s/+135s with zero local batch jobs running and no cron. That is NOT the old
// boot-burst 429 logged as harmless in FIXES-LOG entry at line 269; the per-IP free quota was simply
// gone. GeckoTerminal's candles ARE CoinGecko's onchain API, so when module/.env carries
// COINGECKO_API_KEY we call the OFFICIAL keyed CoinGecko host on our own quota instead. Identical
// response shape (data.attributes.ohlcv_list), official sanctioned endpoint, no scraping.
// The keyless GT path is preserved verbatim for when no key is present — it is the pre-existing
// behaviour, not a new fallback.
const OHLCV_TTL = 20_000;              // fresh window per pool+tf
const GT_MIN_GAP = 2_600;              // >=2.6s between upstream calls (~23/min, under the CG demo 30/min cap too)
const ohlcvCache = new Map();          // key -> { at, list, inflight, err }
let gtChain = Promise.resolve();       // serializes + paces ALL upstream candle calls
let gtLastAt = 0;
// module/.env may hold several comma-separated CG keys (Jesse's research MCP carries two); take the
// first. Cached 60s so a key added/rotated mid-session is picked up without a restart.
let cgKeyCache = { at: 0, key: null };
async function cgOnchainKey() {
  if (cgKeyCache.at && Date.now() - cgKeyCache.at < 60_000) return cgKeyCache.key;
  let key = null;
  try {
    const txt = await readFile(join(MODULE, ".env"), "utf8");
    for (const line of txt.split("\n")) {
      const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.+?)\s*$/);
      if (m && m[1] === "COINGECKO_API_KEY") { key = m[2].split(",")[0].trim() || null; break; }
    }
  } catch (_) {}
  cgKeyCache = { at: Date.now(), key };
  return key;
}
function gtFetchPaced(url, extraHeaders = {}, label = "GT") {
  const p = gtChain.then(async () => {
    const wait = gtLastAt + GT_MIN_GAP - Date.now();
    if (wait > 0) await new Promise(r => setTimeout(r, wait));
    gtLastAt = Date.now();
    const res = await fetch(url, {
      headers: { Accept: "application/json;version=20230302", ...extraHeaders },
      signal: AbortSignal.timeout(15_000),
    });
    if (!res.ok) throw new Error(label + " " + res.status);
    return res.json();
  });
  gtChain = p.catch(() => {});         // keep the pacing chain alive after failures
  return p;
}
async function ohlcvProxy(params) {
  const network = String(params.get("network") || "");
  const pool = String(params.get("pool") || "");
  const tf = String(params.get("tf") || "hour");
  const agg = String(params.get("agg") || "1");
  if (!/^[a-z0-9_-]{1,32}$/i.test(network) || !/^[a-zA-Z0-9]{20,80}$/.test(pool) ||
      // {20,80}: Robinhood Chain GT pool ids are 66 chars (0x + 64 hex) and were 400'd by the old {20,64} cap (FIXES-LOG entry O)
      !["minute", "hour", "day"].includes(tf) || !/^\d{1,3}$/.test(agg)) {
    return { code: 400, body: { error: "bad params" } };
  }
  if (ohlcvCache.size > 300) ohlcvCache.clear();   // bounded; never grows past ~all pools*tfs
  const key = `${network}/${pool}/${tf}/${agg}`;
  let c = ohlcvCache.get(key);
  if (!c) { c = { at: 0, list: null, inflight: null, err: null }; ohlcvCache.set(key, c); }
  if (c.list && Date.now() - c.at < OHLCV_TTL) {
    return { code: 200, body: { ohlcv: c.list, fetchedAt: c.at, stale: false } };
  }
  if (!c.inflight) {
    const cgKey = await cgOnchainKey();
    const qs = `aggregate=${agg}&limit=300&currency=usd`;
    const url = cgKey
      ? `https://api.coingecko.com/api/v3/onchain/networks/${network}/pools/${pool}/ohlcv/${tf}?${qs}`
      : `https://api.geckoterminal.com/api/v2/networks/${network}/pools/${pool}/ohlcv/${tf}?${qs}`;
    c.inflight = gtFetchPaced(url, cgKey ? { "x-cg-demo-api-key": cgKey } : {}, cgKey ? "CG" : "GT")
      .then(j => { c.list = j?.data?.attributes?.ohlcv_list || []; c.at = Date.now(); c.err = null; return c.list; })
      .catch(e => { c.err = e.message; if (!c.list) throw e; return c.list; })
      .finally(() => { c.inflight = null; });
  }
  if (c.list) {
    // serve last-good immediately; refresh continues in background
    return { code: 200, body: { ohlcv: c.list, fetchedAt: c.at, stale: true, note: c.err ? `refresh failed (${c.err}) — serving last good` : "refreshing" } };
  }
  try { const list = await c.inflight; return { code: 200, body: { ohlcv: list, fetchedAt: c.at, stale: false } }; }
  catch (e) { return { code: 502, body: { error: "upstream: " + e.message } }; }
}

// ---------- Suggested Plays TRIAGE (added 2026-07-21, CW-sessionB-triage) ----------
// POST /api/triage appends Jesse's YES/NO/trigger decisions to triage-decisions.jsonl
// (append-only — these reasons are TRAINING DATA for future agents, schema is stable):
//   { time_utc, ticker, contract, chain, list_origin: "A"|"B", decision, reason,
//     trigger?, intent?, meta: { price, liq, vol24, ... } }
// decisions: no_soft     — "not interested right now" (soft pass)
//            no_never    — "never show me this again" (permanent blacklist, e.g. scam)
//            no_trigger  — "not until something big happens" (trigger REQUIRED)
//            yes         — interested (moves to the YES list; reason REQUIRED)
//            yes_not_now — from YES list: "not right now" (what-would-make-me-buy trigger REQUIRED)
//            buy_now     — from YES list: buying (intent = Jesse's levels/sizes/TPs captured
//                          verbatim; NO auto-execution — the trade panel stays the only path)
// After every write, exclusions.json is rebuilt so the List A/B GENERATORS never
// resurface holdings, dollar-true stables, blacklisted or already-triaged tokens.
const TRIAGE_FILE = "triage-decisions.jsonl";
const TRIAGE_DECISIONS = new Set(["no_soft", "no_never", "no_trigger", "yes", "yes_not_now", "buy_now"]);
const TRIAGE_TRIGGER_REQUIRED = new Set(["no_trigger", "yes_not_now"]);
// YOUR current holdings — the suggestion lists never resurface what you already hold.
// Ships EMPTY: add your own tickers, e.g. ["BTC", "ETH"].
const TRIAGE_HOLDINGS = [];
async function dollarTrueSymbols() {
  try {
    const reg = JSON.parse(await readFile(join(MODULE, "registry.json"), "utf8"));
    const toks = reg.tokens || reg;
    return Object.entries(toks).filter(([, v]) => v && typeof v === "object" && v.dollarTrue).map(([k]) => k);
  } catch { return ["USDG", "USDC"]; }
}
async function rebuildExclusions() {
  const rows = await readJsonl(TRIAGE_FILE);
  const latest = new Map();                       // contract (lowercased) -> latest decision row
  for (const r of rows) if (r && r.contract && r.decision) latest.set(String(r.contract).toLowerCase(), r);
  const blacklist = [], triaged = [];
  for (const r of latest.values()) {
    const item = { ticker: r.ticker, contract: r.contract, chain: r.chain, decision: r.decision, reason: r.reason, time_utc: r.time_utc };
    if (r.decision === "no_never") blacklist.push(item);
    triaged.push(item);
  }
  const out = {
    _meta: {
      purpose: "SINGLE exclusion source for the Suggested Plays list generators (List A numeric momentum + List B thesis). Any generator MUST load this file and exclude: (1) every ticker in holdings, (2) every ticker in dollarTrue, (3) every contract in blacklist (PERMANENT — Jesse said never show again), (4) every contract in triaged (already decided — the YES / NOT-RIGHT-NOW / BUY views own them now; do not resurface).",
      maintainedBy: "dashboard-server.mjs — rebuilt from triage-decisions.jsonl on boot and on every POST /api/triage. Do NOT hand-edit (overwritten). To add a holding, edit TRIAGE_HOLDINGS in dashboard-server.mjs.",
      matchRule: "tickers match case-insensitively; contracts match case-insensitively on the full address/mint string",
    },
    updated_utc: new Date().toISOString().replace(/\.\d+Z$/, "Z"),
    holdings: TRIAGE_HOLDINGS,
    dollarTrue: await dollarTrueSymbols(),
    blacklist,
    triaged,
  };
  await writeFile(join(HERE, "exclusions.json"), JSON.stringify(out, null, 2) + "\n");
  return out;
}
async function handleTriagePost(body) {
  let d;
  try { d = JSON.parse(body || "{}"); } catch { return { code: 400, out: { ok: false, error: "bad JSON" } }; }
  const ticker = String(d.ticker || "").trim();
  const contract = String(d.contract || "").trim();
  const chain = String(d.chain || "").trim();
  const list_origin = String(d.list_origin || "").trim().toUpperCase();
  const decision = String(d.decision || "").trim();
  const reason = String(d.reason || "").trim();
  const trigger = d.trigger != null ? String(d.trigger).trim() : "";
  const intent = d.intent != null ? String(d.intent).trim() : "";
  if (!ticker || !contract || !chain) return { code: 400, out: { ok: false, error: "ticker, contract and chain are required" } };
  if (!["A", "B"].includes(list_origin)) return { code: 400, out: { ok: false, error: "list_origin must be A or B" } };
  if (!TRIAGE_DECISIONS.has(decision)) return { code: 400, out: { ok: false, error: "unknown decision '" + decision + "'" } };
  if (!reason) return { code: 400, out: { ok: false, error: "a reason is required for every decision (this is training data)" } };
  if (TRIAGE_TRIGGER_REQUIRED.has(decision) && !trigger) return { code: 400, out: { ok: false, error: "this decision requires a named trigger (what has to happen)" } };
  if (decision === "buy_now" && !intent) return { code: 400, out: { ok: false, error: "buying-now requires the intent (levels / sizes / TPs) — it is captured, not executed" } };
  const meta = (d.meta && typeof d.meta === "object" && !Array.isArray(d.meta)) ? d.meta : {};
  const row = {
    time_utc: new Date().toISOString().replace(/\.\d+Z$/, "Z"),   // UTC to the second
    ticker, contract, chain, list_origin, decision, reason,
    ...(trigger ? { trigger } : {}),
    ...(intent ? { intent } : {}),
    meta: { price: meta.price ?? null, liq: meta.liq ?? null, vol24: meta.vol24 ?? null,
            ...(meta.name ? { name: String(meta.name) } : {}),
            ...(meta.pool ? { pool: String(meta.pool) } : {}),
            ...(meta.gtNetwork ? { gtNetwork: String(meta.gtNetwork) } : {}),
            ...(meta.thesis ? { thesis: String(meta.thesis).slice(0, 500) } : {}) },
  };
  await appendFile(join(HERE, TRIAGE_FILE), JSON.stringify(row) + "\n");
  const exclusions = await rebuildExclusions();
  return { code: 200, out: { ok: true, row, exclusionCounts: { blacklist: exclusions.blacklist.length, triaged: exclusions.triaged.length } } };
}

// ---------- Research queue (added 2026-07-21, CW-cockpit-round2) ----------
// "Add to Database" on the Suggested Plays cards: POST appends a request row to
// research-requests.jsonl; a Claude session fulfills the queue (runs the research,
// creates the Notion entry) and appends {ts, ticker, contract, chain, tier, notion_url}
// rows to research-results.jsonl. GET returns both files so the UI can show
// "research queued (Tier)" badges and the Notion link once a result lands.
// QUEUE-AND-DISPLAY ONLY: these routes never research, never trade, never write Notion.
const RESEARCH_REQ_FILE = "research-requests.jsonl";
const RESEARCH_RES_FILE = "research-results.jsonl";
const RESEARCH_TIERS = new Set(["Bronze", "Silver", "Gold"]);   // explicitly NOT Diamond (Jesse spec)
async function handleResearchPost(body) {
  let d;
  try { d = JSON.parse(body || "{}"); } catch { return { code: 400, out: { ok: false, error: "bad JSON" } }; }
  const ticker = String(d.ticker || "").trim();
  const contract = String(d.contract || "").trim();
  const chain = String(d.chain || "").trim();
  const tier = String(d.tier || "").trim();
  const source_list = String(d.source_list || "").trim();
  if (!ticker || !contract || !chain) return { code: 400, out: { ok: false, error: "ticker, contract and chain are required" } };
  if (!RESEARCH_TIERS.has(tier)) return { code: 400, out: { ok: false, error: "tier must be Bronze, Silver or Gold" } };
  if (!source_list) return { code: 400, out: { ok: false, error: "source_list is required (which card list the request came from)" } };
  const row = { ts: new Date().toISOString().replace(/\.\d+Z$/, "Z"), ticker, contract, chain, tier, source_list };
  await appendFile(join(HERE, RESEARCH_REQ_FILE), JSON.stringify(row) + "\n");
  return { code: 200, out: { ok: true, row } };
}

http.createServer(async (req, res) => {
  const [url, qs] = (req.url || "/").split("?");
  const params = new URLSearchParams(qs || "");
  try {
    if (url === "/api/state") {
      // ?fresh=1 → wait for a real rebuild (refresh button + first paint use it)
      const { data, stale, age, err } = await cached("state", buildState, { force: params.get("fresh") === "1" });
      return json(res, 200, { ...data, stale, ageMs: age, refreshError: err || null });
    }
    if (url === "/api/funding") {
      const { data, stale, age, err } = await cached("funding", runFundingCalc, { force: params.get("fresh") === "1" });
      return json(res, 200, { generated: new Date(cache.funding.at).toISOString(), stale, ageMs: age, refreshError: err || null, results: data });
    }
    if (url === "/api/feedback" && req.method === "POST") {
      try {
        const { text, context } = JSON.parse(await readBody(req) || "{}");
        if (!text || !String(text).trim()) return json(res, 400, { ok: false, error: "empty" });
        const entry = { time: new Date().toISOString(), source: "trading-dashboard", context: context || null, text: String(text).trim() };
        await appendFile(join(HERE, "feedback-log.jsonl"), JSON.stringify(entry) + "\n");
        return json(res, 200, { ok: true });
      } catch (e) { return json(res, 400, { ok: false, error: e.message }); }
    }
    // ---------- Execute Now page: persisted pasted-coin list (Jesse 2026-07-24) ----------
    // Write-limited: a small JSON list of {ticker, contract, chain} so the page survives
    // refresh. No execution surface; the vet gate + registry stay the only trade path.
    if (url === "/api/exec-coins" && req.method === "GET") {
      try { return json(res, 200, JSON.parse(await readFile(join(HERE, "exec-coins.json"), "utf8"))); }
      catch { return json(res, 200, { coins: [] }); }
    }
    if (url === "/api/exec-coins" && req.method === "POST") {
      try {
        const { coins } = JSON.parse(await readBody(req) || "{}");
        if (!Array.isArray(coins) || coins.length > 100) return json(res, 400, { ok: false, error: "coins must be an array (max 100)" });
        const clean = coins.filter(c => c && typeof c.contract === "string" && /^0x[0-9a-fA-F]{40}$/.test(c.contract))
          .map(c => ({ ticker: String(c.ticker || "?").slice(0, 20), contract: c.contract, chain: String(c.chain || "").slice(0, 20) }));
        await writeFile(join(HERE, "exec-coins.json"), JSON.stringify({ coins: clean }, null, 1));
        return json(res, 200, { ok: true, count: clean.length });
      } catch (e) { return json(res, 400, { ok: false, error: e.message }); }
    }
    // ---------- LIQUIDITY MATRIX + SIZING ENGINE (spec: proposals/LIQUIDITY-MATRIX-BUILD-SPEC.md
    // Part 2, Jesse-blessed 2026-07-28). Read-only on markets. Writes touch ONLY
    // risk-matrix.json (validated, timestamped .bak first) and risk-overrides.jsonl
    // (append-only override log). Suggest-never-clamp: nothing here gates, blocks or
    // resizes a trade — the numbers are display + prefill; every existing gate
    // (ARMED, registry, per-trade confirm, provisional $25 cap) is untouched. ----------
    if (url === "/api/risk-matrix" && req.method === "GET") {
      try {
        const { data } = await cached("state", buildState, {});
        const ctx = await riskContext(data);
        return json(res, 200, { ok: true, config: ctx.cfg, context: {
          tvl: ctx.tvl, ccm: ctx.ccm, portfolioValueUsd: ctx.portfolioValueUsd,
          dryPowderUsd: ctx.dryPowderUsd, basket: ctx.basketL } });
      } catch (e) { return json(res, 500, { ok: false, error: e.message }); }
    }
    if (url === "/api/risk-matrix" && req.method === "POST") {
      try {
        const saved = await saveMatrix(JSON.parse(await readBody(req) || "{}"));
        return json(res, 200, { ok: true, ...saved });
      } catch (e) { return json(res, e.code === "INVALID" ? 400 : 500, { ok: false, error: e.message }); }
    }
    if (url === "/api/risk-matrix/override" && req.method === "POST") {
      try {
        const d = JSON.parse(await readBody(req) || "{}");
        const out = await setTierOverride({ contract: d.contract, ticker: d.ticker, L: d.L == null ? null : Number(d.L) });
        return json(res, 200, { ok: true, ...out });
      } catch (e) { return json(res, 400, { ok: false, error: e.message }); }
    }
    if (url === "/api/risk-matrix/size" && req.method === "POST") {
      try {
        const d = JSON.parse(await readBody(req) || "{}");
        if (!Array.isArray(d.items) || !d.items.length || d.items.length > 200)
          return json(res, 400, { ok: false, error: "items must be a non-empty array (max 200)" });
        const { data } = await cached("state", buildState, {});
        return json(res, 200, { ok: true, ...(await sizeItems(d.items, data)) });
      } catch (e) { return json(res, 500, { ok: false, error: e.message }); }
    }
    // ---------- ladder take-profit rule (Jesse 2026-07-24: "when I do Ladder Designer, I
    // need it to give me options for take profit as well") ----------
    // Appends ONE fill-triggered TP rule to sentinel-rules.json: when a resting limit BUY
    // for (token, wallet) placed after `createdAfter` fills, the sentinel places the listed
    // TP SELLS sized off the ACTUAL fill (fracOfFill × filled qty). This is how TPs work on
    // buys that may never fill — no fill, no sell, ever. Authorization model preserved:
    // the ONLY caller is the Ladder Designer right after Jesse's own confirm press placed
    // the buys, and the rule is stamped that way. The sentinel remains SELLS-ONLY and
    // arm.mjs re-enforces registry + caps underneath. Validation is strict; anything off
    // is refused with the reason.
    if (url === "/api/sentinel-rule" && req.method === "POST") {
      try {
        const d = JSON.parse(await readBody(req) || "{}");
        const token = String(d.token || "").trim().toUpperCase();
        const wallet = String(d.wallet || "").trim();
        const lvls = Array.isArray(d.tpLevels) ? d.tpLevels : [];
        const reg = JSON.parse(await readFile(join(MODULE, "registry.json"), "utf8"));
        const regTok = (reg.tokens || reg)[token];
        if (!regTok || !regTok.contract) return json(res, 400, { ok: false, error: `$${token} is not in the verified registry — no TP rule without a registry row` });
        if (!wallet) return json(res, 400, { ok: false, error: "wallet is required" });
        if (!lvls.length || lvls.length > 12) return json(res, 400, { ok: false, error: "tpLevels must have 1-12 entries" });
        const clean = [];
        for (const l of lvls) {
          const price = Number(l.price), frac = Number(l.fracOfFill);
          if (!(price > 0) || !Number.isFinite(price)) return json(res, 400, { ok: false, error: "every TP needs a price > 0" });
          if (!(frac > 0 && frac <= 1)) return json(res, 400, { ok: false, error: "every TP fracOfFill must be between 0 and 1" });
          clean.push({ price, fracOfFill: Number(frac.toFixed(6)) });
        }
        const fracSum = clean.reduce((a, l) => a + l.fracOfFill, 0);
        if (fracSum > 1.0001) return json(res, 400, { ok: false, error: `TP fractions sum to ${(fracSum * 100).toFixed(1)}% of each fill — cannot sell more than 100%` });
        const now = new Date().toISOString();
        const rule = {
          id: `${token.toLowerCase()}-ladder-tps-${now.replace(/[:.]/g, "").slice(0, 15)}`,
          token, wallet, chain: regTok.chain || String(d.chain || "robinhood"),
          watch: "resting-limit-buys",
          createdAfter: now,
          approvedBy: `Jesse — Ladder Designer confirm press ${now} (TPs staged with the ladder he fired)`,
          tpLevels: clean,
          expiryHours: Math.min(Math.max(Number(d.expiryHours) || 2400, 1), 8760),
          enabled: true,
        };
        const rulesDoc = JSON.parse(await readFile(join(HERE, "sentinel-rules.json"), "utf8"));
        rulesDoc.rules = rulesDoc.rules || [];
        rulesDoc.rules.push(rule);
        await writeFile(join(HERE, "sentinel-rules.json"), JSON.stringify(rulesDoc, null, 2) + "\n");
        return json(res, 200, { ok: true, rule: { id: rule.id, token, wallet, levels: clean.length, moonbagPct: +((1 - fracSum) * 100).toFixed(1) } });
      } catch (e) { return json(res, 400, { ok: false, error: e.message }); }
    }
    // ---------- ladder-design capture (Jesse 2026-07-23) ----------
    // Every STAGED ladder is persisted — the numeric design (levels, $ per rung, % below
    // market, risk/size settings) to ladder-designs.jsonl + the design canvas as a PNG in
    // ladder-shots/ — so Jesse's level-picking patterns can be mined later. Write-limited:
    // appends a record and writes an image, no execution surface, no gates touched.
    if (url === "/api/ladder-design" && req.method === "POST") {
      try {
        const { record, png } = JSON.parse(await readBody(req, 4_000_000) || "{}");
        if (!record || !record.ticker || !Array.isArray(record.levels)) return json(res, 400, { ok: false, error: "record.ticker + record.levels[] required" });
        const t = new Date().toISOString();
        let shot = null;
        if (png && /^data:image\/png;base64,/.test(png)) {
          shot = `ladder-shots/${String(record.ticker).replace(/[^A-Za-z0-9_-]/g, "")}-${t.replace(/[:.]/g, "")}.png`;
          await mkdir(join(HERE, "ladder-shots"), { recursive: true });
          await writeFile(join(HERE, shot), Buffer.from(png.slice("data:image/png;base64,".length), "base64"));
        }
        await appendFile(join(HERE, "ladder-designs.jsonl"), JSON.stringify({ time: t, source: "ladder-designer", shot, ...record }) + "\n");
        return json(res, 200, { ok: true, shot });
      } catch (e) { return json(res, 400, { ok: false, error: e.message }); }
    }
    // ---------- trade-idea queue: DISABLED 2026-07-21 (armed-server hardening) ----------
    // This file-queue was written by an unowned session, was never reviewed, and was NOT
    // gated by the TRADE_IDEA_ARMED flag. Per Session A's flag (COWORK-LOG 14:55Z) and
    // Jesse's "one, arm it" decision, an armed server keeps zero unreviewed paths to
    // execution. The reviewed, token-gated /api/trade-idea/* engine below is canonical.
    // If a "ask Claude for deeper judgment" channel is wanted later, it gets rebuilt
    // deliberately per the roadmap — not re-enabled here.
    if ((url === "/api/trade-request" || url === "/trade-request") ||
        url === "/trade-requests" || url === "/api/trade-requests" ||
        url === "/trade-responses" || url === "/api/trade-responses") {
      return json(res, 410, { ok: false, error: "queue disabled 2026-07-21 (unreviewed path removed on arming) — use the Trade Idea panel (/api/trade-idea/*)" });
    }
    // ---------- ledger re-scan (READ-ONLY ingest so fresh trades get real basis) ----------
    if (url === "/api/ingest" && req.method === "POST") {
      if (ingest.running) return json(res, 202, { ok: true, running: true, note: "ingest already running" });
      if (Date.now() - ingest.lastAt < 300_000) return json(res, 429, { ok: false, error: "cooldown — last scan " + Math.round((Date.now() - ingest.lastAt) / 1000) + "s ago (5 min min)", last: ingest.lastResult });
      runIngest().catch(() => {});
      return json(res, 202, { ok: true, running: true, note: "ledger re-scan started (robinhood + base + solana, read-only)" });
    }
    if (url === "/api/ingest") {
      return json(res, 200, { running: ingest.running, last: ingest.lastResult });
    }
    // ---------- trade-idea engine (in-server execution path; namespaced /api/trade-idea/*) ----------
    // Distinct from the /api/trade-request file-queue above: these routes run the scenario
    // analysis and (on an explicit confirm token) invoke the module's arm.mjs/swap.mjs directly
    // via child_process and stream the real result back. DISARMED by default — every execution
    // is FORCED to dry-run unless the server was started with TRADE_IDEA_ARMED=1. See trade-idea.mjs.
    if (url === "/api/trade-idea/config") {
      return json(res, 200, tradeConfig());
    }
    if (url === "/api/trade-idea/analyze" && req.method === "POST") {
      try {
        const { positionKey, text, mode, context } = JSON.parse(await readBody(req) || "{}");
        const { data } = await cached("state", buildState);   // reuse the cached portfolio state
        const out = await analyzeIdea({ state: data, positionKey, text, mode: mode === "quick" ? "quick" : "normal", context });
        return json(res, out.ok ? 200 : 400, out);
      } catch (e) { return json(res, 400, { ok: false, error: e.message }); }
    }
    // READ-ONLY sentinel status (2026-07-22): rules, last tick, recent log — the UI
    // and Jesse can always see exactly what the sentinel is armed to do and has done.
    if (url === "/api/sentinel") {
      return json(res, 200, sentinelStatus());
    }
    // ---------- VET-LITE (2026-07-23, Jesse: "Auto-vet lite, capped buy") ----------
    // Mechanical scam screen for a Suggested-Plays quick buy on an unregistered token.
    // CLEAR → writes a PROVISIONAL registry row hard-capped at $25/order (vetlite.mjs;
    // backup written first). The full token-vetter agent still owns cap removal.
    // REFUSED/collision → returns the reasons, writes nothing. This route can never
    // execute a trade — the normal analyze → confirm → execute gates all still apply.
    if (url === "/api/vet-lite" && req.method === "POST") {
      try {
        const { ticker, contract, chain } = JSON.parse(await readBody(req) || "{}");
        const v = await vetLite({ ticker, contract, chain });
        if (v.verdict === "CLEAR") {
          const w = applyVetLiteRow(v.ticker, v.row);
          if (!w.ok) return json(res, 409, { ok: false, ...v, error: w.error });
          cache.state.at = 0;                       // fresh state so the new registry token shows
          return json(res, 200, { ok: true, ...v, written: true, backup: w.backup });
        }
        return json(res, v.verdict === "ALREADY" ? 200 : 422, { ok: v.verdict === "ALREADY", ...v, written: false });
      } catch (e) { return json(res, 400, { ok: false, error: e.message }); }
    }
    // ---------- BEST-EXECUTION ROUTE SCAN (READ-ONLY, added 2026-07-31) ----------
    // Jesse: "I need it to show me basically like a quick scan... I want people to really
    // know that they're getting the best price possible... scanned 56 pools for this token,
    // and these are your best routing options."
    //
    // swap.mjs has raced 1inch v6 vs KyberSwap since 2026-07-22 and executed the winner, but
    // printed the result to a console nobody sees. This surfaces the SAME work to the screen.
    //
    // CANNOT EXECUTE: no wallet, no signer, no approvals, no confirm token, no child process.
    // It reads registry.json, DexScreener, and the two aggregator QUOTE endpoints. Every
    // number it returns is live and click-through verifiable; failures are reported, never
    // padded. See route-scan.mjs for the integrity contract.
    if (url === "/api/route-scan" && req.method === "POST") {
      try {
        const { srcTicker, dstTicker, usd, qty } = JSON.parse(await readBody(req) || "{}");
        const { routeScan } = await import("./route-scan.mjs");
        const out = await routeScan({ srcTicker, dstTicker, usd, qty });
        return json(res, out.ok ? 200 : 422, out);
      } catch (e) { return json(res, 400, { ok: false, error: String(e?.message || e).slice(0, 200) }); }
    }
    // READ-ONLY execution progress for the UI loading bar (2026-07-22). Polled by the
    // client while its execute fetch is in flight. No side effects, in-memory only.
    if (url === "/api/trade-idea/progress") {
      const p = executeProgress(params.get("token"));
      return json(res, 200, p ? { ok: true, ...p } : { ok: false });
    }
    if (url === "/api/trade-idea/execute" && req.method === "POST") {
      try {
        const { confirmToken, dryRun, method } = JSON.parse(await readBody(req) || "{}");
        if (!confirmToken) return json(res, 400, { ok: false, error: "missing confirmToken (server refuses to execute without an explicit confirm token from the UI)" });
        const out = await executeConfirm({ confirmToken, dryRun, method });
        if (out.ok || out.results) cache.state.at = 0;   // force fresh state so a live fill/rest shows
        return json(res, out.ok ? 200 : 400, out);
      } catch (e) { return json(res, 400, { ok: false, error: e.message }); }
    }
    // ---------- POST-TRADE CONTEXT CAPTURE (write-limited; added 2026-07-22) ----------
    // Attaches "why did we make this trade" onto an existing trade-idea-log.jsonl row (or a
    // companion row if the target is gone). NO execution side effects: it never analyzes,
    // mints a token, or spawns arm/swap. See attachTradeContext() in trade-idea.mjs.
    if (url === "/api/trade-idea/context" && req.method === "POST") {
      try {
        const { logRef, context } = JSON.parse(await readBody(req) || "{}");
        const out = await attachTradeContext({ logRef, context });
        return json(res, out.ok ? 200 : 400, out);
      } catch (e) { return json(res, 400, { ok: false, error: e.message }); }
    }
    // ---------- PLAY-CANDIDATE QUEUE (write-limited; added 2026-07-22) ----------
    // Appends a Jesse-described candidate play (one_liner, or a detail row) to
    // doctrine/play-candidates.jsonl. Append-only; no other side effects. Agents later
    // research these into PLAYBOOKS.md drafts for Jesse's approval.
    if (url === "/api/play-candidate" && req.method === "POST") {
      try {
        const row = JSON.parse(await readBody(req) || "{}");
        const out = await appendPlayCandidate(row);
        return json(res, out.ok ? 200 : 400, out);
      } catch (e) { return json(res, 400, { ok: false, error: e.message }); }
    }
    // ---------- trade-idea call log (READ-ONLY; added 2026-07-22) ----------
    // Feeds the per-card history threads on the dashboard, replacing the dead-queue
    // polling. Parses trade-idea-log.jsonl (written by executeConfirm on every run,
    // live AND dry). Optional ?ticker=X filter, newest first. NO side effects: this
    // route reads a file and returns JSON, it cannot analyze, confirm, or execute.
    if (url === "/api/trade-idea/log") {
      const rows = await readJsonl("trade-idea-log.jsonl");
      const ticker = String(params.get("ticker") || "").trim().toUpperCase();
      const calls = (ticker ? rows.filter(r => String(r.ticker || "").toUpperCase() === ticker) : rows)
        .sort((a, b) => String(b.call_time || "").localeCompare(String(a.call_time || "")));
      return json(res, 200, { calls });
    }
    // ---------- Suggested Plays triage (append-only decision log + exclusions rebuild) ----------
    if (url === "/api/triage" && req.method === "POST") {
      try {
        const { code, out } = await handleTriagePost(await readBody(req));
        return json(res, code, out);
      } catch (e) { return json(res, 400, { ok: false, error: e.message }); }
    }
    if (url === "/api/triage") {
      return json(res, 200, { decisions: await readJsonl(TRIAGE_FILE) });
    }
    // ---------- research queue (Add to Database; queue-and-display only, see block above) ----------
    if (url === "/api/research-request" && req.method === "POST") {
      try {
        const { code, out } = await handleResearchPost(await readBody(req));
        return json(res, code, out);
      } catch (e) { return json(res, 400, { ok: false, error: e.message }); }
    }
    if (url === "/api/research-status") {
      return json(res, 200, {
        requests: await readJsonl(RESEARCH_REQ_FILE),
        results: await readJsonl(RESEARCH_RES_FILE),
      });
    }
    // ---------- GT candle proxy (read-only market data; cached + paced, see block above) ----------
    if (url === "/api/ohlcv") {
      // CEX branch (VENUES-ROADMAP Phase 3): network "coinbase" serves candles from
      // Coinbase itself (pool param = product id), GT-shaped so every chart consumer
      // (levels canvas, ladder designer, volatility read) works on CEX symbols unchanged.
      if (params.get("network") === "coinbase") {
        try {
          const { candles } = await import("../module/venues/coinbase.mjs");
          const tf = params.get("tf") || "hour", agg = Number(params.get("agg") || 1);
          const gran = tf === "minute" ? (agg >= 15 ? "FIFTEEN_MINUTE" : agg >= 5 ? "FIVE_MINUTE" : "ONE_MINUTE")
                     : tf === "hour" ? (agg >= 4 ? "FOUR_HOUR" : "ONE_HOUR") : "ONE_DAY";
          return json(res, 200, { ohlcv: await candles(params.get("pool"), gran, 300), source: "coinbase" });
        } catch (e) { return json(res, 200, { ohlcv: [], error: String(e.message).slice(0, 160) }); }
      }
      const { code, body } = await ohlcvProxy(params);
      return json(res, code, body);
    }
    // ---------- registry decoy contracts (READ-ONLY; added 2026-07-22) ----------
    // The card grid hides any position whose contract is in ANY registry token's decoys[]
    // array (belt-and-suspenders on top of the datasource's isDecoy flag). Flattened,
    // lowercased. Read a file, return JSON — no side effects.
    if (url === "/api/registry-decoys") {
      try {
        const reg = JSON.parse(await readFile(join(MODULE, "registry.json"), "utf8"));
        const toks = reg.tokens || reg;
        const set = new Set();
        for (const t of Object.values(toks)) if (t && Array.isArray(t.decoys)) for (const d of t.decoys) if (d) set.add(String(d).toLowerCase());
        return json(res, 200, { decoys: [...set] });
      } catch (e) { return json(res, 200, { decoys: [], error: e.message }); }
    }
    // ---------- static ----------
    const rel = url === "/" ? "dashboard.html" : url.replace(/^\/+/, "");
    const file = normalize(join(HERE, rel));
    const ext = extname(file);
    if (!file.startsWith(HERE) || !MIME[ext] || rel.includes("..") || /(^|\/)\./.test(rel)) {
      res.writeHead(403); return res.end("forbidden");
    }
    try {
      const data = await readFile(file);
      res.writeHead(200, { "Content-Type": MIME[ext], "Cache-Control": "no-store" });
      res.end(data);
    } catch { res.writeHead(404); res.end("not found"); }
  } catch (e) {
    json(res, 500, { error: e.message });
  }
}).listen(PORT, "127.0.0.1", () => {
  // Truthful armed-state banner (fix 2026-07-22): the old hardcoded "(read-only)" line
  // lied whenever the server was started with TRADE_IDEA_ARMED=1. Same check as trade-idea.mjs.
  const armed = process.env.TRADE_IDEA_ARMED === "1";
  console.log(armed
    ? `TRADING DASHBOARD [ARMED: live-capable, the Trade Idea path can place REAL orders after per-trade confirm] → http://127.0.0.1:${PORT}/`
    : `TRADING DASHBOARD [DISARMED: dry-run only, every execute is forced to preview, no real orders] → http://127.0.0.1:${PORT}/`);
  // warm both caches on boot so the first page load is instant-ish
  cached("state", buildState).catch(() => {});
  cached("funding", runFundingCalc).catch(() => {});
  // keep exclusions.json in sync with the triage log (holdings + dollarTrue + blacklist + triaged)
  rebuildExclusions().catch(e => console.error("[dashboard] exclusions rebuild failed:", e.message));

  // ---------- MOONBAG SENTINEL heartbeat (completed 2026-07-23) ----------
  // The 2026-07-22 sentinel build wired the /api/sentinel status route but never
  // called sentinelTick — this loop is what actually makes fill-triggered TP
  // top-ups happen. sentinelTick() can only SELL, only per the Jesse-pre-approved
  // rules in sentinel-rules.json, only while ARMED (disarmed = log-only); arm.mjs
  // re-enforces registry + $500 cap underneath. First tick ~45s after boot (lets
  // the state cache warm), then every 90s riding datasource's own orders cache —
  // no extra 1inch traffic. Busy-guard so a slow tick never overlaps itself.
  let sentinelBusy = false;
  async function sentinelPass(label) {
    if (sentinelBusy) return;
    sentinelBusy = true;
    try {
      const out = await sentinelTick(async () => (await cached("state", buildState)).data);
      if (out?.actions?.length) console.log(`[sentinel:${label}]`, JSON.stringify(out.actions));
    } catch (e) { console.error(`[sentinel:${label}] tick failed:`, e.message); }
    finally { sentinelBusy = false; }
  }
  setTimeout(() => sentinelPass("boot"), 45_000);
  setInterval(() => sentinelPass("beat"), 90_000);
});
