// Hive UI — renders /api/hive every 10s. Every string that came from outside (token symbols,
// reasons, errors) goes through esc(): a token named "<img onerror=...>" must render as text.
"use strict";
const $ = (id) => document.getElementById(id);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const usd = (n, d = 2) => (n == null || !Number.isFinite(Number(n)) ? "—" : "$" + Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }));
const px = (n) => (n == null ? "—" : "$" + Number(n).toPrecision(5));
const ago = (iso) => {
  if (!iso) return "—";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 90) return Math.round(s) + "s ago";
  if (s < 5400) return Math.round(s / 60) + "m ago";
  if (s < 172800) return Math.round(s / 3600) + "h ago";
  return Math.round(s / 86400) + "d ago";
};
let STATE = null;
let POS_MODE = "live";

async function post(path, body = {}) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json", "X-Hive": "1" }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || "HTTP " + r.status);
  return j;
}

const STATE_PILL = {
  PAPER_FILLED: "ok", CONFIRMED: "ok", PAPER_PLACED: "ok", PLACED: "ok",
  NEEDS_APPROVAL: "honey", APPROVED: "honey", PLANNED: "", READY: "", SUBMITTING: "warn", SUBMITTED: "warn",
  REJECTED: "bad", FAILED: "bad", UNKNOWN: "warn", EXPIRED: "", DECLINED: "",
};

function renderBlueprint(b) {
  const el = $("blueprint");
  if (!b || !b.ok) { el.innerHTML = `<div class="warnbox">Bottom Blueprint unavailable: ${esc(b && b.error)}</div>`; return; }
  const c = b.clock, cy = b.cycle;
  const pct = c.bottom_window_total_days ? Math.min(100, (c.bottom_window_day / c.bottom_window_total_days) * 100) : 0;
  el.innerHTML = `
    <div class="stat"><small>Bottom Blueprint</small><b>${esc(c.state.replaceAll("_", " "))}</b><span class="sub">snapshot ${esc(b.snapshot_id)} · live out-of-sample test</span></div>
    <div class="stat"><small>Window day</small><b>${c.bottom_window_day} / ${c.bottom_window_total_days}</b><div class="meter"><i style="width:${pct}%"></i></div></div>
    <div class="stat"><small>To bottom center</small><b>${c.days_to_bottom_center}d</b><span class="sub">${esc(cy.bottom_center)} (${esc(cy.bottom_window_start)} → ${esc(cy.bottom_window_end)})</span></div>
    <div class="stat"><small>To momentum center</small><b>${c.days_to_momentum_center}d</b><span class="sub">${esc(cy.momentum_center)}</span></div>
    <div class="stat" style="max-width:320px"><small>Momentum rule</small><span class="sub">${esc(b.momentum_rule || "—")}</span></div>`;
}

function renderMD(m) {
  const miss = !m || !m.status || m.status === "MISSING";
  $("md").innerHTML = miss
    ? `<div class="empty">No snapshot published yet.<br><span class="sub">${esc(m && m.message)}</span></div>`
    : `<div class="row"><span class="pill ${m.status === "STALE" ? "bad" : "ok"}">${esc(m.status)}</span><b>${esc(m.regime || "")}</b></div>
       <p>${esc(m.final_call || m.final_signal || "")}</p><div class="sub">snapshot ${esc(m.snapshot_id)} · ${ago(m.generated_at)} · context only, never a trade trigger</div>`;
}

