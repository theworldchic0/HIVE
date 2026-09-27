# NUK3R2 Research System — Phase 1 (Narrative Intelligence Edition)

> The beekeeper's method, preserved in full as the Research Bee's source of truth. Two **audited
> implementation fixes** apply in `config/research.json` and are noted where they appear (§16 Timing,
> §11 Liquidity tiers). Everything else is implemented as written.

**Scope:** everything between "I have a ticker or narrative" and "I have a Pass/Fail verdict + my own
decision." This is the front door. Nothing enters the Altcoin Trading Terminal (Phase 2) or the Position
Manager (Phase 3) without going through it.

**Operating principle:** a research engine, not an auto-buy engine. It identifies asymmetric
opportunities by combining product quality, narrative power, narrative timing, asset expression,
liquidity asymmetry, team credibility and cycle context. The output is a researched decision with
explicit evidence, uncertainty and re-check conditions.

## 1. Core strategy
> "We seek underexposed assets whose product, exclusivity, and credible execution give them the ability
> to capture an emerging or reviving narrative before that narrative becomes fully priced into liquidity."

- **Narrative Strength × Narrative Timing × Asset Expression = Opportunity**
- **Opportunity × Product Quality × Liquidity Asymmetry = CoinPicks Candidate**

A strong narrative doesn't automatically make a winning token. A narrative can be powerful but mature,
widely known, or attached to a poor asset expression. A token can be excellent while its narrative
fades. Research separates those variables and finds where they overlap. The strategy targets small and
mid caps. Large caps can pass quality tests, but flag them when they're already heavily discovered,
highly liquid or institutionally saturated.

**Foundational distinction:** Narrative Quality ≠ Narrative Timing · Narrative Strength ≠ Asset Quality · Asset Quality ≠ Entry Timing.

## 2. Step 0 — Exclusivity Factor Gate (runs first, always)
Three sub-scores, 0–10 each:
- **Ease of Use.** Does it actually work smoothly, simply and effectively? Test it yourself.
  0–3 broken or vaporware · 4–6 works but clunky · 7–10 genuinely easy, reliable and effective.
- **Hair-on-Fire.** Does it solve an important problem users urgently feel they must adopt? This scores
  urgency, not technology. 0–1 gimmick · 2–4 interesting, not urgent · 5–7 clearly valuable · 8–10
  undeniable urgency.
- **Exclusivity.** A unique, hard-to-duplicate advantage: first-to-market with durable network effects,
  a legal or regulatory edge, official approval or distribution clones can't buy, world-class strategic
  backing, proprietary infrastructure, uniquely powerful distribution. Never award it for a
  standardized or easily copied feature.

**Gate = /30. 16+ continue; 0–15 FAIL and stop.** The gate is absolute: a great narrative, smart-money
fit or a deep drawdown never overrides it.

## 3. Step 1 — Market + cycle regime
Regimes: Bull Expansion · Late Expansion · Distribution / Transition · Bear Decline · Capitulation /
Bottom Watch · Recovery / Early Expansion · Mania / Late Cycle. BTC structure is the anchor.

Record: BTC price, distance from the latest cycle high and low, BTC trend, approximate phase, macro and
liquidity conditions, broad vs selective market, and whether rotation is accelerating or contracting.

**Bottom-window logic:** the cycle model's bottom and momentum windows are context, not promises. When
one is active, **Bottom Window Mode** applies: find narratives being born, revived or accelerating while
weak legacy narratives lose attention.

Implications: in a broad mania quality matters less for a while; in a selective recovery narrative
quality matters more; in a bear or at the bottom, survival, new narratives, revivals and deeply
repriced champions matter most; in late expansion, maturity and exhaustion matter.

**Mandatory one-line interpretation**, e.g. *"Bear / Bottom Watch — prioritize rising or freshly revived
narratives, newborn assets, crashed champions and durable toll-takers; avoid mature stories without a
new propagation mechanism."*

## 4. Step 2 — Narrative identification
What story is this asset asking the market to believe?
- **A. Primary narrative:** one sentence a normal person understands, no jargon.
- **B. Secondary narratives:** AI, privacy, sovereignty, anti-surveillance, DeFi, institutional adoption,
  stablecoins, prediction markets, digital scarcity, and so on.
- **C. Constellation:** the reinforcing bundle (e.g. Private AI = AI + privacy + sovereignty; root:
  technology transformation / fear of displacement / control).
- **D. Lineage:** *Perennial root → prior crypto narrative → current mutation → current asset
  expression.* Never just "AI" or "RWA".
- **E. Status:** Emerging · Rising · Mature · Fading · Revived · Dead. A revival requires a **new
  external force** that restarts repetition, not just memory.

