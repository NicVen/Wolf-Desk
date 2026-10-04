// ADAPTIVE walk-forward engine.
//
// Fixed parameters fitted to history decay: our own test showed TRAIN PF 1.34 vs
// TEST 1.17 -- the market moved. So instead of ONE tuned setting, the bot re-fits
// on a trailing window and trades the next block with that setting. No lookahead:
// every decision for block i uses only data from blocks < i.
//
// Adaptive dimensions
//   * stop width k (x ATR) and hold length      -- re-chosen each block
//   * per-pair gating                           -- mute pairs whose trailing
//                                                  record is negative, re-enable
//                                                  when they recover
//
// Honest accounting: the reported equity is the CONCATENATION of out-of-sample
// blocks only. Warmup blocks are excluded. Adaptive is compared head-to-head with
// every fixed-k baseline -- if adaptivity does not beat fixed, this says so.
//
// Run: BACKTEST=1 node adaptive.mjs

import https from "https";
import fs from "fs";
import path from "path";
import { analyze, PAIRS } from "../server.js";

const FX = ["EURUSD","GBPUSD","USDJPY","USDCHF","AUDUSD","NZDUSD","USDCAD","GBPJPY","EURJPY","EURGBP"];
const COSTS = {
  EURUSD: 1.5, GBPUSD: 1.5, USDJPY: 1.5, USDCHF: 1.6, AUDUSD: 1.6,
  NZDUSD: 1.8, USDCAD: 1.7, GBPJPY: 2.5, EURJPY: 2.0, EURGBP: 1.8,
  XAUUSD: 5.0, XAGUSD: 30, USOIL: 5.0, NAS100: 3.0, SPX500: 3.0,
  US30: 6.0, BTCUSD: 40, ETHUSD: 30,
};
const WIN_1H = 500, WIN_1D = 260, COOLDOWN_BARS = 4, CACHE_DIR = "./cache";
const KS = [2, 3, 4, 6, 8];
const HOLDS = [3, 6, 12, 24, 48];   // short holds added 2026-07: only fast exits survived the recent decay
const SIGCACHE = "adaptive_signals.json";

