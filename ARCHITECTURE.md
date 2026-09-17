# Excalibur v13 — Markov Omnibus: System & Mechanics

> **What this document is.** The complete, build-ready description of how this
> trading-intelligence desk works end to end — every data source, every formula,
> the Markov regime engine, the scoring model, the verdict logic, the HTTP API,
> the JSON contract, and the operational layer. It is written so that a second
> app (e.g. a mobile "consult before I trade" companion) can be built against it
> without reading the source.
>
> **What it is NOT.** Not an auto-trader, and not financial advice. Every output
> is a *mechanical read of data* — a lead to investigate, not a trade
> instruction. Always verify before risking capital.

Internally the codebase is branded **THE WOLF PROJECT / STAALWAG**. "Excalibur
v13 — Markov Omnibus" is the name of this iteration: an *omnibus* (all four
asset classes scored by one engine) whose signature layer is an *observable
Markov regime* read on top of the score.

---

## 1. The idea in one paragraph

Pull live prices for ~44 instruments across four asset classes. For each one,
compute a trend/momentum/volatility read from the price series, blend it with
hand-maintained fundamental inputs (catalyst, positioning, supply/demand) into a
single **0–100 opportunity score**, tag it with a **Markov regime** (BULL / BEAR /
SIDE plus how "sticky" that regime is), and turn all of that into a mechanical
**BUY / SELL / WATCH** verdict with a written bull-vs-bear case. Attach the list
of brokers and prop-firms that actually offer the instrument. Rank everything,
serve it as JSON behind a login gate, and render it on a live "trading-floor"
dashboard. A daily/weekly Telegram post summarises the top reads and the
market-wide regime vote.

---

## 2. Pipeline overview

```
                        ┌───────────────────────── scout/ (collectors) ──────────────────────┐
                        │  prices.py   Yahoo hourly bars → trend/mom/vol + regime             │
                        │  regime.py   observable Markov regime (state, persistence, next)    │
                        │  news.py     Google News RSS → headlines + bull/bear tilt (on-demand)│
                        └────────────────────────────────────────────────────────────────────┘
                                             │
   data/signals_<class>.json  ──────────────┤   (manual fundamental inputs)
   data/brokers.json          ──────────────┤   (venue coverage)
                                             ▼
                        ┌──────────────────── compiler/ ─────────────────────┐
                        │  score.py     5-component 0–100 score + ranking     │
                        │  analysis.py  verdict + conviction + bull/bear case │
                        └────────────────────────────────────────────────────┘
                                             │
                                             ▼
                        run.py  ── builds ──▶ data/opportunities_<class>.json
                                             │
                                             ▼
                        serve.py  ── HTTP ──▶ /data /refresh /news /calendar /rates /fx /health
                                             │
                                             ▼
                        dashboard/index.html  (live board)   +   Telegram posts
```

**One-line summary:** `scout (pull) → compiler (score + regime + verdict + match)
→ data/*.json → server → dashboard / app / Telegram`.

---

## 3. The universe (`config.py`)

Four asset classes. Each instrument maps to `(yahoo_ticker, display_category,
coverage_key)`. The `coverage_key` links it to a boolean column in
`brokers.json`.

| Class | `coverage_key`(s) | Instruments |
|---|---|---|
| **commodities** | `metals` / `energy` / `ags` | Gold, Silver, Copper, Platinum, Palladium, WTI Crude, Brent, Natural Gas, Wheat, Corn, Soybeans, Coffee, Sugar, Cocoa |
| **fx** | `fx` | EUR/USD, GBP/USD, USD/JPY, USD/CHF, USD/CAD, AUD/USD, NZD/USD, EUR/JPY, GBP/JPY, EUR/GBP |
| **indices** | `indices` | S&P 500, Nasdaq 100, Dow Jones, Russell 2000, DAX, FTSE 100, Euro Stoxx 50, Nikkei 225, Hang Seng, ASX 200 |
| **stocks** | `stocks` | NVIDIA, AMD, Broadcom, Microsoft, Apple, Meta, Amazon, Alphabet, Tesla, Palantir |

Each class also names its manual signal file (`signals_<class>.json`).

**Scoring weights** (also in `config.py`), max points, total = 100:

