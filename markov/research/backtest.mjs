// Walk-forward backtest for the Markov signal bot.
//
// Runs the bot's REAL analyze() (imported from server.js, no copy -> no drift)
// bar-by-bar over ~2y of hourly history, with NO lookahead: at each step analyze
// only sees data up to the current bar. Signals are traded intraday/scalping --
// each position exits on TP, SL, or a time-stop (whichever comes first). One open
// position per pair at a time (mirrors real trading and removes the re-poll
// duplication that distorted the live sample).
//
// Pass 1 collects signals (hold-independent) with per-trade FEATURES; pass 2
// resolves them for each hold window. Bars are cached to ./cache so re-runs are
// fast. Every trade is dumped to backtest_trades.json for offline slicing.
//
// Reports TRAIN (first half) / TEST (second half) so an edge can be validated
// out-of-sample instead of curve-fit.
//
// Run:  BACKTEST=1 node backtest.mjs [holdBars] [maxPairs] [costMult]

import https from "https";
import fs from "fs";
import path from "path";
import { analyze, PAIRS } from "../server.js";

const RANGE_1H   = "730d";   // Yahoo's max hourly depth (~2y)
const RANGE_1D   = "2y";
const WIN_1H     = 500;      // rolling 1h window fed to analyze (~1mo, matches prod)
const WIN_1D     = 260;      // rolling daily window (~1y)
const COOLDOWN_BARS = 4;     // ~240min live cooldown, in 1h bars
const HOLD_SWEEP = process.argv[2] ? [parseInt(process.argv[2])] : [6, 12, 24];
const MAX_PAIRS  = process.argv[3] ? parseInt(process.argv[3]) : PAIRS.length;
const COST_MULT  = process.argv[4] ? parseFloat(process.argv[4]) : 1;
const CACHE_DIR  = "./cache";
const CACHE_TTL  = 12 * 3600 * 1000;   // re-fetch bars older than 12h

// ── Transaction costs — ESTIMATES for OUR feed/broker (FN) only ─────────────────
// Round-trip cost per trade, in each pair's own pip units (spread + commission +
// slippage, entry AND exit combined). These are OUR assumptions; a different
// broker will differ. Tune here or stress-test with the 3rd CLI arg (e.g. 2 = 2x).
const COSTS = {   // pip units per pair (see PAIRS for pip size)
  EURUSD: 1.5, GBPUSD: 1.5, USDJPY: 1.5, USDCHF: 1.6, AUDUSD: 1.6,
  NZDUSD: 1.8, USDCAD: 1.7, GBPJPY: 2.5, EURJPY: 2.0, EURGBP: 1.8,
  XAUUSD: 5.0, XAGUSD: 30,  USOIL: 5.0, NAS100: 3.0, SPX500: 3.0,
  US30: 6.0,  BTCUSD: 40,  ETHUSD: 30,
};
const DEFAULT_COST_PIPS = 2.0;

// Buyer/renter disclaimer — printed on every run and stored in the report.
const DISCLAIMER =
  "IMPORTANT FOR BUYERS/RENTERS: These backtest results include transaction-cost " +
  "estimates for OUR feed/broker (FN) ONLY. They do NOT reflect the spread, " +
  "commission, or slippage of YOUR broker, which will differ and can materially " +
  "change results. Keep your own broker's costs in mind. Past performance is not " +
  "indicative of future results. This is a signal tool, not financial advice, and " +
  "no returns are guaranteed.";

