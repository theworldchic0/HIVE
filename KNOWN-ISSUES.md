# KNOWN ISSUES: honest limits of this build (v5, 2026-07-24)

1. **Partial fills are not split into realized P&L.** A partially filled resting
   order shows as "partial" with its filled %, but the filled fraction is not yet
   booked into per-position realized P&L. Workaround: the ledger and the order's
   own readback carry the truth; full fills book normally.
2. **Solana is watch-only.** The ledger can ingest a Solana address read-only;
   there is no Solana execution path (by design, 1inch is not on Solana).
3. **Charts need a GeckoTerminal-known pool.** Tokens whose pool only DexScreener
   indexes may show "no candle data" on the levels chart; the card's DexScreener
   link still works. The GT iframe inside the ladder designer can also take a few
   seconds to paint on slow connections.
4. **Hand-pinned fill links.** When the 1inch book reports a fill without a tx
   hash, the dashboard shows the fill without a chain link; you can hand-pin the
   tx in `CONFIRMED_FILLS` inside `cockpit/datasource.mjs` (map ships empty, with
   the shape commented).
5. **Suggested Plays ships empty.** The four list JSON files are placeholders;
   the pages render a friendly note. Populate them with your own screens (any
   process that writes the documented JSON shape works), or ignore the pages.
6. **Coinbase card is optional and read-only.** Without `cockpit/coinbase.json`
   the dashboard simply skips it; that is expected, not an error.
7. **Thin-market microcaps behave like thin markets.** The venue race gets you
   best-of-two quotes, but a 2-hop route on a thin token can still cost 2-5% in
   spread and impact. The preview shows the quote; read it.
8. **Add to Database is bring-your-own-researcher.** The button on suggested
   cards queues a row into `cockpit/research-requests.jsonl` and the card polls
   `research-results.jsonl` for a result link (the UI calls it a Notion link;
   any URL works). Nothing ships to fulfill that queue; wire your own process or
   ignore the button.

Fixed in this build (was open in v1): the poisoned-pair price bug (a fake
DexScreener pair could hijack a token's price and liquidity display; pair picking
is now registry-first with a median-price sanity filter plus a price-vs-chart
disagreement guard in the ladder designer) and the ladder designer's hard
per-tier size caps (the SIZE slider is now free 0.01%-10% at every risk level
with suggestions instead of clamps, editable per-rung dollar amounts, and
add/remove rung controls).

## v5 notes
- Take-profit automation (ladder TP rungs, fill-triggered sentinel sells, standing bag-fraction
  sells) exists upstream but ships in the NEXT update — v5's sentinel acts only on rules you
  write by hand in cockpit/sentinel-rules.json.
- The suggested-plays lists start EMPTY and fill from your own screening runs (Research/).
- CEX realized/closed P&L still not wired into the closed-positions table; order truth via
  `node module/cex.mjs --orders`.
- **WETH/ETH-funded router fills are not auto-booked.** The Robinhood-Chain router-recovery
  scan classifies fills funded by a STABLE money leg; a fill funded in WETH/ETH is skipped
  with a loud ledger warning naming the tx (guessing money legs risks booking non-trades).
  Add such a trade in one line with `node ledger/add-manual-trade.mjs`.
