/* ROUTE SCAN UI — shared best-execution display for all three trade panels (2026-07-31).
 *
 * Jesse: "when I go to execute a trade, I need it to show me basically like a quick scan
 * because this has to be satisfying to use... I want people to really know that they're
 * getting the best price possible... scanned 56 pools for this token, and these are your best
 * routing options." Then: "I already understand the engine is done, but I need it to be shown
 * so people can see."
 *
 * swap.mjs has raced 1inch v6 vs KyberSwap and executed the winner since 2026-07-22, but the
 * result only ever reached a console. This renders the SAME work on screen, before the confirm
 * button, on dashboard.html, suggested.html and execute.html from one source of truth.
 *
 * INTEGRITY CONTRACT: every figure comes from POST /api/route-scan, which makes live calls to
 * DexScreener and both aggregators. The pool count is the real pair count. The quotes are real
 * quotes. A dead source renders as a failure, NEVER as a padded number. We never display a
 * scanned-pool count we did not actually scan — these zips ship to Jesse's boss and to members,
 * and a fabricated progress number would be a number that lies to them.
 *
 * PURELY ADDITIVE: never gates, alters, or triggers execution.
 *
 * Usage:  <script src="/route-scan-ui.js"></script>
 *         RouteScanUI.render(slotElement, analyzeResult);
 */
