# THE WOLF PROJECT

Commodities intelligence desk. Scouts the web for breadcrumbs leading to good
commodity trade opportunities, finds which brokers/propfirms offer those
commodities, compiles a coverage list, and surfaces it on a live Wall-Street-style
dashboard.

## Mission
1. **SCOUT** — scan news, analyst notes, calendars, supply/demand signals, COT data,
   sentiment for commodities showing edge (catalyst + trend + positioning).
2. **MATCH** — cross-reference each flagged commodity against brokers & prop firms
   that actually offer it (symbol, leverage, spread, prop rules).
3. **COMPILE** — build a ranked opportunity list + broker/propfirm coverage table.
4. **DISPLAY** — live dashboard (ticker tape, heat map, opportunity cards, coverage
   matrix) that refreshes like a trading floor.

## Architecture (proposed)
```
THE WOLF PROJECT/
  scout/       data collectors (news, prices, calendar, COT, sentiment)
  compiler/    scoring engine + broker/propfirm matcher -> ranked list
  data/        cached pulls + compiled JSON (opportunities.json, coverage.json)
  dashboard/   live web UI (HTML/JS) reading the JSON, auto-refresh
```

## Pipeline
`scout (pull) -> compiler (score + match) -> data/*.json -> dashboard (render)`

## Commodity universe (draft)
Metals: gold, silver, copper, platinum, palladium.
Energy: WTI, Brent, natural gas.
Ags: wheat, corn, soybeans, coffee, sugar, cocoa.

## Scoring (draft) — each commodity 0-100
- Catalyst proximity (upcoming data/event)        25
- Trend / momentum (price vs MAs)                 25
- Positioning (COT / sentiment extremes)          20
- Supply-demand signal (deficit/surplus news)     20
- Volatility fit (tradeable, not chaos)           10

## Broker/propfirm coverage targets
Brokers: BlackBull, IC Markets, Pepperstone, Eightcap ...
Prop firms: FundedNext, FTMO, GoatFunded, FundingPips, The5ers, E8 ...
For each: does it offer the symbol? leverage, typical spread, prop rules.

## Status
- [x] Folder scaffold
- [ ] Scout data sources chosen
- [ ] Compiler scoring engine
- [ ] Broker/propfirm coverage data
- [ ] Dashboard UI

## NOTE
Research/intelligence tool. Outputs are leads to investigate, NOT trade signals
or financial advice. Always verify before risking capital.
