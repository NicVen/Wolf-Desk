// STRUCTURAL experiments to make FX majors viable.
//
// Filtering FX entries failed out-of-sample (every rule: TRAIN good, TEST < 1.0).
// FX has BOTH a thinner gross edge (PF 1.14 vs 1.54 non-FX) AND a heavier cost
// burden (median cost/risk 0.042 vs 0.025). So change the trade GEOMETRY, not the
// entry selection:
//
//   A) STOP WIDTH sweep (1H). Wider stop => bigger risk denominator => cost is a
//      smaller fraction of R. Tests whether FX's problem is purely cost-scaling.
//   B) SWING mode (daily bars, the bot's own analyzeSwing). Daily ATR dwarfs a
//      fixed spread, so cost/risk collapses. Tests whether FX needs a higher TF.
//
// Both report TRAIN/TEST so we can tell a real structural fix from a curve fit.
//
// Run: BACKTEST=1 node experiment_fx.mjs

import https from "https";
import fs from "fs";
import path from "path";
import { analyze, analyzeSwing, PAIRS } from "../server.js";

const FX = ["EURUSD","GBPUSD","USDJPY","USDCHF","AUDUSD","NZDUSD","USDCAD","GBPJPY","EURJPY","EURGBP"];
const COSTS = {
  EURUSD: 1.5, GBPUSD: 1.5, USDJPY: 1.5, USDCHF: 1.6, AUDUSD: 1.6,
  NZDUSD: 1.8, USDCAD: 1.7, GBPJPY: 2.5, EURJPY: 2.0, EURGBP: 1.8,
  XAUUSD: 5.0, XAGUSD: 30, USOIL: 5.0, NAS100: 3.0, SPX500: 3.0,
  US30: 6.0, BTCUSD: 40, ETHUSD: 30,
};
const WIN_1H = 500, WIN_1D = 260, COOLDOWN_BARS = 4, CACHE_DIR = "./cache";