| Constant | Points | Component | Source |
|---|---|---|---|
| `W_CATALYST` | 25 | upcoming event / news catalyst | manual |
| `W_TREND` | 25 | price vs moving averages + momentum | auto (prices) |
| `W_POSITION` | 20 | positioning / sentiment extreme | manual |
| `W_SUPPLY` | 20 | supply-demand / fundamentals / rate-diff | manual |
| `W_VOLFIT` | 10 | tradeable volatility band | auto (prices) |

---

## 4. Price metrics (`scout/prices.py`)

Fetches **hourly** bars over a 1-month range from Yahoo's chart API
(`range=1mo&interval=60m`). Hourly (not daily) so FX/indices move through the day
instead of looking frozen. Pure `requests`; on Windows `truststore` is injected
so the OS certificate store is used.

Requires ≥ 60 clean closes, otherwise the instrument returns `None` (no data).
Computed fields:

| Field | Meaning / formula |
|---|---|
| `last` | latest close |
| `ma20`, `ma50` | simple moving averages of the last 20 / 50 closes |
| `mom20` | 20-bar momentum: `(close[-1] / close[-21] − 1) × 100` (percent) |
| `atr_pct` | 14-bar average true range as a % of price: `mean(high−low, last 14) / last × 100` |
| `above_ma20` | `last > ma20` |
| `above_ma50` | `last > ma50` |
| `ma_stack_up` | `ma20 > ma50` (fast average above slow = uptrend structure) |
| `regime` | the Markov regime block (see §5) |

---

## 5. The Markov regime engine (`scout/regime.py`) — the signature layer

This is the "Markov" in *Markov Omnibus*, and the most decision-relevant field
for a "should I take this trade right now" screen. It is **observable** (built
directly from realised price labels) and **honest by construction** — it makes no
forecasting claim beyond the transition matrix it measures, and the window and
threshold are explicit.

**Algorithm:**

1. **Label each bar.** Starting at index `window`, label bar *i* by its rolling
   return `close[i] / close[i−window] − 1`:
   - `> +thr` → **BULL**
   - `< −thr` → **BEAR**
   - otherwise → **SIDE**

   Defaults: `window = 20`, `thr = 0.005` (0.5%).

2. **Stride-sample.** Take every `stride`-th label (`stride = window` by
   default). Overlapping rolling windows share bars and would manufacture fake
   persistence; striding decorrelates the samples so the transition
   probabilities are honest.

3. **Build the transition matrix.** Over the sampled label sequence, count
   transitions between the three states into a 3×3 matrix
   `trans[from][to]`.

4. **Report the current state and its dynamics** from the row of the current
   state:
   - `state` — the label of the most recent bar (current regime)
   - `persist` — **stickiness**: `P(stay in current state next step)` =
     `trans[current][current] / row_total`, rounded to 2 dp
   - `next` — the most likely next state = `argmax` of the current row
   - `n` — number of sampled points the matrix was built from
   - `confidence` — derived from `n` (see gate below): `"high"` / `"medium"` / `"low"`
   - `vote` — boolean: is this regime allowed to count in the market read?

**Sample-size gate (enforced, not advisory).** The matrix is only as
trustworthy as `n`. Two thresholds make that explicit:

| Constant | Value | Effect |
|---|---|---|
| `MIN_N_VOTE` | **8** | below this: `vote = false`, `confidence = "low"` — **excluded from the market-wide vote**, and shown with a "thin, n=k" marker in posts |
| `MIN_N_TRUST` | **15** | at/above this: `confidence = "high"` (persistence treated as solid); between the two → `confidence = "medium"`, still votes but flagged ⚠ |

So: **below 8 → suppressed from the vote + marked; 8–14 → votes but downgraded
and flagged; ≥15 → full confidence.** A handful of thinly-sampled reads can no
longer swing the market call. (With 1-month hourly bars, `n` typically lands
around ~6 for short-session equities and ~20–29 for 24h FX, so the gate bites in
practice.)

**Guards.** Needs at least `window + stride×2` closes; if too short it returns
`{state:null, …, n:0, confidence:"low", vote:false}` (or the last label with
`persist:null` when there aren't enough sampled transitions — also non-voting at
`n:0`).

**Output shape:**

```json
"regime": { "state": "BULL", "persist": 0.71, "next": "BULL",
            "n": 20, "confidence": "high", "vote": true }
```