(function () {
  if (window.RouteScanUI) return;

  var CSS = `
  .rs{margin:10px 0 12px 0; padding:11px 13px; background:#0c1620; border:1px solid #2a4a6b; border-radius:10px;
      font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; color:#dfe8f1}
  .rs-h{display:flex; align-items:center; gap:9px; flex-wrap:wrap; font-size:12.5px; font-weight:800;
        letter-spacing:.03em; color:#7fd4a8; text-transform:uppercase}
  .rs-h .spin{width:12px; height:12px; border:2px solid #2a4a6b; border-top-color:#7fd4a8;
        border-radius:50%; animation:rsspin .7s linear infinite; display:inline-block}
  @keyframes rsspin{to{transform:rotate(360deg)}}
  .rs-big{font-size:19px; font-weight:800; color:#eef4fa; letter-spacing:-.3px; margin:6px 0 2px 0}
  .rs-big .n{color:#7fd4a8}
  .rs-sub{font-size:11.5px; color:#9db0c2; margin-bottom:8px}
  .rs-q{display:flex; gap:8px; flex-wrap:wrap; margin:7px 0}
  .rs-card{flex:1 1 165px; padding:7px 9px; border-radius:8px; background:#0f1a24; border:1px solid #26384a}
  .rs-card.win{border-color:#7fd4a8; background:#0e2018; box-shadow:0 0 0 1px rgba(127,212,168,.25) inset}
  .rs-card.fail{border-color:#6b3030; background:#1c1113}
  .rs-card .v{font-size:10.5px; text-transform:uppercase; letter-spacing:.06em; color:#9db0c2; font-weight:700}
  .rs-card .o{font-size:14.5px; font-weight:800; color:#eef4fa; font-variant-numeric:tabular-nums}
  .rs-card .m{font-size:10.5px; color:#9db0c2}
  .rs-card .badge{float:right; font-size:9.5px; font-weight:800; color:#0c1620; background:#7fd4a8;
        border-radius:4px; padding:1px 5px; letter-spacing:.05em}
  .rs-route{font-size:11.5px; color:#9db0c2; margin:6px 0 0 0; font-family:ui-monospace,Menlo,monospace}
  .rs-pools{margin-top:8px; border-top:1px solid #1e2e3d; padding-top:7px}
  .rs-pools table{width:100%; border-collapse:collapse; font-size:11px}
  .rs-pools td{padding:2px 5px 2px 0; color:#9db0c2; font-variant-numeric:tabular-nums}
  .rs-pools td.dx{color:#eef4fa; font-weight:700}
  .rs-pools a{color:#8ab8f5; text-decoration:none}
  .rs-pools a:hover{text-decoration:underline}
  .rs-toggle{background:none; border:none; color:#8ab8f5; font-size:11px; cursor:pointer; padding:0; margin-top:5px}
  .rs-note{font-size:10.5px; color:#6f7f8f; margin-top:7px; line-height:1.45}
  .rs-err{font-size:11.5px; color:#f9a}`;

  function injectCss() {
    if (document.getElementById("rs-ui-css")) return;
    var s = document.createElement("style");
    s.id = "rs-ui-css"; s.textContent = CSS;
    document.head.appendChild(s);
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function fmt(n, d) {
    return (n == null || !isFinite(n)) ? "—" : Number(n).toLocaleString(undefined, { maximumFractionDigits: d == null ? 2 : d });
  }

  async function render(slot, a) {
    if (!slot) return;
    injectCss();

    // Only DEX market swaps route through aggregators. NOTE: the server strips `argv` from the
    // client-facing leg and sends the human-readable `command` string instead, e.g.
    //   "node swap.mjs --src USDG --dst AI --usd 25 --slippage 1 --wallet wallet-2"
    // The first build read L.argv, found nothing, and silently never ran. Parse `command`.
    var cmdOf = function (L) { return String((L && (L.command || L.venue)) || ""); };
    var legs = (a && a.legs) || [];
    var leg = legs.filter(function (L) { return cmdOf(L).indexOf("swap.mjs") >= 0; })[0];

    if (!leg) {
      var anyCex = legs.some(function (L) { return cmdOf(L).indexOf("cex.mjs") >= 0; });
      var anyArm = legs.some(function (L) { return cmdOf(L).indexOf("arm.mjs") >= 0; });
      if (anyCex) slot.innerHTML = '<div class="rs"><div class="rs-h">Routing</div><div class="rs-sub">Coinbase order — routed by the exchange, so no on-chain pool race applies.</div></div>';
      else if (anyArm) slot.innerHTML = '<div class="rs"><div class="rs-h">Routing</div><div class="rs-sub">Resting limit order — it fills at your price on the book, so there is no aggregator race to run.</div></div>';
      return;
    }

    var parts = cmdOf(leg).trim().split(/\s+/);
    var gv = function (k) { var i = parts.indexOf(k); return (i >= 0 && i + 1 < parts.length) ? parts[i + 1] : null; };
    var src = gv("--src"), dst = gv("--dst");
    var usd = gv("--usd"), qty = gv("--qty"), qtyPct = gv("--qty-pct");

    // PERCENTAGE SELLS (2026-07-31 fix). "sell 50% now" ships as `--qty-pct 50`, which the
    // scanner cannot size by itself because it deliberately never reads a wallet balance.
    // The engine has ALREADY computed the exact token count into leg.tokens (and the dollar
    // value into leg.usd), so use those rather than telling Jesse "sell scan needs qty or usd".
    // He hit this on $GME with "sell 50% now" and got a red error where the scan should be.
    if (!qty && !usd) {
      if (qtyPct != null && leg.tokens != null) qty = String(leg.tokens);
      else if (leg.tokens != null) qty = String(leg.tokens);
      else if (leg.usd != null) usd = String(leg.usd);
    }
    if (!src || !dst) {
      slot.innerHTML = '<div class="rs"><div class="rs-h">Route scan</div><div class="rs-err">Could not read the swap pair from the plan, so no scan was run. The engine still races both venues at execution time.</div></div>';
      return;
    }

    slot.innerHTML = '<div class="rs"><div class="rs-h"><span class="spin"></span>Scanning liquidity…</div>' +
      '<div class="rs-sub">Counting every live pool for $' + esc(dst) + ' and racing both aggregators for the best price.</div></div>';

    var r;
    try {
      var resp = await fetch("/api/route-scan", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ srcTicker: src, dstTicker: dst, usd: usd != null ? Number(usd) : undefined, qty: qty || undefined })
      });
      r = await resp.json();
    } catch (e) {
      slot.innerHTML = '<div class="rs"><div class="rs-h">Route scan</div><div class="rs-err">Scan unavailable (' + esc(e.message) +
        '). This does not block the trade — the engine still races both venues at execution time.</div></div>';
      return;
    }
    if (!r || !r.ok) {
      slot.innerHTML = '<div class="rs"><div class="rs-h">Route scan</div><div class="rs-err">✖ ' + esc((r && r.error) || "no venue produced a quote") + '</div>' +
        '<div class="rs-note">Shown honestly rather than hidden. The engine will still race both venues when you execute.</div></div>';
      return;
    }

    var P = r.pools || {};
    // USD FIRST, token amount second (Jesse 2026-07-31: a quote shown only as "0.03421 SOL"
    // is unreadable — lead with the dollar value). Buys value the token at the live pool mid
    // the scan itself pulled, so it renders with ≈; sells pay the stable, shown as-is.
    var approx = r.usdIsEstimate ? "≈" : "";
    var cards = (r.quotes || []).map(function (q) {
      if (!q.ok) return '<div class="rs-card fail"><div class="v">' + esc(q.venue) + '</div><div class="m">no quote — ' + esc(q.error || "unavailable") + '</div></div>';
      var isWin = q.venue === r.winner;
      var big = (q.outUsd != null) ? approx + '$' + fmt(q.outUsd, 2) : fmt(q.out, 4);
      var sub = (q.outUsd != null)
        ? fmt(q.out, 4) + ' ' + esc(r.pair.dst) + ' out · ' + q.ms + 'ms'
        : esc(r.pair.dst) + ' out (no live pool price for a USD value) · ' + q.ms + 'ms';
      return '<div class="rs-card ' + (isWin ? "win" : "") + '"><div class="v">' + esc(q.venue) + (isWin ? '<span class="badge">BEST</span>' : '') + '</div>' +
        '<div class="o">' + big + '</div><div class="m">' + sub + '</div></div>';
    }).join("");

    var routeLine = "";
    var kq = (r.quotes || []).filter(function (q) { return q.venue === "kyber" && q.ok; })[0];
    if (r.winner === "kyber" && kq && kq.splits && kq.splits.length) {
      var path = kq.splits[0].map(function (h) { return h.exchange; }).join(" → ");
      routeLine = '<div class="rs-route">route: ' + kq.hopCount + ' hop' + (kq.hopCount === 1 ? "" : "s") + ' via ' + esc(path) +
        (kq.gasUsd != null ? ' · gas ≈ $' + fmt(kq.gasUsd, 4) : "") + '</div>';
    } else if (r.winner === "1inch") {
      var oq = (r.quotes || []).filter(function (q) { return q.venue === "1inch" && q.ok; })[0];
      if (oq && oq.protocols && oq.protocols.length) routeLine = '<div class="rs-route">route: ' + esc(oq.protocols.join(" → ")) + '</div>';
    }

    var edge = (r.edgePct != null && r.loser)
      ? '<b class="n">' + (r.edgePct > 0 ? "+" : "") + fmt(r.edgePct, 3) + '%</b> better than ' + esc(r.loser)
      : 'only venue that quoted';

    var poolRows = (P.top || []).map(function (t) {
      return '<tr><td class="dx">' + esc(t.dex) + '</td><td>$' + fmt(t.liqUsd, 0) + '</td>' +
        '<td>' + (t.vol24Usd != null ? "$" + fmt(t.vol24Usd, 0) + " 24h" : "") + '</td>' +
        '<td>' + (t.isRegistryMainPool ? "★ main" : "") + '</td>' +
        '<td>' + (t.url ? '<a href="' + esc(t.url) + '" target="_blank" rel="noopener">verify ↗</a>' : "") + '</td></tr>';
    }).join("");

    var failNote = (r.integrity && r.integrity.quotesFailed && r.integrity.quotesFailed.length)
      ? '<div class="rs-err">One venue did not answer: ' + r.integrity.quotesFailed.map(function (f) { return esc(f.venue) + " (" + esc(f.error) + ")"; }).join(", ") +
        '. The winner above is the best of what did.</div>' : "";

    var id = "rsP" + Math.random().toString(36).slice(2, 8);
    slot.innerHTML = '<div class="rs">' +
      '<div class="rs-h">✓ Best-execution scan complete <span style="color:#9db0c2;font-weight:600;text-transform:none;letter-spacing:0">' + r.elapsedMs + 'ms</span></div>' +
      '<div class="rs-big">Scanned <span class="n">' + (P.scanned != null ? P.scanned : "—") + '</span> pools across <span class="n">' + r.aggregatorsQueried + '</span> aggregators</div>' +
      '<div class="rs-sub">' + (P.counted != null ? P.counted + ' passed the fake-liquidity filter' : "") +
        (P.excludedAsSuspect ? ' · ' + P.excludedAsSuspect + ' excluded as suspect' : "") +
        (P.totalLiqUsd != null ? ' · $' + fmt(P.totalLiqUsd, 0) + ' real depth' : "") +
        ' · sizing ' + esc(r.sizeNote || "") + '</div>' +
      '<div class="rs-q">' + cards + '</div>' +
      '<div class="rs-sub">Routing you through <b style="color:#7fd4a8">' + esc(String(r.winner || "").toUpperCase()) + '</b> — ' + edge + '.</div>' +
      routeLine + failNote +
      '<button class="rs-toggle" data-rs="' + id + '">show the pools ▾</button>' +
      '<div class="rs-pools" id="' + id + '" style="display:none"><table><tbody>' + poolRows + '</tbody></table>' +
      '<div class="rs-note">' + esc((r.integrity && r.integrity.note) || "") + ' Scanned ' + esc(r.scannedAt || "") + '.</div></div></div>';

    var btn = slot.querySelector('[data-rs="' + id + '"]'), pl = slot.querySelector("#" + id);
    if (btn && pl) btn.addEventListener("click", function () {
      var open = pl.style.display !== "none";
      pl.style.display = open ? "none" : "block";
      btn.textContent = open ? "show the pools ▾" : "hide the pools ▴";
    });
  }

  window.RouteScanUI = { render: render };
})();
