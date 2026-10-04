# Markov 18-pair signal bot

Old copy still posts daily through @Staalwag_bot (another copy became Signal
Engine v2, "My Trading Bot", on 17 Aug 2026). The fixed version below replaces it,
as a private paper test until it proves itself. Moved here from the PC folder `Markov - Claude BOT`
(it used to run on Railway / the PC on port 8095). It now runs on the VPS next
to the other desks as `markov-bot` (port 8783), set up once with
`sudo bash deploy/markov-setup.sh`, then kept current by auto-ship.

## How calls work (Oct 2026)

- **One post per trade idea.** A pair with an open call stays silent until that
  call closes. A flip in direction closes the old call at market first.
  (Before: the same call was re-posted every scan, about 5x per idea.)
- **Exits are the ones the July walk-forward picked** (`research/adaptive.mjs`,
  HQ `MARKOV_BOT_STATUS.md` §8): stop 6×ATR(1H), target 2R, and a 12-hour
  time-stop that closes at market. Every close is posted with its R result.
- **EURUSD and EURGBP are dropped** (negative in both test halves).
- On the July data these rules score PF 1.24 in both halves (+0.035R per call,
  ~2,360 calls over 2 years) and PF 1.19 in the last 90 days. Thin: it must
  prove itself forward before it is sold or called proven.
- **Paper test first:** `PAPER_TEST=true` labels every post. Go public only
  after 30 calls at PF >= 1.3, all visible in HQ.
- Call logic lives in `calls.mjs` (tested: `npm test`). Signal selection in
  `analyze()` is unchanged.
- Record: `https://staalwag.com/markov/signals.json` (every call, open and
  closed, with its result). STAALWAG HQ reads it.

Settings (`/etc/markov-bot.env`): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
`PAPER_TEST`, `STOP_ATR_K` (6), `TARGET_R` (2), `HOLD_HOURS` (12),
`DROP_PAIRS` (EURUSD,EURGBP), `SCAN_SUMMARY` (off), `WEBHOOK_ENABLED` (off).

Folders: `research/` (backtests; run from inside it, Yahoo needed),
`tradingview/` (Pine scripts), `windows/` (old PC launcher / Railway deploy),
`v2_research/` (Python v2 engine experiments).

---

## Original notes
Claude Trading Bot with Markov Regime Model integrated. Scans 18 pairs every 15 min via Yahoo Finance, sends signals to Telegram.

## What's new vs the original bot

The Markov regime model is built directly into `server.js`. For every pair, before sending a Telegram signal, the bot now:

1. **Labels the market regime** — Bull / Bear / Sideways — from the 20-day rolling log-return on daily bars
2. **Builds a 3x3 transition matrix** — how often Bull stays Bull, Bull flips to Bear, etc.
3. **Scores each trade** — Bull regime adds +3 to the bull score; Bear regime adds +3 to the bear score; strong conviction (>0.5) adds +2
4. **Filters bad setups** — if the regime is persistently against your trade direction (>80% sticky) the setup is marked FILTERED. Same if the 3-bar ahead forecast is >55% against you.
5. **Shows regime in Telegram** — every signal now shows the current regime, conviction, and persistence

## Telegram signal example

```
=== XAUUSD - BUY | SWING | High Confidence ===
Entry:    2342.50
Stop:     2318.20  (-243.0 pips)
TP1:      2391.10 (+486.0 pips)
TP2:      2415.80 (+733.0 pips)
R:R:      1:2.0
---
Trend:  Uptrend | ADX: 28.4
RSI:    58.3 | MACD: +0.000124
Daily:  BULLISH
Regime: Bull (conviction +0.72, persist 84%)
EMA50:  2301.20 | EMA200: 2198.40
Volume: HIGH
Sat, 24 May 2026 04:15:00 GMT
```

## Pairs and thresholds

| Asset class     | Examples                      | Markov threshold |
|-----------------|-------------------------------|-----------------|
| Forex majors    | EURUSD, GBPUSD, USDJPY, etc.  | 1.0%            |
| Gold            | XAUUSD                        | 1.5%            |
| Commodities     | XAGUSD, USOIL                 | 2.0%            |
| Indices         | NAS100, SPX500, US30          | 2.0%            |
| Crypto          | BTCUSD, ETHUSD                | 3.0%            |

## Setup

1. Copy `.env.example` → `.env` and fill in your credentials (same as `config.json` in the CLAUDE folder)
2. Run `npm install`
3. Test locally: `node server.js`
4. Deploy: run `deploy.bat` or `railway up` from this folder

## Environment variables (Railway dashboard)

| Variable            | Value                          |
|---------------------|-------------------------------|
| TELEGRAM_BOT_TOKEN  | From config.json in CLAUDE folder |
| TELEGRAM_CHAT_ID    | From config.json in CLAUDE folder |
| SCAN_INTERVAL_MIN   | 15                            |
| QUIET_INTERVAL_MIN  | 60                            |

## Telegram commands

| Command           | What it does                              |
|-------------------|-------------------------------------------|
| `/scan`           | Manual scan of all 18 pairs now           |
| `/analyze XAUUSD` | Deep analysis of one pair (includes regime)|
| `/status`         | Uptime, last scan, next scan              |
| `/stop`           | Pause auto-scans                          |
| `/resume`         | Resume auto-scans                         |
| `/last`           | Results from the last scan                |
| `/pairs`          | Full list of monitored pairs              |

## Files

| File            | Purpose                                          |
|-----------------|--------------------------------------------------|
| `server.js`     | Main bot — Markov + all indicators + Telegram    |
| `package.json`  | Node.js project config                           |
| `.env.example`  | Environment variable template                    |
| `deploy.bat`    | One-click Railway deployment                     |
| `pine-alert.pine` | TradingView webhook alert template             |

## Architecture

- Yahoo Finance v8 API → 1H bars (intraday) + daily bars (swing + Markov) + weekly bars (MTF)
- Markov regime runs on daily bars for both intraday and swing analysis
- Scoring: RSI, EMA50/200, MACD, ADX, structure, patterns, RSI divergence, liquidity sweeps, volume, Markov regime + conviction
- Quality gate: R:R ≥ 1.5, ADX > 20 (intraday) / 18 (swing), no MTF conflict, no Markov conflict, no adverse 3-bar forecast
- Signals fire via Telegram Bot API