// ── data plumbing ───────────────────────────────────────────────────────────────
function fetchTS(symbol, interval, range) {
  return new Promise((resolve, reject) => {
    const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?interval=${interval}&range=${range}`;
    https.get(url, { headers: { "User-Agent": "Mozilla/5.0" } }, (res) => {
      let d = ""; res.on("data", c => d += c);
      res.on("end", () => { try {
        const j = JSON.parse(d)?.chart?.result?.[0];
        if (!j?.timestamp) return reject(new Error("no data"));
        const q = j.indicators.quote[0], out = [];
        for (let i = 0; i < j.timestamp.length; i++)
          if (q.close[i] != null && q.high[i] != null && q.low[i] != null)
            out.push({ t: j.timestamp[i], open: q.open[i], high: q.high[i], low: q.low[i], close: q.close[i], volume: q.volume?.[i] || 0 });
        resolve(out);
      } catch (e) { reject(e); } });
    }).on("error", reject).setTimeout(20000, function(){ this.destroy(); reject(new Error("timeout")); });
  });
}
async function cachedFetch(symbol, interval, range) {
  if (!fs.existsSync(CACHE_DIR)) fs.mkdirSync(CACHE_DIR, { recursive: true });
  const f = path.join(CACHE_DIR, `${symbol.replace(/[^A-Za-z0-9]/g,"_")}_${interval}_${range}.json`);
  try { const s = fs.statSync(f); if (Date.now()-s.mtimeMs < 12*3600*1000) return JSON.parse(fs.readFileSync(f,"utf8")); } catch {}
  const b = await fetchTS(symbol, interval, range);
  try { fs.writeFileSync(f, JSON.stringify(b)); } catch {}
  return b;
}
function resolveTrade(dir, entry, sl, tp, fwd, hold) {
  const risk = Math.abs(entry-sl); if (!(risk>0)) return null;
  const n = Math.min(hold, fwd.length);
  for (let i=0;i<n;i++){ const {high,low}=fwd[i];
    if (dir==="BUY"){ if(low<=sl) return -1; if(high>=tp) return (tp-entry)/risk; }
    else            { if(high>=sl) return -1; if(low<=tp) return (entry-tp)/risk; } }
  const ex = fwd[n-1]?.close; if (ex==null) return null;
  return (dir==="BUY" ? (ex-entry) : (entry-ex)) / risk;
}
function st(Rs){ const n=Rs.length; if(!n) return {n:0,wr:0,pf:0,sum:0,avg:0,dd:0,ret2dd:0};
  const w=Rs.filter(r=>r>0), gw=w.reduce((a,b)=>a+b,0), gl=Rs.filter(r=>r<0).reduce((a,b)=>a+Math.abs(b),0);
  let eq=0,pk=0,dd=0; for(const r of Rs){eq+=r; if(eq>pk)pk=eq; if(pk-eq>dd)dd=pk-eq;}
  return { n, wr:+(100*w.length/n).toFixed(1), pf: gl>0?+(gw/gl).toFixed(2):0,
           sum:+eq.toFixed(1), avg:+(eq/n).toFixed(4), dd:+dd.toFixed(1),
           ret2dd: dd>0?+(eq/dd).toFixed(2):0 }; }

// ── build signal table: for every signal, net R under each (k, hold) ────────────
async function buildSignals() {
  if (fs.existsSync(SIGCACHE)) {
    const age = Date.now() - fs.statSync(SIGCACHE).mtimeMs;
    if (age < 12*3600*1000) { console.log("Loading cached signal table..."); return JSON.parse(fs.readFileSync(SIGCACHE,"utf8")); }
  }
  console.log("Building signal table (all pairs, all k x hold combos)...");
  const rows = [];
  for (const p of PAIRS) {
    let b1h, bD;
    try { [b1h, bD] = await Promise.all([cachedFetch(p.yahoo,"1h","730d"), cachedFetch(p.yahoo,"1d","2y")]); }
    catch { continue; }
    if (b1h.length < WIN_1H+50 || bD.length < 60) continue;
    const dT = bD.map(b=>b.t); let cd=-1;
    for (let t=WIN_1H; t<b1h.length-1; t++) {
      if (t<cd) continue;
      const ts=b1h[t].t; let dEnd=0; while(dEnd<dT.length&&dT[dEnd]<=ts) dEnd++;
      if (dEnd<60) continue;
      let r; try { r = analyze(p.symbol, b1h.slice(t-WIN_1H,t+1), bD.slice(Math.max(0,dEnd-WIN_1D),dEnd), p.pip, p.markovThr||0.015); } catch { continue; }
      if (r?.setup?.quality !== "VALID") continue;
      const dir = r.setup.direction, entry = r.setup.entry, atr = r.ATR;
      const fwd = b1h.slice(t+1);
      const R = {};
      for (const k of KS) {
        const risk = atr*k;
        const sl = dir==="BUY" ? entry-risk : entry+risk;
        const tp = dir==="BUY" ? entry+2*risk : entry-2*risk;
        const costR = (COSTS[p.symbol]*p.pip)/risk;
        for (const h of HOLDS) {
          const g = resolveTrade(dir, entry, sl, tp, fwd, h);
          R[`${k}_${h}`] = g==null ? null : +(g-costR).toFixed(4);
        }
      }
      rows.push({ sym:p.symbol, ts, R });
      cd = t + COOLDOWN_BARS;
    }
    process.stdout.write(`  ${p.symbol} done\n`);
  }
  rows.sort((a,b)=>a.ts-b.ts);
  fs.writeFileSync(SIGCACHE, JSON.stringify(rows));
  return rows;
}

// ── walk-forward adaptive engine ────────────────────────────────────────────────
// blocks = calendar months. For block i: fit on trailing WINDOW months, trade i.
function monthKey(ts){ const d=new Date(ts*1000); return `${d.getUTCFullYear()}-${String(d.getUTCMonth()+1).padStart(2,"0")}`; }

function runAdaptive(rows, opts) {
  const { window = 6, warmup = 6, gatePairs = true, objective = "ret2dd", minTrades = 30 } = opts;
  const months = [...new Set(rows.map(r=>monthKey(r.ts)))].sort();
  const byMonth = {}; for (const r of rows) (byMonth[monthKey(r.ts)] ??= []).push(r);

  const oos = [], picks = [];
  for (let i = warmup; i < months.length; i++) {
    const trainMonths = months.slice(Math.max(0,i-window), i);
    const train = trainMonths.flatMap(m => byMonth[m] || []);
    if (train.length < minTrades) continue;

    // pick (k, hold) on trailing window
    let best = null;
    for (const k of KS) for (const h of HOLDS) {
      const key = `${k}_${h}`;
      const Rs = train.map(r=>r.R[key]).filter(v=>v!=null);
      if (Rs.length < minTrades) continue;
      const s = st(Rs);
      const score = objective==="ret2dd" ? s.ret2dd : objective==="pf" ? s.pf : s.sum;
      if (!best || score > best.score) best = { k, h, key, score, s };
    }
    if (!best) continue;

    // per-pair gating on trailing window with the chosen params
    let active = null;
    if (gatePairs) {
      active = new Set();
      const bySym = {};
      for (const r of train) { const v=r.R[best.key]; if (v!=null) (bySym[r.sym] ??= []).push(v); }
      for (const [sym, Rs] of Object.entries(bySym)) {
        if (Rs.length < 8) { active.add(sym); continue; }   // too few -> don't judge
        if (st(Rs).sum > 0) active.add(sym);
      }
      if (active.size === 0) active = null;                 // never mute everything
    }

    const test = byMonth[months[i]] || [];
    let blockSum = 0, blockN = 0;
    for (const r of test) {
      if (active && !active.has(r.sym)) continue;
      const v = r.R[best.key];
      if (v == null) continue;
      oos.push(v); blockSum += v; blockN++;
    }
    picks.push({ month: months[i], k: best.k, hold: best.h,
                 activePairs: active ? active.size : "all",
                 blockN, blockSum: +blockSum.toFixed(1) });
  }
  return { stats: st(oos), picks, oos };
}

// ── main ────────────────────────────────────────────────────────────────────────
const rows = await buildSignals();
console.log(`\n${rows.length} signals | ${[...new Set(rows.map(r=>monthKey(r.ts)))].length} months\n`);

// Baselines: every fixed (k,hold), scored over the SAME period the adaptive engine
// trades (skip warmup) so the comparison is apples-to-apples.
const months = [...new Set(rows.map(r=>monthKey(r.ts)))].sort();
const WARMUP = 6;
const evalRows = rows.filter(r => months.indexOf(monthKey(r.ts)) >= WARMUP);

console.log("=== FIXED baselines (same eval period as adaptive) ===");
const fixedResults = [];
for (const k of KS) for (const h of HOLDS) {
  const Rs = evalRows.map(r=>r.R[`${k}_${h}`]).filter(v=>v!=null);
  const s = st(Rs);
  fixedResults.push({ label:`k=${k} hold=${h}`, ...s });
}
fixedResults.sort((a,b)=>b.ret2dd-a.ret2dd);
console.log(`${"config".padEnd(16)} ${"n".padStart(5)} ${"PF".padStart(6)} ${"sumR".padStart(8)} ${"maxDD".padStart(7)} ${"ret/DD".padStart(7)} ${"WR%".padStart(6)}`);
for (const f of fixedResults.slice(0,8))
  console.log(`${f.label.padEnd(16)} ${String(f.n).padStart(5)} ${String(f.pf).padStart(6)} ${String(f.sum).padStart(8)} ${String(f.dd).padStart(7)} ${String(f.ret2dd).padStart(7)} ${String(f.wr).padStart(6)}`);
const bestFixed = fixedResults[0];

console.log("\n=== ADAPTIVE walk-forward variants (out-of-sample only) ===");
console.log(`${"variant".padEnd(38)} ${"n".padStart(5)} ${"PF".padStart(6)} ${"sumR".padStart(8)} ${"maxDD".padStart(7)} ${"ret/DD".padStart(7)} ${"WR%".padStart(6)}`);
const variants = [];
for (const window of [3, 6, 12])
  for (const gatePairs of [false, true])
    for (const objective of ["ret2dd", "pf", "sum"]) {
      const res = runAdaptive(rows, { window, warmup: WARMUP, gatePairs, objective });
      const label = `win${window}m ${objective} ${gatePairs?"+gate":"     "}`;
      variants.push({ label, res });
      const s = res.stats;
      console.log(`${label.padEnd(38)} ${String(s.n).padStart(5)} ${String(s.pf).padStart(6)} ${String(s.sum).padStart(8)} ${String(s.dd).padStart(7)} ${String(s.ret2dd).padStart(7)} ${String(s.wr).padStart(6)}`);
    }

variants.sort((a,b)=>b.res.stats.ret2dd - a.res.stats.ret2dd);
const bestAdaptive = variants[0];
console.log(`\nBest fixed   : ${bestFixed.label} -> PF ${bestFixed.pf}, sumR ${bestFixed.sum}, DD ${bestFixed.dd}, ret/DD ${bestFixed.ret2dd}`);
console.log(`Best adaptive: ${bestAdaptive.label.trim()} -> PF ${bestAdaptive.res.stats.pf}, sumR ${bestAdaptive.res.stats.sum}, DD ${bestAdaptive.res.stats.dd}, ret/DD ${bestAdaptive.res.stats.ret2dd}`);
const verdict = bestAdaptive.res.stats.ret2dd > bestFixed.ret2dd
  ? "ADAPTIVE WINS on return/drawdown."
  : "FIXED WINS -- adaptivity did NOT beat a well-chosen fixed setting. Do not ship the adaptive layer.";
console.log(`\nVERDICT: ${verdict}`);

console.log(`\n=== ${bestAdaptive.label.trim()} : what it chose each month ===`);
console.log(`${"month".padEnd(9)} ${"k".padStart(2)} ${"hold".padStart(5)} ${"pairs".padStart(6)} ${"n".padStart(4)} ${"sumR".padStart(8)}`);
for (const p of bestAdaptive.res.picks)
  console.log(`${p.month.padEnd(9)} ${String(p.k).padStart(2)} ${String(p.hold).padStart(5)} ${String(p.activePairs).padStart(6)} ${String(p.blockN).padStart(4)} ${String(p.blockSum).padStart(8)}`);

fs.writeFileSync("adaptive_result.json", JSON.stringify({
  generated: new Date().toISOString(),
  bestFixed, bestAdaptive: { label: bestAdaptive.label.trim(), stats: bestAdaptive.res.stats, picks: bestAdaptive.res.picks },
  allFixed: fixedResults, allAdaptive: variants.map(v=>({label:v.label.trim(), stats:v.res.stats})),
  verdict,
}, null, 2));
console.log("\nWrote adaptive_result.json");
process.exit(0);
