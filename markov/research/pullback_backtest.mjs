// pullback_backtest.mjs — test the fix hypothesis honestly.
//
// Hypothesis: the live bot loses because its bias is trend-following but it
// ENTERS AT MARKET (often near resistance = the top of the swing). The fix:
// keep the bot's own direction call, but enter on a PULLBACK to the level —
// buy support in a bullish setup, sell resistance in a bearish one.
//
// This reuses the bot's REAL pipeline (analyze/PAIRS/yahooFetch via BACKTEST=1),
// so there is no re-implementation drift. For every bar where analyze() emits a
// VALID setup it simulates two trades forward on the same bars:
//    BASELINE  = the bot's actual market entry  (should reproduce the loss)
//    PULLBACK  = limit at nearS (long) / nearR (short), SL 1*ATR beyond, 2R TP
// Walk-forward split into thirds; per-trade R dumped for DSR in python.
//
// Run:  node pullback_backtest.mjs   (writes pullback_bt.json)
process.env.BACKTEST = "1";
import fs from "fs";

const SRV = "file:///C:/Users/nvent/OneDrive/Desktop/CLAUDE/Projects/Markov%20-%20Claude%20BOT/server.js";
const { analyze, PAIRS, yahooFetch } = await import(SRV);

const WARMUP = 260;        // bars before we trust the indicators/markov
const FILL_WINDOW = 24;    // bars a pullback limit has to fill (≈1 day hourly)
const RES_WINDOW = 160;    // bars to resolve TP/SL after fill
const STEP = 1;            // evaluate every bar

// Resolve a bracket forward from bar `start`: which of SL/TP prints first?
function resolve(bars, start, dir, sl, tp) {
  for (let k = start; k < Math.min(bars.length, start + RES_WINDOW); k++) {
    const b = bars[k];
    if (dir === "BUY") {
      if (b.low <= sl) return "LOSS";
      if (b.high >= tp) return "WIN";
    } else {
      if (b.high >= sl) return "LOSS";
      if (b.low <= tp) return "WIN";
    }
  }
  return null; // unresolved in window
}

async function backtestPair(p) {
  let hourly, daily;
  try {
    hourly = await yahooFetch(p.yahoo, "60m", "3mo");
    daily = await yahooFetch(p.yahoo, "1d", "1y");
  } catch { return []; }
  if (!hourly || hourly.length < WARMUP + 60) return [];

  const trades = [];
  for (let i = WARMUP; i < hourly.length - 1; i += STEP) {
    let r;
    try { r = analyze(p.symbol, hourly.slice(0, i + 1), daily, p.pip); }
    catch { continue; }
    const su = r && r.setup;
    if (!su || su.quality !== "VALID") continue;

    const dir = su.direction;          // BUY / SELL
    const ATR = r.ATR;
    if (!ATR || ATR <= 0) continue;

    // BASELINE — bot's own market entry
    const baseRes = resolve(hourly, i + 1, dir, su.sl, su.tp1);
    let baseR = null;
    if (baseRes) {
      const rr = Math.abs(su.tp1 - su.entry) / Math.max(1e-9, Math.abs(su.entry - su.sl));
      baseR = baseRes === "WIN" ? rr : -1;
    }

    // PULLBACK — limit at the level, 1*ATR stop beyond, 2R target
    let pbR = null, filled = false;
    const level = dir === "BUY" ? r.nearS : r.nearR;
    if (level) {
      const slPb = dir === "BUY" ? level - ATR : level + ATR;
      const tpPb = dir === "BUY" ? level + 2 * ATR : level - 2 * ATR;
      // find fill within FILL_WINDOW
      for (let f = i + 1; f < Math.min(hourly.length, i + 1 + FILL_WINDOW); f++) {
        const b = hourly[f];
        const hit = dir === "BUY" ? b.low <= level : b.high >= level;
        if (hit) {
          filled = true;
          const res = resolve(hourly, f + 1, dir, slPb, tpPb);
          if (res) pbR = res === "WIN" ? 2.0 : -1.0;
          break;
        }
      }
    }

    trades.push({ pair: p.symbol, i, dir, level: level || null,
                  baseR, pbR, filled });
  }
  return trades;
}

const all = [];
for (const p of PAIRS) {
  process.stdout.write(`  ${p.symbol}… `);
  const t = await backtestPair(p);
  process.stdout.write(`${t.length} valid setups\n`);
  for (const x of t) all.push({ ...x, idxSpan: null });
}

// stats helper
const stat = (rs) => {
  const c = rs.filter(x => x != null);
  const w = c.filter(x => x > 0).length;
  const net = c.reduce((a, b) => a + b, 0);
  return { n: c.length, wins: w,
           wr: c.length ? +(100 * w / c.length).toFixed(1) : 0,
           net_r: +net.toFixed(2),
           exp_r: c.length ? +(net / c.length).toFixed(3) : 0 };
};

const baseR = all.map(t => t.baseR);
const pbAll = all.filter(t => t.pbR != null);   // filled + resolved
const pbR = pbAll.map(t => t.pbR);

// walk-forward: split filled pullback trades into thirds by global order
const ordered = all.filter(t => t.pbR != null);
const third = Math.max(1, Math.ceil(ordered.length / 3));
const wf = [0, 1, 2].map(k => {
  const seg = ordered.slice(k * third, (k + 1) * third).map(t => t.pbR);
  const s = stat(seg);
  return { period: `P${k + 1}`, ...s };
});

const out = {
  generated: new Date().toISOString(),
  pairs: PAIRS.length,
  total_valid_setups: all.length,
  baseline_market_entry: stat(baseR),
  pullback_entry: {
    resolved: pbAll.length,
    no_fill: all.filter(t => t.level && !t.filled).length,
    ...stat(pbR),
  },
  walk_forward_thirds: wf,
  months_positive: wf.filter(w => w.exp_r > 0).length,
  pb_returns: pbR,          // for DSR in python
  base_returns: baseR.filter(x => x != null),
};
fs.writeFileSync("pullback_bt.json", JSON.stringify(out, null, 2));

console.log("\nBASELINE (market entry):", JSON.stringify(out.baseline_market_entry));
console.log("PULLBACK (level entry) :", JSON.stringify(out.pullback_entry));
console.log("walk-forward:", wf.map(w => `${w.period} ${w.wr}%/${w.exp_r}R`).join("  "));
console.log("thirds positive:", out.months_positive, "/ 3");