// ── timestamped fetch w/ disk cache ────────────────────────────────────────────
function fetchTS(symbol, interval, range) {
  return new Promise((resolve, reject) => {
    const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?interval=${interval}&range=${range}`;
    https.get(url, { headers: { "User-Agent": "Mozilla/5.0" } }, (res) => {
      let d = ""; res.on("data", c => d += c);
      res.on("end", () => {
        try {
          const j = JSON.parse(d)?.chart?.result?.[0];
          if (!j?.timestamp) { reject(new Error("no data")); return; }
          const q = j.indicators.quote[0], out = [];
          for (let i = 0; i < j.timestamp.length; i++) {
            if (q.close[i] != null && q.high[i] != null && q.low[i] != null)
              out.push({ t: j.timestamp[i], open: q.open[i], high: q.high[i],
                         low: q.low[i], close: q.close[i], volume: q.volume?.[i] || 0 });
          }
          resolve(out);
        } catch (e) { reject(e); }
      });
    }).on("error", reject).setTimeout(20000, function () { this.destroy(); reject(new Error("timeout")); });
  });
}

async function cachedFetch(symbol, interval, range) {
  if (!fs.existsSync(CACHE_DIR)) fs.mkdirSync(CACHE_DIR, { recursive: true });
  const f = path.join(CACHE_DIR, `${symbol.replace(/[^A-Za-z0-9]/g, "_")}_${interval}_${range}.json`);
  try {
    const st = fs.statSync(f);
    if (Date.now() - st.mtimeMs < CACHE_TTL) return JSON.parse(fs.readFileSync(f, "utf8"));
  } catch { /* miss */ }
  const bars = await fetchTS(symbol, interval, range);
  try { fs.writeFileSync(f, JSON.stringify(bars)); } catch { /* ignore */ }
  return bars;
}

// ── resolve one trade over forward bars: TP / SL / time-stop ────────────────────
// Returns GROSS R multiple. Same-bar TP+SL -> conservative loss.
function resolveTrade(dir, entry, sl, tp, fwd, holdBars) {
  const risk = Math.abs(entry - sl);
  if (!(risk > 0)) return null;
  const n = Math.min(holdBars, fwd.length);
  for (let i = 0; i < n; i++) {
    const { high, low } = fwd[i];
    if (dir === "BUY") {
      if (low <= sl) return -1;
      if (high >= tp) return (tp - entry) / risk;
    } else {
      if (high >= sl) return -1;
      if (low <= tp) return (entry - tp) / risk;
    }
  }
  const exit = fwd[n - 1]?.close;
  if (exit == null) return null;
  return (dir === "BUY" ? (exit - entry) : (entry - exit)) / risk;
}

// ── metrics from an array of R multiples ────────────────────────────────────────
export function stats(Rs) {
  const n = Rs.length;
  if (!n) return { trades: 0, wins: 0, winRate: 0, sumR: 0, avgR: 0, pf: 0, maxDD: 0 };
  const wins = Rs.filter(r => r > 0);
  const grossW = wins.reduce((a, b) => a + b, 0);
  const grossL = Rs.filter(r => r < 0).reduce((a, b) => a + Math.abs(b), 0);
  let eq = 0, peak = 0, maxDD = 0;
  for (const r of Rs) { eq += r; if (eq > peak) peak = eq; if (peak - eq > maxDD) maxDD = peak - eq; }
  return {
    trades: n, wins: wins.length,
    winRate: +(100 * wins.length / n).toFixed(1),
    sumR: +eq.toFixed(2), avgR: +(eq / n).toFixed(3),
    pf: grossL > 0 ? +(grossW / grossL).toFixed(2) : (grossW > 0 ? Infinity : 0),
    maxDD: +maxDD.toFixed(2),
  };
}

// ── PASS 1: collect signals for a pair (hold-independent) ───────────────────────
function collectSignals(pair, bars1h, barsD) {
  const sigs = [];
  let cooldownUntil = -1;
  const dTimes = barsD.map(b => b.t);
  const costPrice = (COSTS[pair.symbol] ?? DEFAULT_COST_PIPS) * pair.pip * COST_MULT;

  for (let t = WIN_1H; t < bars1h.length - 1; t++) {
    if (t < cooldownUntil) continue;
    const win1h = bars1h.slice(t - WIN_1H, t + 1);
    const ts = bars1h[t].t;
    let dEnd = 0; while (dEnd < dTimes.length && dTimes[dEnd] <= ts) dEnd++;
    if (dEnd < 60) continue;
    const winD = barsD.slice(Math.max(0, dEnd - WIN_1D), dEnd);

    let r;
    try { r = analyze(pair.symbol, win1h, winD, pair.pip, pair.markovThr || 0.015); }
    catch { continue; }
    const s = r?.setup;
    if (!s || s.quality !== "VALID") continue;

    const entry = s.entry, sl = s.sl, tp = s.tp1;
    const risk = Math.abs(entry - sl);
    if (!(risk > 0)) continue;

    const d = new Date(ts * 1000);
    sigs.push({
      pair: pair.symbol, t, ts,
      hour: d.getUTCHours(), dow: d.getUTCDay(),
      dir: s.direction, entry, sl, tp,
      costR: +(costPrice / risk).toFixed(4),   // cost as fraction of risk
      atrPct: +(r.ATR / r.price * 100).toFixed(3),
      adx: r.ADX, conf: r.conf, bull: r.bull, bear: r.bear,
      diff: Math.abs(r.bull - r.bear),
      regime: r.markov?.regime ?? null,
      persistence: r.markov?.persistence ?? null,
      conviction: r.markov?.conviction ?? null,
      trend: r.TREND, dailyBias: r.dailyBias, rr: s.rr,
    });
    cooldownUntil = t + COOLDOWN_BARS;
  }
  return sigs;
}

// ── PASS 2: resolve collected signals for a hold window ─────────────────────────
function resolveAll(sigs, bars1hByPair, holdBars) {
  const out = [];
  for (const s of sigs) {
    const fwd = bars1hByPair[s.pair].slice(s.t + 1);
    const g = resolveTrade(s.dir, s.entry, s.sl, s.tp, fwd, holdBars);
    if (g == null) continue;
    const gf = resolveTrade(s.dir === "BUY" ? "SELL" : "BUY",
                            s.entry, 2 * s.entry - s.sl, 2 * s.entry - s.tp, fwd, holdBars);
    out.push({ ...s, hold: holdBars,
               rGross: +g.toFixed(4),
               rNet: +(g - s.costR).toFixed(4),
               rFlipNet: gf == null ? null : +(gf - s.costR).toFixed(4) });
  }
  return out;
}

function line(label, s) {
  return `${label.padEnd(18)} ${String(s.trades).padStart(5)} tr | ${String(s.winRate).padStart(5)}% WR | PF ${String(s.pf).padStart(5)} | sumR ${String(s.sumR).padStart(9)} | avgR ${String(s.avgR).padStart(7)} | DD ${s.maxDD}R`;
}

// ── main ────────────────────────────────────────────────────────────────────────
async function main() {
  const pairs = PAIRS.slice(0, MAX_PAIRS);
  console.log(`Walk-forward backtest | ${pairs.length} pairs | hold ${HOLD_SWEEP.join("/")} bars | ~2y 1h | cost x${COST_MULT}`);
  console.log("-".repeat(78));
  console.log(DISCLAIMER.replace(/(.{1,76}\s)/g, "$1\n").trimEnd());
  console.log("-".repeat(78));

  const data = {}, bars1hByPair = {};
  for (const p of pairs) {
    try {
      const [b1h, bD] = await Promise.all([
        cachedFetch(p.yahoo, "1h", RANGE_1H),
        cachedFetch(p.yahoo, "1d", RANGE_1D),
      ]);
      if (b1h.length > WIN_1H + 50 && bD.length > 60) { data[p.symbol] = { b1h, bD }; bars1hByPair[p.symbol] = b1h; }
      else console.log(`  ${p.symbol}: insufficient data - skip`);
    } catch (e) { console.log(`  ${p.symbol}: fetch error ${e.message} - skip`); }
  }

  // PASS 1 — collect signals once
  console.log(`\nCollecting signals...`);
  let allSigs = [];
  for (const p of pairs) {
    const d = data[p.symbol]; if (!d) continue;
    const s = collectSignals(p, d.b1h, d.bD);
    allSigs.push(...s);
  }
  allSigs.sort((a, b) => a.ts - b.ts);
  console.log(`${allSigs.length} signals collected.`);

  // train/test split by TIME (median timestamp)
  const tsList = allSigs.map(s => s.ts).sort((a, b) => a - b);
  const splitTs = tsList[Math.floor(tsList.length / 2)];
  const splitDate = new Date(splitTs * 1000).toISOString().slice(0, 10);

  const report = {
    generated: new Date().toISOString(),
    disclaimer: DISCLAIMER,
    config: { WIN_1H, COOLDOWN_BARS, RANGE_1H, COST_MULT, costs_pips: COSTS },
    split: { splitDate, note: "TRAIN = first half by time, TEST = second half (out-of-sample)" },
    holds: {},
  };

  const allTrades = [];
  for (const holdBars of HOLD_SWEEP) {
    const trades = resolveAll(allSigs, bars1hByPair, holdBars);
    allTrades.push(...trades);
    const train = trades.filter(t => t.ts < splitTs);
    const test  = trades.filter(t => t.ts >= splitTs);

    const perPair = {};
    for (const p of pairs) {
      const tr = trades.filter(t => t.pair === p.symbol);
      if (tr.length) perPair[p.symbol] = {
        all:   stats(tr.map(t => t.rNet)),
        train: stats(train.filter(t => t.pair === p.symbol).map(t => t.rNet)),
        test:  stats(test .filter(t => t.pair === p.symbol).map(t => t.rNet)),
        gross: stats(tr.map(t => t.rGross)),
      };
    }
    report.holds[holdBars] = {
      net:        stats(trades.map(t => t.rNet)),
      gross:      stats(trades.map(t => t.rGross)),
      flippedNet: stats(trades.filter(t => t.rFlipNet != null).map(t => t.rFlipNet)),
      train:      stats(train.map(t => t.rNet)),
      test:       stats(test.map(t => t.rNet)),
      perPair,
    };

    const h = report.holds[holdBars];
    console.log(`\n===== HOLD ${holdBars} bars =====`);
    console.log(line("NET (all, costs)", h.net));
    console.log(line("gross (no costs)", h.gross));
    console.log(line("flipped (net)", h.flippedNet));
    console.log(line(`TRAIN <${splitDate}`, h.train));
    console.log(line(`TEST  >=${splitDate}`, h.test));
    console.log(`per-pair NET: all sumR | TRAIN sumR | TEST sumR | trades`);
    for (const p of pairs) {
      const s = perPair[p.symbol]; if (!s) continue;
      const consistent = s.train.sumR > 0 && s.test.sumR > 0 ? " OK-both" :
                         s.train.sumR < 0 && s.test.sumR < 0 ? " BAD-both" : " mixed";
      console.log(`  ${p.symbol.padEnd(8)} ${String(s.all.sumR).padStart(8)} | ${String(s.train.sumR).padStart(8)} | ${String(s.test.sumR).padStart(8)} | ${String(s.all.trades).padStart(4)}${consistent}`);
    }
  }

  fs.writeFileSync("backtest_result.json", JSON.stringify(report, null, 2));
  fs.writeFileSync("backtest_trades.json", JSON.stringify(allTrades));
  console.log(`\nWrote backtest_result.json + backtest_trades.json (${allTrades.length} trade records)`);
}

main().then(() => process.exit(0)).catch(e => { console.error(e); process.exit(1); });
