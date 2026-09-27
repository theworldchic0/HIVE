# SAFETY: the laws this system ships with

1. **DISARMED by default.** The launcher starts the dashboard preview-only. Real
   placement requires you to start it with `ARM=1`, every time. Arming is a human
   act; Claude never does it.
2. **Per-trade confirmation.** Armed or not, every order requires your explicit
   yes on that specific trade, at the plain-English confirmation card or the GO
   flag. Claude never executes on its own initiative.
3. **Registry gate.** The engine refuses any token without a verified row in
   `module/registry.json`. This is the scam-clone firewall. Add rows only after
   multi-source contract verification you have personally seen.
4. **Per-order USD cap.** `module/config.json` limits.maxUsdPerOrder ships at
   $500. Change it deliberately if you mean to; it is your throttle, and all
   three execution layers read this one value.
5. **Key hygiene.** Your private key lives in `module/wallet.key` (chmod 600) and
   your API keys in `module/.env`. They never appear in chat, never leave the
   machine, never get committed anywhere. Use a dedicated trading wallet holding
   only what you trade with.
6. **Dry-run first, always.** Every primitive previews before it can execute.
   Read the preview. The preview is the contract.
7. **Verify against reality.** A trade is done when the chain says so (tx hash,
   orderbook readback, dashboard fill), never because a tool printed no error.
8. **Sentinel scope.** The moonbag sentinel can ONLY place sells, ONLY per rules
   you wrote into `cockpit/sentinel-rules.json`, ONLY while the server is armed.
9. **Not investment advice.** This is execution tooling. You are responsible for
   what you trade, on chains where tokens can and do go to zero.

## Data-flow honesty (v5.1 additions, from community review)
- **Optional Claude parsing sends your dictation off-machine.** If you add
  `ANTHROPIC_API_KEY=` to `module/.env`, the Trade Idea panel sends the TEXT of each
  trade dictation to api.anthropic.com to parse it. Nothing else is sent — no keys, no
  balances — but the words themselves leave this machine. Leave the line empty (the
  default) and parsing stays 100% local. This is a conscious opt-in, never a default.
- **Token allowance is unlimited by design.** Resting ladders share one ERC-20 approval
  to the canonical 1inch router (an exact-amount approval would be consumed by the first
  fill and strand every deeper rung). This is the industry-standard tradeoff; the
  spender is pinned to 1inch's audited router, never a user-supplied address. To revoke
  at any time: revoke.cash, connect the trading wallet, revoke the router allowance.
- **The Coinbase venue module refuses orders without `{confirm:true}`** (and the CLI's
  `--confirm GO` remains on top). Importing the module can never fire an order by accident.

## The Trader Bee sandbox: the ONE scoped exception to law 2 (added 2026-09-27, beekeeper's request)
The beekeeper asked for a trading agent with **partial automation**: its own wallet, fixed small buys.
That is a deliberate, bounded exception to per-trade confirmation. It follows the same pattern as the
sentinel (pre-approved rules, armed only), and it applies ONLY inside these walls:
- **Own wallet only.** `NUK3R2-Trader-Bee-Agent-v1.0.0/trader-bee/secrets/agent_wallet.key`, created on
  this machine, funded by you with only what it may spend. It can never touch `module/wallet.key` or
  any other wallet.
- **Buys only, fixed sizes:** discovery $10 / $5 / $1 by research confidence, and $1 on a NUK3R2
  buy-zone entry. Sells and take-profits always need your per-trade approval.
- **Verified contracts only:** research identity VERIFIED by ≥2 independent sources, gate PASS, rank
  BUY/WATCH, plus live liquidity, security, price-impact and round-trip-sell gates.
- **Hard budgets** ($/24h, $/7d, buys/24h, $/asset) and a circuit breaker (3 failed live trades in a row
  pause it).
- **Paper by default.** Live requires `"mode": "live"` in its config AND `python trader.py arm` typed by
  you. **Arming is a human act. Claude never arms the Bee, never edits its sizes, budgets or gates,
  and never approves on your behalf.**
- **Stop any time:** `python trader.py disarm` / `pause`, or DISARM / Pause in the Hive UI.
Everything outside these walls stays under laws 1–9 above.
