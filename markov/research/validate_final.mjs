// FINAL VALIDATION: stop-width (k x ATR) sweep across ALL 18 pairs.
//
// Established so far:
//   * entry FILTERS on FX all failed out-of-sample (curve fits)
//   * widening the FX stop improved BOTH halves, monotonically (structural)
// Open question answered here: does a wider stop help every pair, or only FX?
//
// Reports FX / non-FX / whole portfolio with TRAIN vs TEST at each k.
// Run: BACKTEST=1 node validate_final.mjs

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
const WIN_1H = 500, WIN_1D = 260, COOLDOWN_BARS = 4, HOLD = 24, CACHE_DIR = "./cache";
const KS = [2, 3, 4, 6, 8];

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
function st(Rs){ const n=Rs.length; if(!n) return {n:0,wr:0,pf:0,sum:0,avg:0,dd:0};
  const w=Rs.filter(r=>r>0), gw=w.reduce((a,b)=>a+b,0), gl=Rs.filter(r=>r<0).reduce((a,b)=>a+Math.abs(b),0);
  let eq=0,pk=0,dd=0; for(const r of Rs){eq+=r; if(eq>pk)pk=eq; if(pk-eq>dd)dd=pk-eq;}
  return { n, wr:+(100*w.length/n).toFixed(1), pf: gl>0?+(gw/gl).toFixed(2):0,
           sum:+eq.toFixed(1), avg:+(eq/n).toFixed(4), dd:+dd.toFixed(1) }; }

const sigs = [];
console.log("Collecting signals across all 18 pairs (cached bars)...");
for (const p of PAIRS) {
  let b1h, bD;
  try { [b1h, bD] = await Promise.all([cachedFetch(p.yahoo,"1h","730d"), cachedFetch(p.yahoo,"1d","2y")]); }
  catch (e) { console.log(`  ${p.symbol}: ${e.message} - skip`); continue; }
  if (b1h.length < WIN_1H+50 || bD.length < 60) { console.log(`  ${p.symbol}: thin data - skip`); continue; }
  const dT = bD.map(b=>b.t); let cd=-1;
  for (let t=WIN_1H; t<b1h.length-1; t++) {
    if (t<cd) continue;
    const ts=b1h[t].t; let dEnd=0; while(dEnd<dT.length&&dT[dEnd]<=ts) dEnd++;
    if (dEnd<60) continue;
    let r; try { r = analyze(p.symbol, b1h.slice(t-WIN_1H,t+1), bD.slice(Math.max(0,dEnd-WIN_1D),dEnd), p.pip, p.markovThr||0.015); } catch { continue; }
    if (r?.setup?.quality !== "VALID") continue;
    sigs.push({ sym:p.symbol, t, ts, dir:r.setup.direction, entry:r.setup.entry, atr:r.ATR, pip:p.pip, b1h });
    cd = t + COOLDOWN_BARS;
  }
}
const tsL = sigs.map(s=>s.ts).sort((a,b)=>a-b);
const split = tsL[Math.floor(tsL.length/2)];
console.log(`${sigs.length} signals | split ${new Date(split*1000).toISOString().slice(0,10)} | hold ${HOLD} bars | RR 2:1\n`);

const out = {};
for (const k of KS) {
  const g = { FX:{all:[],tr:[],te:[]}, NON:{all:[],tr:[],te:[]}, ALL:{all:[],tr:[],te:[]} };
  const perPair = {};
  for (const s of sigs) {
    const risk = s.atr*k;
    const sl = s.dir==="BUY" ? s.entry-risk : s.entry+risk;
    const tp = s.dir==="BUY" ? s.entry+2*risk : s.entry-2*risk;
    const gr = resolveTrade(s.dir, s.entry, sl, tp, s.b1h.slice(s.t+1), HOLD);
    if (gr==null) continue;
    const net = gr - (COSTS[s.sym]*s.pip)/risk;
    const grp = FX.includes(s.sym) ? "FX" : "NON";
    for (const key of [grp, "ALL"]) { g[key].all.push(net); (s.ts<split?g[key].tr:g[key].te).push(net); }
    (perPair[s.sym] ??= {all:[],tr:[],te:[]}).all.push(net);
    (s.ts<split ? perPair[s.sym].tr : perPair[s.sym].te).push(net);
  }
  out[k] = { g, perPair };
  console.log(`--- k=${k} x ATR stop ---`);
  for (const key of ["FX","NON","ALL"]) {
    const a=st(g[key].all), tr=st(g[key].tr), te=st(g[key].te);
    console.log(`  ${key.padEnd(4)} n=${String(a.n).padStart(5)} pf ${String(a.pf).padStart(5)} sum ${String(a.sum).padStart(7)} wr ${String(a.wr).padStart(5)}% DD ${String(a.dd).padStart(6)} | TRAIN pf ${String(tr.pf).padStart(5)} | TEST pf ${String(te.pf).padStart(5)} sum ${String(te.sum).padStart(7)}`);
  }
}

// per-pair at the chosen k, showing train/test consistency
const BEST = 6;
console.log(`\n=== PER-PAIR at k=${BEST} (TRAIN sum | TEST sum | verdict) ===`);
const pp = out[BEST].perPair;
const keep = [], drop = [];
for (const p of PAIRS) {
  const d = pp[p.symbol]; if (!d) continue;
  const a=st(d.all), tr=st(d.tr), te=st(d.te);
  const ok = tr.sum>0 && te.sum>0;
  const bad = tr.sum<0 && te.sum<0;
  const verdict = ok ? "KEEP (both+)" : bad ? "DROP (both-)" : "mixed";
  if (ok) keep.push(p.symbol); if (bad) drop.push(p.symbol);
  console.log(`  ${p.symbol.padEnd(8)} n=${String(a.n).padStart(4)} pf ${String(a.pf).padStart(5)} | ${String(tr.sum).padStart(7)} | ${String(te.sum).padStart(7)} | ${verdict}`);
}
console.log(`\nboth-halves positive: ${keep.join(", ") || "none"}`);
console.log(`both-halves negative: ${drop.join(", ") || "none"}`);

fs.writeFileSync("validate_final.json", JSON.stringify({
  generated: new Date().toISOString(), hold: HOLD, split: new Date(split*1000).toISOString(),
  summary: Object.fromEntries(Object.entries(out).map(([k,v])=>[k,{
    FX:{all:st(v.g.FX.all),train:st(v.g.FX.tr),test:st(v.g.FX.te)},
    NON:{all:st(v.g.NON.all),train:st(v.g.NON.tr),test:st(v.g.NON.te)},
    ALL:{all:st(v.g.ALL.all),train:st(v.g.ALL.tr),test:st(v.g.ALL.te)},
  }])), keep, drop,
}, null, 2));
console.log("\nWrote validate_final.json");
process.exit(0);