function renderTrader(t) {
  const btn = $("traderButtons"), stats = $("traderStats"), alert = $("traderAlert"), wallet = $("wallet");
  if (!t || !t.ok) {
    alert.innerHTML = `<div class="warnbox">Trader Bee unavailable: ${esc(t && t.error)}</div>`;
    btn.innerHTML = stats.innerHTML = wallet.innerHTML = "";
    $("modeBadge").innerHTML = "";
    return;
  }
  const live = t.effective_mode === "live";
  $("modeBadge").innerHTML = `<span class="pill ${live ? "live" : "paper"}">${live ? "LIVE · ARMED" : "PAPER"}</span>`;
  const paused = t.controls && t.controls.paused;
  btn.innerHTML = `${paused ? `<button class="go" data-act="resume">Resume</button>` : `<button data-act="pause">Pause (kill switch)</button>`}
    ${live ? `<button class="danger" data-act="disarm">DISARM</button>` : ""}`;
  let msg = "";
  if (paused) msg += `<div class="warnbox" style="margin-bottom:10px">PAUSED — ${esc(t.controls.paused_reason)}</div>`;
  if (t.config_mode === "live" && !live) msg += `<div class="warnbox" style="margin-bottom:10px">Config says live but the Bee is not armed${t.key_present ? "" : " and has no wallet"} — it is running in PAPER.</div>`;
  if (t.last_tick && t.last_tick.error) msg += `<div class="warnbox" style="margin-bottom:10px">Last tick error: ${esc(t.last_tick.error)}</div>`;
  alert.innerHTML = msg;
  const b = t.budget;
  const s = t.sizes;
  stats.innerHTML = `
    <div class="agent"><small class="sub">Discovery buys ${s.discovery_enabled ? "" : "(off)"}</small><div class="row" style="margin-top:4px">
      <span class="pill honey">high ${usd(s.discovery.high, 0)}</span><span class="pill honey">medium ${usd(s.discovery.medium, 0)}</span><span class="pill honey">low ${usd(s.discovery.low, 0)}</span></div></div>
    <div class="agent"><small class="sub">Zone entry ${s.zone_enabled ? "" : "(off)"}</small><div style="margin-top:4px"><span class="pill honey">${usd(s.zone_entry, 0)} on NUK3R2 buy-zone entry</span></div></div>
    <div class="agent"><small class="sub">Budget used (${esc(t.effective_mode)})</small>
      <div class="sub" style="margin-top:4px">24h ${usd(b.used_24h)} / ${usd(b.daily_usd, 0)} · ${b.buys_24h}/${b.max_buys_per_day} buys</div>
      <div class="meter"><i style="width:${Math.min(100, (b.used_24h / b.daily_usd) * 100)}%"></i></div>
      <div class="sub" style="margin-top:4px">7d ${usd(b.used_7d)} / ${usd(b.weekly_usd, 0)}</div>
      <div class="meter"><i style="width:${Math.min(100, (b.used_7d / b.weekly_usd) * 100)}%"></i></div></div>`;
  const bal = t.balances || {};
  const chains = Object.entries(bal).map(([ch, r]) => {
    if (!r || !r.ok) return `<div class="sub">${esc(ch)}: <span class="pill bad">unavailable</span> ${esc(r && r.error)}</div>`;
    const toks = Object.values(r.tokens || {}).map((x) => `${Number(x.amount).toLocaleString("en-US", { maximumFractionDigits: 4 })} ${esc(x.symbol)}`).join(" · ");
    return `<div class="sub">${esc(ch)}: ${toks || "—"} · ${Number(r.native).toFixed(5)} ETH gas</div>`;
  }).join("");
  wallet.innerHTML = `<small class="sub">Trader Bee wallet (fund with USDC on Base / USDG on Robinhood + a little ETH for gas)</small>
    <div style="margin:6px 0">${t.wallet_address ? `<span class="addr">${esc(t.wallet_address)}</span>` : `<span class="sub">No wallet yet — run <span class="mono">python trader.py wallet-new</span></span>`}</div>
    ${chains || `<div class="sub">balances refresh every few minutes while the Bee runs</div>`}
    <div class="sub" style="margin-top:6px">last tick ${ago(t.last_tick && t.last_tick.at)} · ${esc(JSON.stringify(t.counts))}</div>`;
}

function checksLine(it) {
  const g = it.gates || {}, c = g.checks || {}, m = c.market || {}, q = it.quote || {};
  const parts = [];
  if (m.liquidity_usd != null) parts.push(`liq ${usd(m.liquidity_usd, 0)}`);
  if (m.pair_age_hours != null) parts.push(`pair age ${m.pair_age_hours}h`);
  if (q.impact_pct != null) parts.push(`impact ${q.impact_pct}%`);
  if (q.roundtrip_loss_pct != null) parts.push(`round-trip loss ${q.roundtrip_loss_pct}%`);
  if (q.winner) parts.push(`best venue ${esc(q.winner)}`);
  return parts.join(" · ");
}