**Market-wide read** (`market_read`): majority vote of every shown instrument's
`state`, **counting only regimes that clear the gate** (`vote = true`; older
payloads without the flag fall back to the `n ≥ 8` test). Returns the winning
state, the vote split, and `counted` (how many regimes actually voted):

```json
{ "state": "BULL", "votes": { "BULL": 7, "BEAR": 2, "SIDE": 1 }, "counted": 10 }
```

If nothing clears the gate, `state` is `null` and `counted` is `0` (no market
read that day rather than a read built on noise).

Display icons used throughout the desk: 🟢 BULL · 🔴 BEAR · 🟡 SIDE.

---

## 6. Manual "scout" inputs (`data/signals_<class>.json`)

The three fundamental score components are **hand-maintained** per instrument and
dated in the file's `_doc` string. Each entry:

```json
"EUR/USD": { "catalyst": 15, "position": 13, "supply": 11,
             "note": "NFP Fri; JPM/Nomura 1.20 YE if DXY breaks below 100" }
```

- `catalyst` (0–25) — proximity/strength of an upcoming event or news driver
- `position` (0–20) — positioning / sentiment extreme (COT, crowding)
- `supply` (0–20) — supply/demand or rate-differential fundamentals
- `note` — free-text context, surfaced in the UI and bull case

**Freshness matters:** these do not auto-update. The file carries an "Updated
YYYY-MM-DD" date; always surface it so a stale fundamental half is visible.

---

## 7. The 0–100 score (`compiler/score.py`)

`score_one(name, price_metrics, signal)` combines the auto price read with the
manual signal. Each component is capped at its weight.

**Trend (0–25)** — `trend_points(pm)`:
- `+6` if `above_ma20`
- `+6` if `above_ma50`
- `+5` if `ma_stack_up`
- momentum term: clamp `mom20` to ±8, then add `(clamped / 8) × 8` → contributes
  up to ±8
- clamped to `[0, 25]`. A `trend_desc` string ("up / down / mixed, mom +x.x%")
  is emitted alongside.

**Vol-fit (0–10)** — `volfit_points(pm)`, a sweet-spot band on `atr_pct`:
- `≤ 0%` → 0 (no data)
- `< 0.5%` → 3 (too quiet)
- `0.5%–3%` → **10 (tradeable — the sweet spot)**
- `3%–5%` → 6 (lively)
- `> 5%` → 2 (chaos)

**Manual components** — taken from the signal, each capped: `catalyst ≤ 25`,
`position ≤ 20`, `supply ≤ 20`.

**Total** = `catalyst + trend + position + supply + volfit`, rounded to 1 dp.

The row returned carries the total `score`, the per-component `breakdown`, the
`trend_desc` / `volfit_desc` strings, the raw price fields, and the `note`.
`rank(rows)` sorts descending by score.

---

## 8. Verdict + case file (`compiler/analysis.py`)

`analyze(row)` turns the numbers into the "case file" a trader reads before
acting. All rule-based and deterministic (offline).

**Verdict** — from trend structure + score:
- `up`   = `above_ma50` **and** `ma_stack_up` **and** `mom20 > 0`
- `down` = `not above_ma20` **and** `not ma_stack_up` **and** `mom20 < 0`
- **BUY** if `up` and `score ≥ 50`
- **SELL** if `down`
- **BUY (weak)** if `up` but `score < 50`
- **WATCH** otherwise

**Conviction** — from score: `≥65` High · `≥50` Moderate · `≥40` Low · else Weak.

**Bull / bear case** — argument lines are appended when conditions hold:
- *Bull:* confirmed up-trend; momentum `≥ +3%`; supply ≥ 60% of its cap
  (quotes the `note`); catalyst ≥ 60% of cap; positioning ≥ 60% of cap; live
  "bullish news flow".