## 5. Step 3 — Narrative Power (/14): seven questions × 0/1/2
1. **One-Sentence Test:** can a normal person retell it after one hearing?
2. **Perennial Root:** is it a mutation of a durable human or economic narrative (§6)?
3. **Tribe:** does owning it make someone part of an "us" against a "them"? (users vs banks, privacy
   vs surveillance, sound money vs debasement, crypto natives vs TradFi)
4. **Face or Mystery:** is there a hero, villain, founder, celebrity or mystery keeping it in the media?
5. **Fear + Envy Engine:** does it trigger both fear and aspiration / FOMO?
6. **Repetition Machine:** does it regenerate through price, news, regulation, celebrities, launches,
   memes, crises, upgrades, cultural conflict or recurring events?
7. **Action Script:** story → specific asset → obvious action? "AI wins" can be powerful and still have
   a weak action script for one token.

Bands: 0–5 weak · 6–8 limited · 9–10 strong · 11–12 very strong · 13–14 exceptional. Scores are
judgments backed by concrete evidence, not machine truth.

## 6. Shiller's nine perennial narrative roots
1. Panic vs Confidence (crashes, bottoms, contagion, stablecoins as safe havens)
2. Frugality vs Showing Off (visible wealth, NFTs, "wen lambo")
3. The Gold Standard / Sound Money (BTC as digital gold, scarcity)
4. Machines Replacing Jobs (automation, AI, agent economies)
5. Automation and AI Replacing Almost All Jobs (the extreme version)
6. Real-Estate Booms and Busts (metaverse land, tokenized RWA)
7. Stock-Market Bubbles / Get-Rich Stories (ICOs, meme cycles, early-participant riches)
8. Boycotts, Profiteers and Evil Business (anti-bank DeFi, anti-surveillance privacy)
9. Wage-Price Spiral / Inflation (inflation fear → sound money)

A root creates durability. Cycle, curve and asset expression decide the opportunity.

## 7. Step 4 — Narrative stage and curve
**Stage:** 1 Birth (barely visible) · 2 Early Formation (entering crypto culture, limited traction) ·
3 Rising (attention expanding, influencing price and capital) · 4 Peak / Mature (widely known,
crowded, heavily priced) · 5 Fading (losing its ability to attract capital). A revival is recorded as
*Stage + Revival*.