function renderApprovals(t) {
  const el = $("approvals");
  const rows = (t && t.ok && t.approvals) || [];
  if (!rows.length) { el.innerHTML = `<div class="empty">Nothing waiting. Soft-flagged buys and take-profit proposals land here.</div>`; return; }
  el.innerHTML = rows.map((it) => {
    const tp = it.strategy === "take_profit";
    const what = tp
      ? `SELL ${Number(it.trigger.qty).toPrecision(6)} ${esc(it.symbol)} at ${px(it.trigger.limit_price_usd)} (resting 1inch limit, ≈${usd(it.usd)})`
      : `BUY ${usd(it.usd)} of ${esc(it.symbol)} · ${esc(it.strategy.replace("_", " "))}${it.tier ? " · " + esc(it.tier) : ""}`;
    return `<div class="approval"><div class="row" style="justify-content:space-between"><b>${what}</b><span class="pill ${it.mode === "live" ? "live" : "paper"}">${esc(it.mode)}</span></div>
      <div class="reason">${esc(it.reason)}</div><div class="sub">${esc(it.chain)} · <span class="mono">${esc(it.contract)}</span></div>
      <div class="sub">${checksLine(it)}</div>
      <div class="row"><button class="go" data-approve="${esc(it.id)}">Approve this ${tp ? "take-profit" : "buy"}</button><button data-decline="${esc(it.id)}">Decline</button>
      <span class="sub">${tp ? "" : "hard gates re-run before it executes"}</span></div></div>`;
  }).join("");
}

function renderPositions(t) {
  const rows = (t && t.ok && t.positions && t.positions[POS_MODE]) || [];
  if (!rows.length) { $("positions").innerHTML = `<div class="empty">No ${POS_MODE} positions.</div>`; return; }
  $("positions").innerHTML = `<table><thead><tr><th>Token</th><th>Chain</th><th class="num">Cost</th><th class="num">Tokens</th><th class="num">Mark</th><th class="num">Value</th><th class="num">P&amp;L</th><th>Buys</th></tr></thead><tbody>${
    rows.map((p) => `<tr><td><b>${esc(p.symbol)}</b><div class="sub mono">${esc(p.contract).slice(0, 10)}…</div></td><td>${esc(p.chain)}</td>
      <td class="num">${usd(p.cost)}</td><td class="num">${Number(p.tokens_net).toPrecision(6)}</td><td class="num">${px(p.mark_usd)}<div class="sub">${ago(p.marked_at)}</div></td>
      <td class="num">${usd(p.value_usd)}</td><td class="num" style="color:${p.pnl_usd == null ? "inherit" : p.pnl_usd >= 0 ? "var(--green)" : "var(--red)"}">${p.pnl_usd == null ? "—" : (p.pnl_usd >= 0 ? "+" : "") + usd(p.pnl_usd)}</td><td>${p.buys}</td></tr>`).join("")
  }</tbody></table>`;
}

function renderIntents(t) {
  const rows = ((t && t.ok && t.recent) || []).filter((x) => x.strategy !== "take_profit" || x.state !== "NEEDS_APPROVAL");
  if (!rows.length) { $("intents").innerHTML = `<div class="empty">No decisions yet. The Bee acts on research verdicts (discovery tiers) and Fib zone entries.</div>`; return; }
  $("intents").innerHTML = `<table><thead><tr><th>When</th><th>Token</th><th>Why</th><th class="num">Size</th><th>Mode</th><th>State</th><th>Detail</th></tr></thead><tbody>${
    rows.map((it) => `<tr><td class="sub">${ago(it.created_at_iso)}</td><td><b>${esc(it.symbol)}</b><div class="sub">${esc(it.chain)}</div></td>
      <td>${esc(it.strategy.replace("_", " "))}${it.tier && it.tier !== "zone" ? `<div class="sub">${esc(it.tier)} confidence</div>` : ""}</td>
      <td class="num">${usd(it.usd)}</td><td><span class="pill ${it.mode === "live" ? "live" : "paper"}">${esc(it.mode)}</span></td>
      <td><span class="pill ${STATE_PILL[it.state] || ""}">${esc(it.state)}</span></td>
      <td class="reason">${esc(it.reason || "")}${it.tx_hash ? `<div class="mono">${esc(it.tx_hash).slice(0, 18)}…</div>` : ""}<div>${checksLine(it)}</div></td></tr>`).join("")
  }</tbody></table>`;
}

