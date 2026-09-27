# UPGRADING — without losing your keys, wallet, or history

**THE ONE RULE: never extract a new zip over your existing folder.** A blind
overwrite replaces your `wallet.key`, your `.env` API keys, your vetted
`registry.json`, your per-order cap in `config.json`, and your trade ledgers
with the blank shipped copies. People have done this. Don't be next.

Your files and the system's files live in the same tree — that's why the
upgrade is a tool, not a drag-and-drop.

## The safe path (10 minutes, your old install is never touched)

1. **Extract the new zip to a NEW folder** — e.g. next to the old one:
   `Altcoin-Trading-System-NEW/`. Do not put it inside the old folder.

2. **From inside the NEW folder, run the upgrade tool pointing at the OLD:**

   ```bash
   node module/upgrade.mjs /path/to/OLD/Altcoin-Trading-System
   ```

   That's a **dry-run** — it only prints what it would carry over: your
   wallet key, `.env`, registry, config, wallet lists, exclusions, sentinel
   rules, suggestion lists, ledgers, and `SETUP-STATE.md`. It also flags
   (a) rows/settings the NEW build ships that your carried files lack, and
   (b) any extra files you created that the new tree doesn't know about.

3. **Read the report. Then apply:**

   ```bash
   node module/upgrade.mjs /path/to/OLD/Altcoin-Trading-System --apply
   ```

4. **Swap folders yourself, deliberately:** rename the old folder to
   `Altcoin-Trading-System-OLD` (it is now your rollback), rename the new
   folder into place.

5. **Prove it before trusting it:**

   ```bash
   cd module && npm install && node doctor.mjs
   ```

   The doctor prints your installed version on line 2 and live-tests every
   key, both chains, the wallet, and the order-build path. Green across the
   criticals = upgraded. Anything red = fix it before trading (each red line
   prints its own fix).

6. Stop the old dashboard server and start the new one (double-click
   `TRADING-DASHBOARD.command`). It boots DISARMED, as always.

## Which version am I on?

`node module/doctor.mjs` — line 2. Or open the `VERSION` file in the install
root. No VERSION file at all = your build predates 2026-07-31; the labels
v1–v5.2 are all older than any dated build (full history inside `VERSION`).

## If you already overwrote your install

Your keys may be gone from the tree, but not from the providers: re-download
your API keys from each portal (they still exist in your accounts), and your
wallet still exists on-chain — restore `module/wallet.key` from wherever you
keep the private key. Re-vet and re-add your registry tokens. Then run the
doctor. If you kept ANY backup of the old folder, `upgrade.mjs` can pull from
it — point it at the backup.
