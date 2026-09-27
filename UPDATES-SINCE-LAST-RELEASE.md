# UPDATES SINCE LAST RELEASE — 2026-07-26 (v5.2) → 2026-07-31

**What this file is:** the focused delta between the PREVIOUS release and THIS
one, regenerated every release. If you (or your AI) already run the previous
build, this file is everything you need to look at — nothing else changed.
Coming from something older? Chain backwards through `CHANGELOG.md`. No
previous install at all? Ignore this file; run the setup agent
(`.claude/skills/setup/SKILL.md`) and do the full thing.

**How your AI should use it (the no-duplicate rule):**
1. Find the user's existing install and read its `VERSION` (no VERSION file =
   pre-2026-07-31; the old v-labels are all older than any dated build).
2. If none exists → full setup, ignore this file.
3. If one exists → UPGRADE mode only: `node module/upgrade.mjs /path/to/OLD`
   carries their keys/wallet/registry/ledgers; this file tells you which
   changed areas to re-read and what (if anything) the user must do by hand.
   Never re-run full setup over a working install, never duplicate their
   files, never re-add registry tokens they already have.
4. Mechanical diff: this build ships `RELEASE-MANIFEST.json` (file → sha256).
   From this release on, `upgrade.mjs` diffs the old install's manifest
   against the new one automatically and prints exactly which shipped files
   changed. (Installs older than 2026-07-31 have no manifest — use the list
   below instead.)

---

## NEW in this release (didn't exist in v5.2)

| What | Where | Why you care |
|---|---|---|
| **Setup agent v2** — SETUP / UPGRADE / DOCTOR modes, resumable, every step live-verified | `.claude/skills/setup/SKILL.md` | The front door. Point new users here; point broken installs at its DOCTOR mode. |
| **Version truth** | `VERSION` (root); doctor prints it line 2 | The version is the date. Ends v3-vs-v3.1 confusion permanently. |
| **Safe upgrades** | `module/upgrade.mjs`, `UPGRADING.md` | Never extract a zip over an install again. Carries wallet/.env/registry/ledgers old→new, dry-run first. |
| **This delta system** | `UPDATES-SINCE-LAST-RELEASE.md`, `RELEASE-MANIFEST.json` | You're reading it. |
| **Full research doctrine** | `doctrine/research/` (7 files), `Research/framework/00-how-we-think.md` | The author's actual research method, error log, source-quality map. Method, not advice. |
| **Trade-call agent** | `.claude/skills/trade-call/SKILL.md` + `doctrine/research/BUY-SELL-CALL-INSTRUCTIONS.md` | Authors the user's OWN buy/sell journal entries from their words. |
| **Best-execution route scan in the UI** | `cockpit/route-scan.mjs`, `cockpit/route-scan-ui.js` | Live pool census + fake-liquidity filter + both aggregators quoted, USD-first, before every trade button. |
| **⛽ ETH-spend switch** | `module/config.json` → `ethSpend`; registry ETH sentinel rows | Market orders can fund from native/wrapped ETH; limit orders deliberately refuse it. |
| **Production fix log ships** | `cockpit/FIXES-LOG.md` (redacted) | Nearly every failure mode, root cause, and verified fix. DOCTOR mode searches it. |
| **Chrome-first launcher** | `TRADING-DASHBOARD.command` | Opens the dashboard in Chrome when installed; your default browser stays yours. |

## CHANGED since v5.2 (behavior you may have memorized)

- **The $500/order cap is GONE from the shipped config** — `limits.maxUsdPerOrder`
  ships effectively unlimited. **USER ACTION: set a real number before arming.**
  The setup agent and README both walk to the exact line.
- **`BEST PRICE` button removed** (2026-07-31): it duplicated the limit-order
  path. Market execution is the single button; name a price and it's a limit.
- **Suggested lists relabeled A/B/C** and `suggested.html` rebuilt after a
  script regression (verified rendering). The three-list SPEC remains partly
  unbuilt — do not promise the ATH exclusion, PIVOT WATCH, or List-C loop.
- **Route-scan code consolidated** onto `route-scan-ui.js` — finding inline
  `.rs-*` CSS or a local `runRouteScan` body anywhere is a regression.
- **Quotes-are-not-fills** is now documented doctrine (14-swap measurement in
  `00-READ-THIS-FIRST-ADDITIONS.md` §4): the venue race compares quotes.

## USER ACTIONS on upgrade (the whole list)

1. Run the upgrade tool (`UPGRADING.md`) — do not hand-copy.
2. Set `limits.maxUsdPerOrder` to a real number (the old $500 default is gone).
3. If you want the new ETH-spend path: note your registry gains ETH sentinel
   rows via the upgrade report (add them if you carried your own registry).
4. `cd module && npm install && node doctor.mjs` — green criticals before trading.