function renderFib(f) {
  $("fibCount").textContent = f ? `(${f.watching} watching)` : "";
  const rows = (f && f.rows) || [];
  if (!rows.length) { $("fib").innerHTML = `<div class="empty">Watchlist is empty. Gate-PASS research verdicts ranked BUY or WATCH are watched automatically.</div>`; return; }
  $("fib").innerHTML = `<table><thead><tr><th>Token</th><th>Rank</th><th>Status</th><th>Zone</th><th style="min-width:170px">bottom ← position → top</th><th class="num">Price</th><th>Checked</th></tr></thead><tbody>${
    rows.map((r) => {
      const pct = r.percent == null ? null : Math.max(0, Math.min(100, r.percent));
      return `<tr><td><b>${esc(r.symbol)}</b><div class="sub">${esc(r.chain)}</div></td><td>${esc(r.rank)}</td>
      <td><span class="pill ${r.status === "ACTIVE" ? "ok" : r.status === "DATA_ERROR" || r.status === "BROKEN" ? "bad" : "warn"}">${esc(r.status || "pending")}</span>${r.reason ? `<div class="reason">${esc(r.reason)}</div>` : ""}</td>
      <td>${r.zone ? `<span class="pill ${r.in_buy_zone ? "ok" : ""}">${esc(r.zone)}${r.in_buy_zone ? " · BUY ZONE" : ""}</span>` : "—"}<div class="sub">${r.percent == null ? "" : Number(r.percent).toFixed(1) + "%"}</div></td>
      <td>${pct == null ? "" : `<div class="zbar" title="100% = bottom (left), 0% = top (right)"><span class="buy"></span><span class="sell"></span><span class="mark" style="left:calc(${100 - pct}% - 1px)"></span></div>`}</td>
      <td class="num">${px(r.price)}</td><td class="sub">${ago(r.checked_at)}</td></tr>`;
    }).join("")
  }</tbody></table>`;
}

function renderQueen(q) {
  const agents = (q && q.agents) || [];
  $("agents").innerHTML = agents.length ? agents.map((a) => `<div class="agent"><div class="name"><span class="dot ${a.status === "green" ? "green" : a.status === "red" ? "red" : a.last_heartbeat_age_s > 1e8 ? "grey" : "yellow"}"></span>${esc(a.display_name)}</div>
      <div class="sub">${a.last_heartbeat_age_s > 1e8 ? "no heartbeat yet" : "heartbeat " + Math.round(a.last_heartbeat_age_s) + "s ago"} · ok ${a.jobs_completed} · fail ${a.jobs_failed}</div>
      ${a.last_error ? `<div class="reason">${esc(a.last_error)}</div>` : ""}</div>`).join("")
    : `<div class="warnbox">Queen unavailable ${esc(q && q.error)}</div>`;
  const recs = (q && q.recommendations) || [];
  $("recs").innerHTML = recs.map((r) => `<div class="sub"><span class="pill ${r.severity === "high" ? "bad" : r.severity === "medium" ? "warn" : ""}">${esc(r.severity)}</span> ${esc(r.recommendation)}</div>`).join("");
}

function renderEvents(evs) {
  $("events").innerHTML = (evs || []).map((e) => {
    const p = e.payload || {};
    const what = p.symbol ? `${p.symbol}${p.state ? " · " + p.state : ""}${p.zone ? " · " + p.zone : ""}${p.rank ? " · " + p.rank : ""}` : (p.command || p.reason || "");
    return `<div><span class="sub">${esc(e.ts.slice(5, 16).replace("T", " "))}</span> <b>${esc(e.type)}</b> <span class="sub">${esc(e.source)}</span> ${esc(what)}</div>`;
  }).join("") || `<div class="empty">No events yet.</div>`;
}

function renderSetup(st) {
  const el = $("setupPanel");
  if (!st) { el.hidden = true; return; }
  const need = st.missing_required || [];
  el.hidden = !(need.length || st.undecided);
  el.innerHTML = need.length
    ? `<div class="warnbox"><b>Setup not finished:</b> ${need.map(esc).join(", ")} missing. Double-click <span class="mono">HIVE-SETUP-KEYS</span> in the Hive folder (or run <span class="mono">python -m hive setup</span>) — it walks you through each key, tests it live, and the Hive picks it up on the next loop.</div>`
    : `<div class="sub">${st.undecided} optional key(s) not decided yet — run <span class="mono">python -m hive setup</span> when you want to add or SKIP them.</div>`;
  $("keys").innerHTML = `<table><thead><tr><th>Key</th><th>Level</th><th>Status</th><th>Stored in</th><th>Recorded</th></tr></thead><tbody>${
    (st.keys || []).map((k) => `<tr><td><b>${esc(k.title)}</b><div class="sub mono">${esc(k.name)}</div></td><td>${esc(k.level)}</td>
      <td>${k.set ? `<span class="pill ok">set</span> <span class="mono sub">${esc(k.masked)}</span>` : k.decision === "SKIPPED" ? `<span class="pill">skipped</span>` : `<span class="pill ${k.level === "required" ? "bad" : "warn"}">not set</span>`}</td>
      <td class="mono sub">${esc(k.file)}</td><td class="sub">${esc(k.decision || "—")} ${esc(k.decided_at || "")}</td></tr>`).join("")
  }</tbody></table><div class="sub" style="margin-top:8px">Add / replace / re-test: <span class="mono">python -m hive setup</span> · health check: <span class="mono">python -m hive doctor</span></div>`;
}