- *Bear:* trend not confirmed up (fakeout risk); momentum `≤ −3%`; move extended
  (`mom20 ≥ 20%`, pullback risk); high vol (`atr_pct > 5%`, prop-DD risk); no
  strong near-term catalyst; live "bearish news flow" ("news contradicts the
  chart"). If nothing else, a default broad risk-off/USD-spike line is added.

**Returned object:**

```json
"analysis": {
  "verdict": "BUY",
  "conviction": "Moderate",
  "summary": "BUY — conviction Moderate. The data leans long: ...",
  "price_reasoning": "Price ... above both its 20-day and 50-day averages ...",
  "score_reasoning": "Score 56.5/100 driven by ...; held back by ...",
  "bull": ["Trend up ...", "Momentum behind it (+1.5% in 20 days)."],
  "bear": ["No strong near-term catalyst — may drift."]
}
```

---

## 9. News tilt (`scout/news.py`)

Pulled **on demand** (by the server's `/news` route, not the batch run, to keep
refreshes fast). Per instrument it queries Google News RSS (free, no key), takes
the top 5 headlines, and derives a crude tilt from keyword counts:

- ≥ 2 more bullish keywords than bearish → **"bullish news flow"**
- ≥ 2 more bearish than bullish → **"bearish news flow"**
- else **"mixed news flow"** (or "no recent news")

Returns `[{title, source, date, link}]` plus the `tilt`.

**Design decision — news tilt is context, never a score input.** By deliberate
choice the tilt does **not** enter the 0–100 score and **cannot** flip a verdict:

- `score_one` takes no news argument — the score is price + the three manual
  fundamentals only.
- `_verdict` is a pure function of price structure + score; it never reads news.
- The tilt only ever *appends* a context line to the `bull` / `bear` arrays
  (and the "news contradicts the chart" flag), and even that is fetched live via
  `/news` — it isn't present at score-build time.

Rationale: the tilt is a crude directional headline count, not sentiment
analysis. Letting a keyword tally silently move the one number the whole ranking
depends on — or turn a BUY into a WATCH — would inject noise into the signal and
hide *why* the call changed. Kept separate, it stays a visible cross-check the
human applies (see §16, step 5), consistent with the engine's honest-by-
construction stance. **Clients should render news as its own context block, not
fold it into the score or verdict.**

---

## 10. Broker / prop-firm coverage (`data/brokers.json` + `run.py`)

`brokers.json` has two lists — `brokers` and `propfirms` — each row a set of
boolean coverage columns (`metals`, `energy`, `ags`, `fx`, `indices`, `stocks`)
plus `max_leverage`, `rules`, and `notes`. During the build, `coverage_for(key,
brokers)` collects every venue whose `coverage_key` column is true:

```json
"coverage": [
  { "name": "IC Markets", "type": "broker",   "leverage": "500:1",
    "notes": "Broad: FX, commodities incl softs, indices, shares" },
  { "name": "FTMO",       "type": "propfirm", "leverage": "2-step 10/5 d5 m10 static",
    "notes": "FX/metals/energy/indices + stock CFDs" }
]
```

This answers, per instrument, *where can I actually take this trade and under
what prop rules*.

---

## 11. The build (`run.py`)

`python run.py` (all classes) or `python run.py fx` (one class). For each class:

1. Load manual signals + `brokers.json`.
2. For every instrument: fetch `price_metrics`, `score_one`, attach `regime`,
   `category`, `ticker`, `covkey`, `coverage`, and `analyze` → append.
3. `rank` by score and write `data/opportunities_<class>.json` with a
   `generated` UTC timestamp, `asset` label, `class`, and the `opportunities[]`
   array.

News is deliberately excluded here (fetched live via `/news`).

---

## 12. The HTTP API (`serve.py`)

A stdlib `http.server` (threaded). Two tiers: **gated intel** and **open market
tools**.

| Method / path | Auth | Returns |
|---|---|---|
| `GET /data?class=<commodities\|fx\|indices\|stocks>` | gated | full `opportunities_<class>.json` — the main feed |
| `GET /refresh?class=<class>` | gated | re-runs the pipeline live, returns fresh JSON |
| `GET /news?name=<Instrument>` | gated | `{news:[...], tilt}` on demand |
| `GET /calendar` | open | this week's economic calendar (faireconomy feed, 30-min cache) |
| `GET /rates` | open | central-bank policy rates (global-rates scrape, 12-h cache, hard fallback table) |
| `GET /fx?from=X&to=Y` | open | live spot conversion (Yahoo, 10-min cache) |
| `GET /rss` \| `/feed` \| `/rss.xml` | open | RSS feed of the desk |
| `GET /health` | open | watchdog status; `200` all-green / `503` anything down |
| `GET /` \| `/index.html` | open→gated | brand landing page if not logged in; the live dashboard if authed |
| `GET /login`, `/auth`, `/go?t=…` | open | Telegram login flow → sets `wolf_session` cookie |
| `GET /manifest.json`, icons, `/og.png`, `/staalwag`, `/about`, `/home` | open | PWA + brand assets |
| `GET /l?c=<key>`, `/clicks.json` | open | click-tracking redirect + totals (marketing) |

**Auth gate.** Intel routes require a `wolf_session` cookie, issued by:
- **Telegram VIP login** — `/auth` (Telegram widget) or `/go?t=<login-token>`
  from the bot; membership checked via `is_vip_member`, session TTL bounded; or
- **`WOLF_PASS`** — a shared key (self-host convenience).

The open market tools (`/calendar`, `/rates`, `/fx`) are intentionally ungated so
they load inside Telegram's in-app browser where cookies may not ride along.

---

## 13. The data contract (one opportunity object)

This is the exact object a client renders. Build UI against this shape:

```json
{
  "name": "USD/JPY",
  "score": 56.5,
  "breakdown": { "catalyst": 13.0, "trend": 18.5, "position": 12.0, "supply": 10.0, "volfit": 3.0 },
  "trend_desc": "up, mom +1.5%",
  "volfit_desc": "ATR 0.2%",
  "note": "BoJ normalisation vs hawkish Fed; MoF intervention risk near highs",
  "price": 161.68, "mom20": 1.46, "atr_pct": 0.23,
  "ma20": 160.67, "ma50": 159.39,
  "above_ma20": true, "above_ma50": true, "ma_stack_up": true,
  "regime": { "state": "BULL", "persist": 0.71, "next": "BULL", "n": 20, "confidence": "high", "vote": true },
  "category": "Major", "ticker": "USDJPY=X", "covkey": "fx",
  "coverage": [ { "name": "IC Markets", "type": "broker", "leverage": "500:1", "notes": "..." } ],
  "analysis": {
    "verdict": "BUY", "conviction": "Moderate", "summary": "...",
    "price_reasoning": "...", "score_reasoning": "...",
    "bull": ["..."], "bear": ["..."]
  }
}
```

Wrapping payload: `{ "generated": "YYYY-MM-DD HH:MM UTC", "asset": "FX",
"class": "fx", "opportunities": [ ... ] }`.

---

## 14. Presentation & distribution

- **`dashboard/index.html`** — the gated live board (ticker/heat-map/cards style),
  reads `/data`, auto-refreshes, opens per-instrument case files, pulls `/news`
  on demand. **`dashboard/landing.html`** — the public brand front door.
- **`wolf_post.py` / `weekly_post.py`** — compose the daily/weekly Telegram
  posts: top reads per class as `• NAME — VERDICT · score N 🟢 BULL, 71% stay`,
  headed by the **market regime vote** (`market_read` across everything shown).
- **`gate_bot.py`** — the Telegram VIP login bot (issues login tokens, checks
  membership).
- **`marketer.py` / `promo_x.py` / `PROMO.md`** — campaign CRM, weekly report,
  ad copy.

---

## 15. Operational layer (`watchdog.py` + `serve.py` runtime)

`serve.py` runs everything in-process as registered threads:

- **refresh loop** — re-runs the pipeline every `REFRESH_MIN` minutes
  (heartbeat per cycle).
- **gate_bot** — VIP login polling (heartbeat per poll).
- **marketer** — campaign timer / weekly report.
- **watchdog** — checks every `WATCHDOG_MIN` minutes (default 5): restarts dead
  threads (with crash-loop backoff), alerts `ADMIN_IDS` on Telegram with a
  cooldown, watches `opportunities_<class>.json` freshness on disk
  (`STALE_DATA_MIN`, default 3× refresh), and feeds `/health`
  (`200` green / `503` down).

Key env vars: `PORT`, `REFRESH_MIN`, `WOLF_PASS`, `TELEGRAM_BOT_TOKEN`,
`BOT_USERNAME`, `ADMIN_IDS`, `RUN_BOT` (set `0` on duplicate instances so only
one bot polls), `WATCHDOG_MIN`, `STALE_DATA_MIN`, `ALERT_COOLDOWN_MIN`.
`requirements.txt` is intentionally tiny (`requests` + `truststore`); everything
else is stdlib. Deploy target is Railway (TLS terminated upstream; `Procfile`).

---

## 16. How to consult it before a manual trade (recommended read order)

1. **Market weather** — overall `market_read` state + vote split. Sets the risk
   backdrop (are you trading with or against the tape?).
2. **Ranked list** for the class you're trading — verdict chip, score bar,
   regime tag (`🟢 BULL · 71% stay`), `trend_desc`.
3. **Case file** on the instrument — verdict + conviction, `price_reasoning`,
   the bull vs bear columns, the 5-component score breakdown, the regime detail,
   and a live `/news` pull.
4. **Coverage** — which broker/prop-firm to place it on, leverage, prop DD rules.
5. **Your pre-trade gate** (suggested, not in the engine): proceed only if the
   verdict aligns with the market weather, `persist` clears your threshold, `n`
   isn't tiny, `atr_pct` sits in the tradeable band, and the news tilt doesn't
   contradict the chart.

---

## 17. Honesty & limitations (must be surfaced in any client)

- **Not financial advice.** Outputs are mechanical reads / leads; verify before
  risking capital.
- **Half the score is manual and can go stale.** `catalyst / position / supply`
  are hand-dated in `signals_*.json`; always show the `generated` timestamp and
  the signal date.
- **Regime confidence scales with `n` — and is now enforced.** Below
  `MIN_N_VOTE` (8) a regime is excluded from the market vote and marked "thin";
  8–14 votes but is flagged medium-confidence; ≥15 (`MIN_N_TRUST`) is high. The
  `confidence` / `vote` fields carry this to every client.
- **News tilt is keyword-crude — and deliberately kept out of the score.** A
  directional headline count, surfaced as context only; it never moves the score
  or flips a verdict (see §9).
- **Third-party data.** Prices/calendar/rates come from free public feeds (Yahoo,
  faireconomy, global-rates) and can fail or lag; the engine degrades gracefully
  (`None` rows, cached fallbacks) rather than inventing data.

---

## 18. MT5 bridge — Markov regime gate (`markov_export.py`)

Excalibur's regime is written out for **EA Forge**-generated MT5 EAs, which can
read a regime file and gate entries to it (bull → longs, bear → shorts, sideways
→ block). This turns the desk's read into the live filter on automated trades.

**Reader contract** (the EA's `MarkovBias()`): it reads the whole file,
uppercases it, and returns `+1` if it contains `BULL`/`LONG`, `-1` if `BEAR`/
`SHORT`, else `0` (block both); a **missing file is fail-open** (no gate). So
each file holds exactly one state token plus keyword-free metadata, and the
writer hard-verifies no conflicting keyword can leak (a symbol containing
`LONG`, say, gets its metadata stripped rather than mislead the EA).

**Gate policy** (same sample-size discipline as §5): a confident directional
regime (`BULL`/`BEAR` **and** it clears the `n ≥ 8` vote gate) gates to that
direction; `SIDE`, a thin/non-voting regime, or no data all write `SIDE` →
the EA blocks both. Excalibur never emits a direction it doesn't trust, and
never leaves a stale directional file implying a trend that isn't there.

**Written each pipeline run** (from `run.main`, so on every `/refresh` and every
auto-refresh cycle):

| File | Contents |
|---|---|
| `markov_<SYMBOL>.txt` | one per instrument — the gate token the EA reads |
| `markov_regime.txt` | alias = Gold/XAUUSD, so the proven-edge EA works with its default `InpMarkovFile` |
| `markov_regime.json` | full human/debug summary (gate, real state, persist, n, confidence, vote) |

Display names map to MT5 symbols (`Gold→XAUUSD`, FX by stripping `/`, stocks by
ticker; indices/stocks are broker-dependent defaults — rename the file or point
the EA's `InpMarkovFile` at your broker's symbol if it differs).

**Output directory / config:** `$MARKOV_OUT_DIR`, else MT5 `Common\Files` under
`%APPDATA%` (Windows), else a local `./markov_out`. Set `MARKOV_EXPORT=0` to
disable. **Limitation:** the EA gates on the *last written* file, and cannot see
its age — if the desk stops running the files go stale, so run the writer on the
same cadence as the desk (it already does, via the refresh loop) and delete the
files if you take the desk offline.

## 19. Next step

With the mechanics fixed, the next step is the **mobile companion app**: a thin
PWA / React-Native client over `/data` that renders the market-weather banner,
the ranked per-class list, the tap-through case file, and the coverage panel —
plus the personal pre-trade checklist from §16. The data contract in §13 and the
API in §12 are the full interface it needs.