**Curve:** Declining · Flat · Early Rising · Rising · Accelerating · Peaking · Fading · Revival.
Measure with plain-language keywords ("tokenized treasury", "prediction market", "AI agents
payments", "privacy crypto"), not tickers, against a broad crypto benchmark, using search interest plus
news and social evidence.

**Evidence hierarchy.** Strongest first: multiple independent sources agree · search rising while
news and social repetition rise · price and volume confirm · more projects appear under the story ·
liquidity expands. Weakest: one viral post, one influencer, one price spike, "it feels hot".

**Core rule:** High Narrative Power + a Rising or Revived Curve near an important cycle window = the
highest-priority setup.

## 8. Step 5 — Constellation (/5)
0 isolated · 1 one weak association · 2 two related stories, little interaction · 3 several mutually
reinforcing narratives with measurable attention · 4 a strong bundle with several independent
propagation channels · 5 a full constellation with live catalysts, strong identity and expanding
participation. Record the primary and secondaries, roots, catalysts, assets sharing the story, and
whether the bundle is expanding. Don't double-count marketing labels.

## 9. Step 6 — Archetypes (at least one)
- **Anchor:** the dominant recurring asset. Safer, less asymmetric.
- **Crashed Champion:** a prior-cycle leader, deeply repriced, with the narrative alive or reviving,
  the product working, the team credible and the thesis intact. A crash alone isn't enough.
- **Newborn Narrative:** a new asset whose story is forming in the bear or transition. It needs real
  product or credibility, a clear asset expression and differentiation. High priority, high risk.
- **Toll-Taker:** infrastructure that earns from activity whichever narrative wins (exchanges, rails,
  oracles, lending, payments, settlement). It needs real usage and fee capture.
- **Revival:** an old narrative with a *new catalyst*. No catalyst, no revival.
- **Borrowed / Piggyback:** borrows a societal story. Risk: crypto capital picks another expression.
- **Meme Mutation:** a new generation of a meme. Prefer fresh mutations while the meme re-accelerates.
- **Dead Narrative:** no repetition engine and no credible revival catalyst. Cheapness doesn't help.

## 10. Step 7 — Asset Expression (/10): five × 0/1/2
Narrative-to-Token Fit · Category Leadership · Distribution / Reach · Product Reality · Token Capture /
Economic Link. A strong narrative with a weak asset expression is not a strong candidate.

## 11. Step 8 — Liquidity + trajectory
Measure the main pool size and the ±2% depth. Source tiers: Low <$200K pool / <$15K depth · Medium
$1M–$6M / $15K–$100K · High >$6M / >$100K.
> **Implementation fix (ruling R-10):** the source leaves $200K–$1M undefined. Pool bands used: Micro
> <$50K · Low $50K–$200K · Medium $200K–$6M · High >$6M, on the lower of the two axes. Only a
> *measured* depth counts toward the tier.

**Contract and registry verification comes first:** official contract, independent explorer
resolution, chain and deployment, reject decoys, and match the official domains to the contract. A fake
pool invalidates the research.

**Trajectory 0–5:** Contracting · Flat · Early Improvement · Growing · Strong Growth · Rapid Expansion.
**Cycle-relative:** Underexposed / early · Normal · Broadly discovered · Mature / saturated. The goal is
low or moderate liquidity plus a credible path to higher liquidity.

## 12. Narrative conversion: is the story becoming capital?
Signals: search · social repetition · news · volume and price participation · liquidity and depth
expansion. **State:** None · Emerging · Confirmed · Strong · Reflexive. Don't confuse attention with
capital.

## 13. Step 9 — Team credibility (weighted /10)
Pick 3–5 key people (Founder, Head of Product, Head of Marketing, 1–2 standouts). Each scores 0–10 =
**High** (max 5: 5 founded and scaled a successful crypto company · 4 leadership at a global
institution or major crypto company · 2 founded a crypto project with unclear traction) + **Medium**
(max 3: 3 founded a profitable, growing or acquired business · 2 non-executive role at a top company · 1
business exists, traction unclear) + **Low** (max 2: 2 MBA/PhD/CFA or equivalent · 1 influencer
exposure).

**Final = (Founder × 5 + Σ others) / (5 + number of others).** Only prior track record counts. Every
claim needs a link and a Ctrl+F-able quote. Pseudonymous people are *unverifiable*: that's a real
finding, not a neutral score.

## 14. Smart Money Fit (/6)
0–1 weak · 2–3 developing · 4–5 strong · 6 institutional grade. Evidence: institutional partners,
acquisitions, treasury participation, credible counterparties, major distribution, regulated access,
professional usage. An institutional partnership isn't token demand.

## 15. Core Quality (/50)
Product Quality /10 + Narrative Power /14 + Asset Expression /10 + Team /10 + Smart Money /6.
Bands: 0–24 weak · 25–29 below standard · 30–34 acceptable · 35–39 good · 40–44 strong · 45–50 exceptional. It never overrides a failed gate.

## 16. Timing (/20)
Narrative Stage /5 + Narrative Curve /5 + Constellation /5 + Liquidity Trajectory /5.
Bands: 0–5 poor · 6–9 weak · 10–12 neutral · 13–16 favorable · 17–20 exceptional.
> **Implementation fix (audit):** the source adds the ordinal Stage (1 Birth … 5 Fading) straight into
> Timing, so a fading story out-scored an early one. Stage is mapped to timing points instead: Early
> Formation 5 · Rising 4 · Birth 3 · Peak/Mature 1 · Fading 0 · Revival +1 (cap 5). Curve: rising 5 ·
> revival 5 · early rising 4 · accelerating 4 · flat 2 · peaking 1 · fading 1 · declining 0 (ruling R-11).

## 17. Opportunity Matrix (two axes, never one number)
| Class | Core / Timing |
|---|---|
| **Exceptional candidate** | 45+ / 17+ |
| **Priority Opportunity** | 40+ / 13+ |
| **Quality Watch** | 40+ / <13 |
| **Narrative Speculation Watch** | <40 / 13+ |
| **Pass / Avoid** | <40 / <13 |

Hive confidence (drives the Trader Bee discovery size): Exceptional → **high ($10)** · Priority →
**medium ($5)** · every other class → **low ($1)**.

## 18. Final status (one)
EARLY ASYMMETRIC · STRONG ACCUMULATION · WATCH · MATURE / LATE · DEAD NARRATIVE · SPECULATIVE NARRATIVE.

## 19. Funnel
**Path A, project first:** Ticker → Product → Narrative → Timing → Asset Expression → Decision.
**Path B, narrative first:** Narrative → Constellation → Candidate Assets → Product/Team/Token →
Liquidity → Decision. Path B finds newborn narratives before the winning ticker is obvious; the Meta Bee
feeds it. Questions: what's accelerating, from which root, what reinforces it, what external event
drives repetition, is the curve rising, peaking, fading or reviving, which assets express it directly,
which leads, which is most underexposed, which has real product and token capture, and which has enough
liquidity to survive but enough asymmetry to matter.

## 20. Bottom Window Mode
Priorities: 1 newborn stories · 2 revivals · 3 crashed champions · 4 toll-takers · 5 new meme
mutations (limited). Avoid: buying only because a token is down 80–99%, reviving a dead narrative
without a catalyst, treating borrowed hype as durable, and mistaking institutional use of a technology
for a token action script. **Standing instruction: re-run the scan inside the bottom window. The best
coin on the list may not exist yet.**

## 21. Evidence standard
Every major claim needs evidence: search data, mainstream or financial media, credible crypto media,
docs, product usage, on-chain activity, market data, social activity, policy events, launches,
institutional developments. Don't score a narrative because an AI says it's strong. Explain who tells
the story, why people care, how it repeats, what changed recently, and whether the market is responding.

## 22. Anti-hindsight and anti-story-fitting
1. Don't use future success as evidence of past narrative strength.
2. Separate the narrative explanation from the outcome.
3. Show uncertainty.
4. Don't assign archetypes retroactively.
5. Use multiple sources.
6. Distinguish the story from the ticker.

## 23. Decision tree
Gate? → cycle → primary narrative → Narrative Power /14 → stage and curve → constellation /5 →
archetype → Asset Expression /10 → liquidity level and trajectory → team /10 → Smart Money /6 → Core
/50 → Timing /20 → final classification → **the researcher's decision, BUY / WATCH / PASS, and why.**

## 24. One-page report
Header (name, ticker, chain, contract, CoinGecko, website) · one-sentence overview · cycle context ·
narrative identity · Narrative Power (all seven, with evidence) · narrative timing · constellation ·
archetype · asset expression · product · liquidity (pool, ±2%, tier, trajectory, contract verification) ·
team · smart money · Core /50 · Timing /20 · final status · risk flags · re-check triggers · my decision.

## 25. Re-check triggers (examples)
Curve flat → rising · stage early → rising · a new external catalyst · the constellation expands · a
major product launch · liquidity expands · a weak token starts capturing attention · BTC enters or exits
the bottom window · a project falls into true crashed-champion range · a newborn becomes established
enough to evaluate · a thesis-breaking event. Re-checks are deliberate.

## 26. Handoff to Phase 2
"My Decision" is the literal handoff. **Nothing in Phase 1 auto-buys.** In the Hive, the beekeeper
publishes the verdict; the Trader Bee's own bounded rules (its sandbox) decide any execution, and a failed
gate is a hard stop.

## 27. What Phase 1 doesn't do
Auto-buy, manage positions, set Fib/TSL exits, monitor whales, manage trades, replace execution rules,
guarantee bottom dates or winners, or treat a score as a prediction machine.

## 28. Source discipline
Prefer: primary sources → official docs → on-chain / exchange / market data → reputable independent
reporting → high-quality secondary research → social posts (supporting only). Cite where the claim
appears. Foundations: product and market research, Shiller's *Narrative Economics*, and the cycle and
narrative-curve framework.

## 29. Master principles
1 A good project isn't automatically a good trade. 2 A good narrative isn't automatically a good token.
3 A strong narrative at the wrong stage can be a poor opportunity. 4 Separate narrative strength from
timing. 5 Stories spread through repetition, identity, emotion and simple language. 6 Constellations
beat isolated labels. 7 The story can survive while the ticker changes. 8 The best expression isn't
necessarily the first to get attention. 9 Liquidity is direction as well as size. 10 Search interest
without capital flow isn't enough. 11 Price without narrative understanding isn't enough. 12 A 90% crash
isn't a thesis. 13 A dead narrative doesn't get attractive by getting cheap. 14 A revival needs a new
reason to talk. 15 Newborn narratives deserve attention near cycle bottoms. 16 Crashed champions need
surviving products and narratives. 17 Toll-takers give ecosystem exposure. 18 Institutional adoption
doesn't create a token action script. 19 A project's current success isn't proof of its team's prior
credibility. 20 Every score must be explainable. 21 Subjective scores need evidence and a judgment label.
22 No hindsight. 23 The strongest opportunity is where quality and timing overlap. 24 Bottom windows are
for observation as much as entry. 25 The best next-cycle coin may not exist yet.

## 30. Final equation
Gate → cycle → story → narrative power → curve → constellation → archetype → asset expression → liquidity
and its direction → team → smart money → **Core /50** → **Timing /20** → decision.
The ideal candidate is high quality and underexposed, with a powerful narrative, a rising or freshly
revived curve, a strengthening constellation, room for liquidity to grow, and a token that directly and
credibly expresses the story.
