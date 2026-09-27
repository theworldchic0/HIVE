# Suggested Lists Spec (Jesse, 2026-07-31)

**Status: SPEC ONLY. Approved by Jesse, NOT built yet.** He explicitly said he does not want anything
built right now. This file exists so the decisions are not lost.

**This supersedes the old A/B/C/D list scheme** (the 2026-07-23 restructure where old A became List B,
old B became List C, and a new tokenized-stock list took slot A). Clean slate, three lists.

---

## THE THREE LISTS

### LIST A: Momentum right now
**Screen: up over 100% in the last 24 hours.** That is the whole rule. Simple on purpose.

### LIST B: 30-day momentum
**Screen: up at least 100% in the last 30 days.** Does NOT need to be up in the last 24 hours.

### LIST C: Research-match, no momentum requirement
Purely coins that match the CoinPicks research system. Jesse's words: "projects that you think I would
like from an overall perspective."

**Mechanical filters:**
- Good team
- **Liquidity between $80,000 and $3,100,000**

**Qualitative signals he named as examples:**
- A new launchpad with a founder who used to do something good
- A token that has NOT had good price appreciation, but the team has been promising for a while and has
  recently discussed on their Twitter connecting their token to the revenue of the company in a better way
- A viral product
- A product that has never been done before
- A concept that has never been done before, his example: pairing tokenized stocks against meme coins

**Jesse's framing:** "pretty much anything. We talk a lot about things that excite us."

---

## FRESHNESS AND CACHING

- **5-minute server-side cache.** Plain English: the server does the screening work once and keeps the
  answer for 5 minutes, so opening the page ten times in a row costs one screen instead of ten. After 5
  minutes the next visitor triggers a fresh screen.
- **Visible age stamp** on the page, e.g. "refreshed 2 minutes ago."
- **Force refresh button** that ignores the cache and re-screens immediately.
- Precedent to copy: `dashboard-server.mjs` already has a stale-while-revalidate cache with a `force=true`
  path, commented "every time I press refresh, it should refresh."

---

## THE 98.2% EXCLUSION

- **Measured from ALL-TIME HIGH.** Jesse confirmed.
- **Threshold: 98.2%** (Jesse revised from 98% on 2026-07-31). Anything down more than 98.2% from its
  ATH is excluded from the suggested lists.
- **CARVE-OUT, mandatory:** the filter applies to the SUGGESTED lists only. **Anything Jesse holds, or
  anything saved to the buy list, is never filtered out regardless of drawdown.** SPACEHOOD is the test
  case: it crashed, he still holds a position, and it must stay visible on his dashboard.
- Implementation note: key the carve-out off **live wallet balances** so it is automatic and never needs a
  hand-maintained whitelist.
- Data gap: token records currently carry `change_1h/6h/24h/7d_pct`, price, liquidity, holders and
  `pool_count`, but **no ATH or drawdown field**. This needs a new computed field per token.

---

## ⚠️ TWO CONFLICTS FOR JESSE TO RULE ON

### 1. RESOLVED: the dead-cat problem

Jesse, 2026-07-31: "if it's a dead cat bounce, we don't want it unless the project pivoted. So I don't
know, what should we do? Because I don't want tokens that are dead and just doing a dead cat bounce."

**Agreed solution: do NOT make it a binary include/exclude. Add a third bucket.**

A token down more than 98.2% from ATH is excluded from Lists A, B and C **unless it passes all three
persistence gates below**, in which case it goes to a separate **PIVOT WATCH** tray for Jesse to review
rather than appearing as a normal suggestion.

**The three persistence gates. A dead cat fails these; a real pivot passes them.**

| Gate | Test | Why it separates them |
|---|---|---|
| **Volume persistence** | 7-day average volume must exceed the prior 30-day average | A dead cat is a one or two day volume spike that collapses. A real recovery keeps trading. |
| **Holder growth** | Holder count up over 30 days | Dead cats do not gain holders. Recoveries do. Holder delta is the hardest signal to fake cheaply. |
| **Liquidity growth** | Liquidity up over 30 days | Someone ADDING liquidity is a commitment. Dead cats bounce on thin, shrinking liquidity. |

**Why a third bucket instead of a filter:** a silent exclude means a genuine pivot gets deleted and Jesse
never sees it. A silent include means dead cats pollute the momentum lists, which is the thing he
complained about. The tray gives him the handful of real candidates without the noise.

**The pivot signal that is NOT mechanical:** an actual pivot has a dated announcement. So any token that
reaches PIVOT WATCH should get a `twitter-alpha` pass to answer "did the team announce something, and
when." That is the difference between "the chart bounced" and "the project changed." Agent work, not a
code screen.

