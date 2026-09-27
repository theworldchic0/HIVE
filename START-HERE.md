# 🐝 START HERE: from zero to a running Hive (about 20 minutes)

Written for Windows (it works the same on Mac: use the `.command` files instead of `.bat`).
You never paste a key into a chat, Claude included. Keys go into the terminal window the Hive
opens, and from there into a file on your own computer.

---

## 1. Install two free programs (one time)

| Program | Get it | Important |
|---|---|---|
| **Python 3.10+** | https://www.python.org/downloads/ | On the first installer screen, tick **"Add python.exe to PATH"** |
| **Node.js 20+ (LTS)** | https://nodejs.org | Default options are fine |

Check: open **Command Prompt** and type `python --version` and `node --version`. Both should print a
version number.

## 2. Get the folder onto your computer

On GitHub, open the repository, click **Code → Download ZIP**, and unzip it somewhere simple, for
example `C:\Users\<you>\HIVE`. (If you use git: `git clone` it, then `git checkout claude/stoic-euler-fem1cp`.)

## 3. Double-click `HIVE.bat`

The first time, a terminal window opens the **API key walkthrough** before anything else starts.
For each key it:

1. says what the key powers and what stops working without it
2. gives the exact steps to get it
3. waits for you to **paste it**. The key stays **hidden while you paste**, which is on purpose; just
   press Enter afterwards. (Paste with **right-click** in Command Prompt, or **Ctrl+V** in Windows
   Terminal.)
4. **tests it live** against the service that issued it (✓ works / ✗ rejected / • couldn't confirm)
5. saves it to `module\.env` on your computer and records a dated line in `SETUP-STATE.md`

Don't have a key yet? Type the word **`SKIP`** (in capitals). It's recorded, and the walkthrough
asks again only when you run it again.

### The keys, in the order you'll be asked

| # | Key | Level | Where to get it (free unless noted) | What it's for |
|---|---|---|---|---|
| 1 | **1inch API key** | REQUIRED | https://portal.1inch.dev → sign in → Applications → create app → copy key | Trader Bee quotes, swaps and take-profits; terminal execution |
| 2 | **Alchemy API key** | recommended | https://dashboard.alchemy.com → create app → **Base Mainnet** → copy the API key (not the whole URL) | terminal wallet tracking + a private Base RPC for the Trader Bee |
| 3 | **CoinGecko API key** | recommended | https://www.coingecko.com/en/api/pricing → free **Demo** plan → dashboard → Add New Key | Fib Bee candles + prices, terminal charts (Demo or Pro detected automatically) |
| 4 | Codex API key | optional | https://www.codex.io → dashboard → API keys | terminal momentum screens |
| 5 | Elfa API key | optional (paid credits) | https://www.elfa.ai → API access | social-signal probe |
| 6 | X bearer token | optional (pay-per-use) | https://developer.x.com → Project + App → Keys and tokens → Bearer Token | founder / social tracing |
| 7 | Anthropic API key | optional | https://console.anthropic.com → API Keys | lets the terminal parse dictation with Claude (sends the dictation text off your machine; leave it off if unsure) |
| 8 | Base RPC URL | optional | if you gave an Alchemy key, answer **Y** and it's built for you | faster, private Base connection |
| 9 | Robinhood RPC URL | optional | only if your provider offers Robinhood Chain (4663) | private Robinhood connection |

Elfa and X are only format-checked, not tested live, because those services bill per call.

After the keys, the walkthrough offers to:
- **install the trade executor** (`npm install`, about 30 seconds): answer **Y**
- **create the Trader Bee's own wallet**: type **YES** now, or later with `python trader.py wallet-new`

Then the Hive starts and your browser opens **http://127.0.0.1:8790**.

> Add, replace or re-test a key later: double-click **`HIVE-SETUP-KEYS.bat`**. It runs the walkthrough
> again (Enter keeps a key, `NEW` replaces it, `TEST` re-checks it) and then the **doctor**, a
> full ✓/✗ health check with the fix for anything wrong. The running Hive picks up new keys on its
> next loop, so you don't need to restart.

## 4. What you'll see (the Hive UI)

- **Bottom Blueprint** banner: where we are in the bottom window
- **Trader Bee**: mode (**PAPER** until you arm it), sizes, budget used, wallet and balances
- **Waiting for your approval**: parked buys and take-profit proposals, each with Approve / Decline
- **Positions / Decisions**: every buy it made or refused, with the reason
- **Research queue**: tokens the **Discovery Scout** found on Base + Robinhood (every 6h). These are
  candidates only and can't trade.
- **Fib Bee zone watch**: where each BUY/WATCH token sits between bottom and top
- **API keys**: set / skipped / missing (values are never shown)
- **Queen Bee**: every agent's health

## 5. Feed it research

Open Claude Code in this folder and type **`/nuk3r2 PONS`** (or `/nuk3r2 HOOKR | Robinhood Chain`, or
paste a contract). The **Research Bee** runs your whole Phase 1 method. It verifies the contract first
(and stops to ask you if there are look-alike tokens), then works through the gate, cycle, narrative,
Shiller /14, stage and curve, constellation, archetype, asset expression, liquidity, team, smart
money, Core /50, Timing /20 and the decision. You get the one-page report. Nothing is published until
you say so. Good places to start: the **Research queue** (the Discovery Scout's finds) and the **Meta
Radar** (what the market is trading now, daily / weekly / monthly). Once you publish:
- a **discovery** verdict that passes → the Trader Bee buys **$10 / $5 / $1** (high / medium / low confidence)
- every passing **BUY/WATCH** token → the Fib Bee watches it → **$1** when it enters the NUK3R2 buy zone

## 6. Paper first, then live (your decision, your hands only)

Let it run in **PAPER** for a few days and check its decisions. When you're ready:
1. `cd NUK3R2-Trader-Bee-Agent-v1.0.0\trader-bee`, then `python trader.py wallet` to see the address
2. Fund that address: **USDC on Base** / **USDG on Robinhood Chain** + about $1–2 of **ETH** for gas on each
3. Check the pinned router addresses (Trader Bee README, step 6)
4. Edit `config\trader_bee.json`: change `"mode": "paper"` to `"mode": "live"`
5. `python trader.py arm` and type the arm phrase

Stop any time: **DISARM** or **Pause** in the UI, or `python trader.py disarm`.

## If something's wrong

`python -m hive doctor` shows every check with its fix. Common ones:
- `'python' is not recognized` → reinstall Python with "Add python.exe to PATH" ticked (or use `py -3 -m hive start`)
- `Node.js not found` → install Node 20+ LTS, then double-click `HIVE-SETUP-KEYS.bat`
- 1inch `HTTP 401` → the key was copied wrong; `HIVE-SETUP-KEYS.bat` → `NEW`
