# LIST D — DEGEN INNOVATION DESK: methodology
**Born 2026-07-23 on Jesse's ask: "be like a screener of projects... like an analyst going around for a private equity fund... pitching ideas. Pretend like you're the best in the world at it... There's no limit for how degenerate you can get or how small the liquidity pools... I want to see your methodology too... I do want momentum still... brand new innovations... innovations that really can only happen in crypto, and some of them are viral. I also want you to go at it from the viral angle as well."**

Feeds `suggested-degen.json` (rendered as List D on suggested.html). Lists A/B/C untouched. This file is the desk's living methodology; edit it and the next refresh obeys it.

---

## 1. The desk's one-line thesis

The single most repeatable degen alpha in crypto is being EARLY to the first loud instance of a brand-new mechanic: the first meme paired against a tokenized stock ($AI), the first launchpad on a hot new chain (PONS), the first creator coin with a real fee switch. First instances collect the entire spotlight, the copy-traders, and the press cycle; copies collect the leftovers. So List D hunts NEW MECHANICS with LIVE TAPE, and says exactly which of the two it is buying: the mechanic's flagship, or a mispriced early copy.

## 2. What qualifies (the two gates)

**GATE 1 — identity + tradability (binary):**
- Live pool with a resolvable contract, pulled fresh from DexScreener/GeckoTerminal at generation time. No live pool = watch item in the notes, never a card.
- Not held by Jesse, not triaged, not a stable/wrapped/quote asset, not a known decoy (exclusions.json + STATE-OF-PLAY holdings; SPACEHOOD and PONS excluded by hand until the server's TRIAGE_HOLDINGS catches up).
- NO liquidity floor (Jesse's explicit rule). Depth becomes a RISK BAND label instead of a filter.

**GATE 2 — momentum (Jesse: "I want the chart to have momentum as well"):**
- Real tape: 24h volume >= $100K, OR >= $25K with volume/liquidity turnover >= 1x (a $40K pool doing $60K/day is alive; a $1M pool doing $5K/day is a museum).
- Chart state must be one of: (a) impulse up on 6h/24h, (b) pullback HOLDING above the base after a verified run, (c) fresh ignition off a base. Post-pump wreckage still knifing down fails the gate no matter how good the story (the AUTO-NO dead-chart rule from PLAYBOOKS.md, inherited verbatim). Great-story-no-momentum names go to the BENCH section of the JSON _meta, with the trigger that would promote them.

## 3. The composite score (0-100, shown per card as the rank order)

| Dimension | Weight | What earns points |
|---|---|---|
| Innovation / first-mover | 30% | first > biggest > spotlight > early-copy; mechanic verifiable ON-CHAIN (pool structure, fee flows) beats press claims; "can only happen in crypto" is the bar |
| Momentum quality | 25% | 6h/24h shape (up or held pullback), vol/liq turnover, whether volume is building or fading vs the run's ignition |
| Viral surface | 20% | named press hits, X chatter with dates, a face attached (founder/influencer), one-sentence legibility for a normie ("a meme priced in real NVDA stock") |
| CoinPicks system fit | 15% | narrative stack per Jesse's stated loves (Robinhood Chain, RWA x meme, AI-finance, Virtuals, founder pedigree); playbook rhyme (PLAY 001 launchpad / PLAY 004 tokenized stocks) |
| Asymmetry | 10% | FDV headroom vs the meta's anchor comp (e.g. CASHCAT ~$47M FDV is the current brokerage-chain meme ceiling); exit realism given pool depth |

Scores are relative within the run. The score orders the list; it is not a buy signal. Every card still goes through Jesse's triage -> token-vetter -> per-trade confirm exactly like Lists A/B/C.

## 4. Risk bands (labeled, never averaged away)

- **BAND A** — liq >= $1M, days of history, mechanic verified. Degen by asset class only.
- **BAND B** — liq $100K-$1M or < 7 days old or mechanic partially verified. Standard degen.
- **BAND C** — liq < $100K, hours old, unverified self-described mechanics, no press. Lottery tickets: assume the floor is zero, size like it is entertainment. The desk still lists them because Jesse said no limit, but the band is printed on the card tag and the honest reason is in `special`.
- Execution reality is labeled per pick: Robinhood Chain + Base = engine-executable (registry + vetter first); Solana = OUTSIDE the engine, manual wallet only; Coinbase-listed = buy-ladder skill lane.

## 5. Sourcing (how the candidates got found, every run)

1. **Momentum sweep (quantitative):** GeckoTerminal global + per-network trending and new pools (robinhood, base, solana, eth), DexScreener token-boosts (top + latest = who is PAYING for attention) and fresh token-profiles. No liq floor, vol >= $5K, txns >= ~100/24h to keep corpses out.
2. **Innovation hunt (qualitative):** dated web searches across crypto press + X surfaced posts for first-of-kind mechanics this month; every candidate then resolved to a LIVE pool via DexScreener API or dropped to the watch list. Claims labeled verified / reported / inferred, with URLs.
3. **System priors:** PLAYBOOKS.md (setups + AUTO-NO), jesse-what-i-love-thesis (narrative weights), SEEN-COINS.csv (dedup ledger: read before, append after), exclusions.json, current holdings from STATE-OF-PLAY.
4. **Merge + verify:** finalists get their pair data re-pulled live at emit time; contracts cross-checked against known quote-asset addresses (e.g. the NVDA stock token 0xd0601CE1... shared by AI/REAL pools). The desk surfaces; it never deep-vets. Token-vetter owns contract legitimacy before any registry add or trade.

## 6. Standing exclusion inheritances

- Everything in exclusions.json (holdings, dollarTrue, blacklist, triaged) by ticker + contract.
- Jesse's live positions that predate the exclusions rebuild (SPACEHOOD, PONS resting order) excluded by hand this run; flagged to add to TRIAGE_HOLDINGS.
- Tokens already on Jesse's active radar in other lanes are DISCLOSED, not hidden: if it is already a Luke-Belmar target or a PLAY placeholder subject, the card/bench says so (the desk's job is NEW ideas, not re-pitching his own book to him).

## 7. Refresh + ownership

- Manual refresh this run (born in-session). Proposal per the AGENT-FIRST LAW: fold List D into the `suggestions-refresher` agent as a third mode (it already owns A/B refresh mechanics + exclusion hygiene), OR birth a dedicated degen-desk agent via agent-forge. JESSE'S CALL; nothing birthed without his word.
- Cadence suggestion: this list decays in HOURS (band-C names live and die in a day). Refresh on demand before a trading session, not on a timer.

## 8. Honesty ledger (what this desk cannot see)

- Mechanics described only by the project itself are labeled and treated as marketing until fee flows are traced (HBULL's buyback claim is the live example).
- Sub-day tokens have no history to read; momentum on them is tape-only and can be one wallet painting candles. Band C exists for a reason.
- The sweep sees DexScreener/GeckoTerminal's indexed universe. Anything they have not indexed yet (first minutes of a launch) is invisible by design; this desk is not a sniper bot and does not want to be.
- Rate limits are real (GT free tier); a run that got 429-degraded says so in `_meta` instead of pretending completeness.
