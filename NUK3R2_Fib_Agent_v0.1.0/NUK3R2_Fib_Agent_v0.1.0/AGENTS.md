# Agent Contract

Mission: generate, validate, monitor and learn NUK3R2 Fibonacci market structures.

Non-goals:
- no auto-buy/sell
- no position management
- no automatic methodology changes
- no hindsight-based anchor selection

Required order:
1. Validate token/contract/chain.
2. Determine data coverage and token age.
3. Choose mature or young study mode.
4. Identify ATL and structural high candidates.
5. Calculate Wick High and Maximum Body High.
6. Calculate both Fib structures.
7. Run wick/data-integrity checks.
8. Select a primary anchor only under explicit rules; otherwise NEEDS_REVIEW.
9. Persist both structures and rationale.
10. Start reaction tracking for watchlist candidates.
11. Capture volume/liquidity/market/narrative context.
12. Store immutable observations.
13. Compare hypotheses only from eligible historical observations.
14. Send methodology-change proposals to Queen Bee; beekeeper approval is required.

Definitions:
Wick High = maximum candle High in the eligible study window.
Body High = maximum MAX(Open, Close) in the eligible study window.

Do not call the custom Body High anchor IBH internally. IBH has a conventional session meaning that differs from this methodology.

Fib formula:
price = bottom + (top-bottom)*(1-percent/100)

Thus 100%=bottom and 0%=top.

Suspicious wicks are flagged, not silently deleted. Store wick extension, volume context, liquidity context, source count and exclusion rationale if applicable.

Historical tests must freeze information available at the decision timestamp. Later price movement measures outcomes only; it cannot justify the original anchor.

Status: ACTIVE, WATCHING, NEEDS_REVIEW, DATA_ERROR, PAUSED.