function renderScout(sc) {
  const rows = (sc && sc.queued) || [];
  $("scoutCount").textContent = sc ? `(${sc.queued_count} queued · ${sc.total_seen} seen)` : "";
  if (!rows.length) { $("scout").innerHTML = `<div class="empty">Queue empty. The scout scans every 6 hours while the Hive runs.</div>`; return; }
  $("scout").innerHTML = `<table><thead><tr><th>Token</th><th class="num">Score</th><th class="num">Liquidity</th><th class="num">24h vol</th><th class="num">Buys/Sells</th><th class="num">Age</th><th>Why surfaced</th></tr></thead><tbody>${
    rows.map((r) => { const o = r.observed || {}; return `<tr><td><b>${esc(r.symbol)}</b><div class="sub">${esc(r.chain)} · <span class="mono">${esc(r.contract)}</span></div></td>
      <td class="num">${esc(r.scout_score)}</td><td class="num">${usd(o.liquidity_usd, 0)}</td><td class="num">${usd(o.volume_24h_usd, 0)}</td>
      <td class="num">${esc(o.buys_24h)}/${esc(o.sells_24h)}</td><td class="num">${o.pool_age_hours == null ? "—" : Math.round(o.pool_age_hours / 24) + "d"}</td>
      <td class="reason">${(r.reasons || []).map(esc).join(" · ")}</td></tr>`; }).join("")
  }</tbody></table>`;
}

async function refresh() {
  try {
    const r = await fetch("/api/hive", { cache: "no-store" });
    STATE = await r.json();
    renderBlueprint(STATE.blueprint);
    renderMD(STATE.market_direction);
    renderTrader(STATE.trader);
    renderApprovals(STATE.trader);
    renderPositions(STATE.trader);
    renderIntents(STATE.trader);
    renderFib(STATE.fib);
    renderQueen(STATE.queen);
    renderEvents(STATE.events);
    renderSetup(STATE.setup);
    renderScout(STATE.scout);
    $("refreshed").textContent = "updated " + new Date().toLocaleTimeString();
  } catch (e) {
    $("refreshed").textContent = "Hive UI server unreachable — " + e.message;
  }
}

document.addEventListener("click", async (ev) => {
  const t = ev.target.closest("button");
  if (!t) return;
  try {
    if (t.dataset.m) {
      POS_MODE = t.dataset.m;
      document.querySelectorAll("#posTabs button").forEach((b) => b.classList.toggle("on", b === t));
      renderPositions(STATE && STATE.trader);
      return;
    }
    if (t.dataset.act === "pause") {
      const reason = prompt("Pause the Trader Bee. Reason (optional):", "beekeeper kill switch");
      if (reason === null) return;
      await post("/api/trader/pause", { reason });
    } else if (t.dataset.act === "resume") {
      if (!confirm("Resume the Trader Bee? It will continue buying within its budgets.")) return;
      await post("/api/trader/resume");
    } else if (t.dataset.act === "disarm") {
      if (!confirm("DISARM live trading now? The Bee drops to paper mode until you re-arm from the CLI.")) return;
      await post("/api/trader/disarm");
    } else if (t.dataset.approve) {
      const it = ((STATE.trader && STATE.trader.approvals) || []).find((x) => x.id === t.dataset.approve);
      const what = it ? (it.strategy === "take_profit" ? `place a ${it.mode} take-profit on ${it.symbol}` : `buy ${usd(it.usd)} of ${it.symbol} (${it.mode})`) : "this trade";
      if (!confirm(`Approve: ${what}?\n\nThis is your per-trade confirmation.`)) return;
      await post("/api/trader/approve", { id: t.dataset.approve });
    } else if (t.dataset.decline) {
      await post("/api/trader/decline", { id: t.dataset.decline });
    } else return;
    await refresh();
  } catch (e) {
    alert("Failed: " + e.message);
  }
});

refresh();
setInterval(refresh, 10_000);