### 2. List C cannot be live-refreshed by code
Lists A and B are pure numeric screens, so a 5-minute server cache works perfectly. **List C is not
mechanically screenable.** "Good team," founder pedigree, Twitter statements about connecting tokens to
revenue, and "a concept never done before" all require judgment, which means an agent run, not a code
screen.

Realistic split:
- **A and B: live, 5-minute cache, refresh button works as described.**
- **C: rebuilt by an agent on a schedule (daily is realistic), with its own age stamp.** The refresh button
  on List C would queue an agent run rather than return instantly.

The relevant existing agents: `suggestions-refresher`, `playbook-matchmaker`, `twitter-alpha`,
`token-vetter`. The mechanical part of C (the $80K to $3.1M liquidity band) can be screened live; the
qualitative layer sits on top of it.

**This is a real architectural limit, not a shortcut. Do not promise Jesse a live List C.**

---

## ALSO AGREED: THE POOL SCAN (separate feature, same session)

Real numbers only, no theater. Jesse: "I like that. Yes, I like the real version, being able to click
through and check it."

What can be shown honestly today:
- **True pool count per token** from DexScreener (the suggested data already carries `pool_count`).
- **The actual winning route** from KyberSwap's `routeSummary`, which returns hops and pool addresses.
- **Protocols used** from 1inch v6.
- **The venue race result**, since `swap.mjs` already quotes both 1inch and Kyber and executes the winner,
  so the "X% better than the loser" figure is already computed and real.

Example honest display: "Scanned 14 pools across 2 aggregators. Best route: Kyber, 2 hops, USDG to WETH to
AI. 0.30% better than 1inch."

**Never display a scanned-pool count we did not actually scan.** These zips ship to Jesse's boss and to
members, and a fabricated progress number would be a number that lies to them.


---

## LIST C AS A LEARNING SYSTEM (Jesse, 2026-07-31)

His words: "list C is really going to be the most important one as far as me giving input. Because also,
list C is going to help us create a database of what I'm looking for and what I'm not looking for."

He wants to press yes or no on each List C candidate and attach a reason, "either 'not this one' or 'yes,
this one'," and he wants the freedom to give "a one-sentence reason or a whole paragraph of reasons, like
depending on what I see in the moment." Then: "over time, it should get smarter."

### THE DESIGN: three layers, and only the first one has to be perfect

**LAYER 1: CAPTURE. This is the actual asset.**
Every decision appends one row to `list-c-decisions.jsonl`:
- verdict (yes / no)
- **Jesse's verbatim reason, any length, never summarised or cleaned up**
- **the token's COMPLETE metric snapshot at decision time**, not just the ticker: price, liquidity,
  volume, holders, age, chain, pool count, all change windows, ATH drawdown, team findings, contract
- timestamp, and which list surfaced it

**The critical detail most people get wrong: snapshot the full feature vector at decision time.** If we
only store "no, anonymous team," we can never learn from it later, because by then the token's metrics have
moved. The snapshot is what makes the log trainable instead of just readable.

Even if layers 2 and 3 are never built, this alone delivers exactly what he described: a database of what
he is looking for and what he is not.

**LAYER 2: RULE EXTRACTION, with his approval. This is the "gets smarter" part.**
Periodically an agent reads the decision log and proposes **explicit, readable rules**, for example:
- "Anonymous team appears in 11 of your 14 rejections. Propose: hard exclude."
- "Founder previously shipped a real product appears in 6 of your 9 approvals. Propose: positive weight."
- "You rejected 4 tokens with liquidity under $80K even though they matched everything else. Propose:
  raise the floor."

**Jesse approves or rejects each proposed rule.** Approved rules land in a versioned
`list-c-rules.json` that he can read and edit by hand.

**Why proposed rules and not a score model:** he can audit it, it cannot silently drift, every suggestion
can explain itself, and it works from the very first decisions instead of needing hundreds. It also matches
how the rest of this system already works: registry gates, doctrine files, human confirms.

**LAYER 3: RANKING.** New candidates get scored against the approved rules and ranked, and every card
shows its reasoning: "matches: founder pedigree, novel concept. conflicts: liquidity below your band."

### ⚠️ THE HONEST LIMIT, do not oversell this to Jesse

A statistical model that genuinely learns his taste needs hundreds of labelled examples. At a realistic
decision rate that is a long way off. **What works from decision number one is rule extraction he
approves.** So the promise is "it gets smarter because it keeps proposing rules you agree with," NOT "the
AI figures out your taste." Do not describe it as the latter.

### PRECEDENT ALREADY IN THE CODEBASE
`/api/triage` and its decision store, `feedback-log.jsonl`, `exclusions.json`, and the SEEN-COINS ledger
are all existing capture patterns. Layer 1 should extend that plumbing rather than invent new storage.
Per the AGENT-FIRST LAW this eventually becomes a permanent agent, born via `agent-forge`.