function fetchTS(symbol, interval, range) {
  return new Promise((resolve, reject) => {
    const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?interval=${interval}&range=${range}`;
    https.get(url, { headers: { "User-Agent": "Mozilla/5.0" } }, (res) => {
      let d = ""; res.on("data", c => d += c);
      res.on("end", () => {
        try {
          const j = JSON.parse(d)?.chart?.result?.[0];
          if (!j?.timestamp) return reject(new Error("no data"));
          const q = j.indicators.quote[0], out = [];
          for (let i = 0; i < j.timestamp.length; i++)
            if (q.close[i] != null && q.high[i] != null && q.low[i] != null)
              out.push({ t: j.timestamp[i], open: q.open[i], high: q.high[i], low: q.low[i], close: q.close[i], volume: q.volume?.[i] || 0 });
          resolve(out);
        } catch (e) { reject(e); }
      });
    }).on("error", reject).setTimeout(20000, function(){ this.destroy(); reject(new Error("timeout")); });
  });
}
async function cachedFetch(symbol, interval, range) {
  if (!fs.existsSync(CACHE_DIR)) fs.mkdirSync(CACHE_DIR, { recursive: true });
  const f = path.join(CACHE_DIR, `${symbol.replace(/[^A-Za-z0-9]/g,"_")}_${interval}_${range}.json`);
  try { const st = fs.statSync(f); if (Date.now()-st.mtimeMs < 12*3600*1000) return JSON.parse(fs.readFileSync(f,"utf8")); } catch {}
  const b = await fetchTS(symbol, interval, range);
  try { fs.writeFileSync(f, JSON.stringify(b)); } catch {}
  return b;
}
function resolveTrade(dir, entry, sl, tp, fwd, hold) {
  const risk = Math.abs(entry - sl); if (!(risk>0)) return null;
  const n = Math.min(hold, fwd.length);
  for (let i=0;i<n;i++){ const {high,low}=fwd[i];
    if (dir==="BUY"){ if(low<=sl) return -1; if(high>=tp) return (tp-entry)/risk; }
    else            { if(high>=sl) return -1; if(low<=tp) return (entry-tp)/risk; } }
  const ex = fwd[n-1]?.close; if (ex==null) return null;
  return (dir==="BUY" ? (ex-entry) : (entry-ex)) / risk;
}
function st(Rs){ const n=Rs.length; if(!n) return {n:0,wr:0,pf:0,sum:0,avg:0};
  const w=Rs.filter(r=>r>0), gw=w.reduce((a,b)=>a+b,0), gl=Rs.filter(r=>r<0).reduce((a,b)=>a+Math.abs(b),0);
  return { n, wr:+(100*w.length/n).toFixed(1), pf: gl>0?+(gw/gl).toFixed(2):0,
           sum:+Rs.reduce((a,b)=>a+b,0).toFixed(1), avg:+(Rs.reduce((a,b)=>a+b,0)/n).toFixed(4) }; }
const row = (lbl,a,tr,te) =>
  console.log(`${lbl.padEnd(24)} n=${String(a.n).padStart(4)} pf ${String(a.pf).padStart(5)} sum ${String(a.sum).padStart(7)} wr ${String(a.wr).padStart(5)}% | TRAIN pf ${String(tr.pf).padStart(5)} sum ${String(tr.sum).padStart(7)} | TEST pf ${String(te.pf).padStart(5)} sum ${String(te.sum).padStart(7)}`);

// ── A) 1H stop-width sweep ──────────────────────────────────────────────────────
async function expA() {
  console.log("\n=== A) STOP-WIDTH SWEEP — FX majors, 1H, RR 2:1 ===");
  console.log("k = stop distance in ATR multiples (bot baseline ~2.0). Hold 24 bars.\n");
  const sigs = [];
  for (const sym of FX) {
    const p = PAIRS.find(x => x.symbol === sym);
    const [b1h, bD] = await Promise.all([cachedFetch(p.yahoo,"1h","730d"), cachedFetch(p.yahoo,"1d","2y")]);
    const dT = bD.map(b=>b.t); let cd=-1;
    for (let t=WIN_1H; t<b1h.length-1; t++) {
      if (t<cd) continue;
      const ts=b1h[t].t; let dEnd=0; while(dEnd<dT.length&&dT[dEnd]<=ts) dEnd++;
      if (dEnd<60) continue;
      let r; try { r = analyze(sym, b1h.slice(t-WIN_1H,t+1), bD.slice(Math.max(0,dEnd-WIN_1D),dEnd), p.pip, p.markovThr||0.010); } catch { continue; }
      if (r?.setup?.quality !== "VALID") continue;
      sigs.push({ sym, t, ts, dir:r.setup.direction, entry:r.setup.entry, atr:r.ATR, pip:p.pip, b1h });
      cd = t + COOLDOWN_BARS;
    }
  }
  const tsL = sigs.map(s=>s.ts).sort((a,b)=>a-b); const split = tsL[Math.floor(tsL.length/2)];
  console.log(`collected ${sigs.length} FX signals; split ${new Date(split*1000).toISOString().slice(0,10)}\n`);
  for (const k of [2,3,4,6,8]) {
    const all=[],tr=[],te=[];
    for (const s of sigs) {
      const risk = s.atr*k;
      const sl = s.dir==="BUY" ? s.entry-risk : s.entry+risk;
      const tp = s.dir==="BUY" ? s.entry+2*risk : s.entry-2*risk;
      const g = resolveTrade(s.dir, s.entry, sl, tp, s.b1h.slice(s.t+1), 24);
      if (g==null) continue;
      const costR = (COSTS[s.sym]*s.pip)/risk;
      const net = g - costR;
      all.push(net); (s.ts<split?tr:te).push(net);
    }
    row(`k=${k} ATR stop`, st(all), st(tr), st(te));
  }
}

// ── B) daily swing mode ─────────────────────────────────────────────────────────
async function expB() {
  console.log("\n\n=== B) SWING MODE — FX majors on DAILY bars (bot's analyzeSwing) ===");
  console.log("Hold in DAYS. Cost/risk collapses because daily ATR >> spread.\n");
  const sigs = [];
  for (const sym of FX) {
    const p = PAIRS.find(x => x.symbol === sym);
    const [bD, bW] = await Promise.all([cachedFetch(p.yahoo,"1d","5y"), cachedFetch(p.yahoo,"1wk","5y")]);
    const wT = bW.map(b=>b.t); let cd=-1;
    for (let t=260; t<bD.length-1; t++) {
      if (t<cd) continue;
      const ts=bD[t].t; let wEnd=0; while(wEnd<wT.length&&wT[wEnd]<=ts) wEnd++;
      if (wEnd<30) continue;
      let r; try { r = analyzeSwing(sym, bD.slice(Math.max(0,t-260),t+1), bW.slice(Math.max(0,wEnd-200),wEnd), p.pip, p.markovThr||0.010); } catch { continue; }
      if (r?.setup?.quality !== "VALID") continue;
      sigs.push({ sym, t, ts, dir:r.setup.direction, entry:r.setup.entry, sl:r.setup.sl, tp:r.setup.tp1, pip:p.pip, bD });
      cd = t + 2;   // 2-day cooldown
    }
  }
  if (!sigs.length) { console.log("no swing signals"); return; }
  const tsL = sigs.map(s=>s.ts).sort((a,b)=>a-b); const split = tsL[Math.floor(tsL.length/2)];
  console.log(`collected ${sigs.length} FX swing signals; split ${new Date(split*1000).toISOString().slice(0,10)}\n`);
  for (const hold of [5,10,20,40]) {
    const all=[],tr=[],te=[],gross=[];
    for (const s of sigs) {
      const g = resolveTrade(s.dir, s.entry, s.sl, s.tp, s.bD.slice(s.t+1), hold);
      if (g==null) continue;
      const risk = Math.abs(s.entry-s.sl);
      const costR = (COSTS[s.sym]*s.pip)/risk;
      const net = g - costR;
      gross.push(g); all.push(net); (s.ts<split?tr:te).push(net);
    }
    const g = st(gross);
    row(`hold ${hold}d`, st(all), st(tr), st(te));
    console.log(`${"".padEnd(24)} (gross pf ${g.pf} sum ${g.sum} | median costR shown by gap vs net)`);
  }
}

await expA();
await expB();
process.exit(0);
