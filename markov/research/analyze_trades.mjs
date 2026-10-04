// Offline slicer for backtest_trades.json — finds WHY certain pairs/conditions
// lose, without re-running the walk-forward. Read-only analysis.
//
// Run: node analyze_trades.mjs [hold]

import fs from "fs";

const HOLD = process.argv[2] ? parseInt(process.argv[2]) : 24;
const FX = ["EURUSD","GBPUSD","USDJPY","USDCHF","AUDUSD","NZDUSD","USDCAD","GBPJPY","EURJPY","EURGBP"];
const NONFX = ["XAUUSD","XAGUSD","USOIL","NAS100","SPX500","US30","BTCUSD","ETHUSD"];

const all = JSON.parse(fs.readFileSync("backtest_trades.json", "utf8"));
const T = all.filter(t => t.hold === HOLD);
const tsList = T.map(t => t.ts).sort((a,b)=>a-b);
const splitTs = tsList[Math.floor(tsList.length/2)];

function st(rows, key = "rNet") {
  const Rs = rows.map(r => r[key]).filter(v => v != null);
  const n = Rs.length; if (!n) return { n:0, wr:0, pf:0, sum:0, avg:0 };
  const w = Rs.filter(r=>r>0), gw = w.reduce((a,b)=>a+b,0);
  const gl = Rs.filter(r=>r<0).reduce((a,b)=>a+Math.abs(b),0);
  return { n, wr:+(100*w.length/n).toFixed(1), pf: gl>0?+(gw/gl).toFixed(2):0,
           sum:+Rs.reduce((a,b)=>a+b,0).toFixed(1), avg:+(Rs.reduce((a,b)=>a+b,0)/n).toFixed(4) };
}
const show = (label, rows) => {
  const s = st(rows), g = st(rows, "rGross");
  console.log(`${label.padEnd(26)} n=${String(s.n).padStart(5)} | NET wr ${String(s.wr).padStart(5)}% pf ${String(s.pf).padStart(5)} sum ${String(s.sum).padStart(8)} avg ${String(s.avg).padStart(8)} | gross pf ${g.pf} sum ${g.sum}`);
};

const fx = T.filter(t => FX.includes(t.pair));
const nf = T.filter(t => NONFX.includes(t.pair));

console.log(`=== HOLD ${HOLD} | ${T.length} trades ===\n`);
console.log("--- GROUP ---");
show("ALL", T); show("FX majors", fx); show("non-FX", nf);

console.log("\n--- COST BURDEN (costR = cost as fraction of risk) ---");
const cb = (lo,hi) => T.filter(t => t.costR>=lo && t.costR<hi);
for (const [lo,hi] of [[0,.02],[.02,.04],[.04,.06],[.06,.09],[.09,.15],[.15,9]])
  show(`costR ${lo}-${hi}`, cb(lo,hi));
console.log(`FX median costR   ${median(fx.map(t=>t.costR))}`);
console.log(`nonFX median costR ${median(nf.map(t=>t.costR))}`);

console.log("\n--- SESSION (UTC hour) : FX only ---");
for (const [lbl,hrs] of [["Asia 00-07",[0,7]],["London 07-12",[7,12]],["Overlap 12-16",[12,16]],["NY 16-21",[16,21]],["Late 21-24",[21,24]]])
  show(lbl, fx.filter(t=>t.hour>=hrs[0]&&t.hour<hrs[1]));

console.log("\n--- SESSION (UTC hour) : non-FX ---");
for (const [lbl,hrs] of [["Asia 00-07",[0,7]],["London 07-12",[7,12]],["Overlap 12-16",[12,16]],["NY 16-21",[16,21]],["Late 21-24",[21,24]]])
  show(lbl, nf.filter(t=>t.hour>=hrs[0]&&t.hour<hrs[1]));

console.log("\n--- ADX (trend strength) : FX only ---");
for (const [lo,hi] of [[0,20],[20,25],[25,30],[30,40],[40,999]])
  show(`ADX ${lo}-${hi}`, fx.filter(t=>t.adx>=lo&&t.adx<hi));

console.log("\n--- CONFLUENCE diff (|bull-bear|) : FX only ---");
for (const [lo,hi] of [[0,6],[6,8],[8,10],[10,13],[13,999]])
  show(`diff ${lo}-${hi}`, fx.filter(t=>t.diff>=lo&&t.diff<hi));

console.log("\n--- ATR%% of price : FX only ---");
for (const [lo,hi] of [[0,.05],[.05,.08],[.08,.12],[.12,.2],[.2,99]])
  show(`atr%% ${lo}-${hi}`, fx.filter(t=>t.atrPct>=lo&&t.atrPct<hi));

console.log("\n--- MARKOV regime : FX only ---");
for (const rg of ["Bull","Bear","Sideways"]) show(`regime ${rg}`, fx.filter(t=>t.regime===rg));

console.log("\n--- DIRECTION vs regime agreement : FX only ---");
show("BUY in Bull", fx.filter(t=>t.dir==="BUY"&&t.regime==="Bull"));
show("BUY in Bear", fx.filter(t=>t.dir==="BUY"&&t.regime==="Bear"));
show("SELL in Bear", fx.filter(t=>t.dir==="SELL"&&t.regime==="Bear"));
show("SELL in Bull", fx.filter(t=>t.dir==="SELL"&&t.regime==="Bull"));
show("BUY in Sideways", fx.filter(t=>t.dir==="BUY"&&t.regime==="Sideways"));
show("SELL in Sideways", fx.filter(t=>t.dir==="SELL"&&t.regime==="Sideways"));

console.log("\n--- TREND structure : FX only ---");
for (const tr of ["Uptrend","Downtrend","Ranging"]) show(`TREND ${tr}`, fx.filter(t=>t.trend===tr));

console.log("\n--- dailyBias agreement : FX only ---");
show("dir agrees w/ daily", fx.filter(t=>(t.dir==="BUY"&&t.dailyBias==="BULLISH")||(t.dir==="SELL"&&t.dailyBias==="BEARISH")));
show("dir vs daily conflict", fx.filter(t=>(t.dir==="BUY"&&t.dailyBias==="BEARISH")||(t.dir==="SELL"&&t.dailyBias==="BULLISH")));
show("daily NEUTRAL/NA", fx.filter(t=>t.dailyBias!=="BULLISH"&&t.dailyBias!=="BEARISH"));

function median(a){ if(!a.length) return 0; const s=[...a].sort((x,y)=>x-y); return +s[Math.floor(s.length/2)].toFixed(4); }

// ── candidate rule search (report TRAIN vs TEST so we can spot overfit) ──────────
console.log("\n\n=== CANDIDATE FX RULES (train/test split) ===");
const rules = {
  "baseline FX (no filter)":  t => true,
  "costR < 0.06":             t => t.costR < 0.06,
  "costR < 0.045":            t => t.costR < 0.045,
  "London+Overlap 7-16":      t => t.hour >= 7 && t.hour < 16,
  "ADX >= 25":                t => t.adx >= 25,
  "diff >= 8":                t => t.diff >= 8,
  "agrees w/ daily bias":     t => (t.dir==="BUY"&&t.dailyBias==="BULLISH")||(t.dir==="SELL"&&t.dailyBias==="BEARISH"),
  "not counter-regime":       t => !((t.dir==="BUY"&&t.regime==="Bear")||(t.dir==="SELL"&&t.regime==="Bull")),
  "costR<.06 + hrs7-16":      t => t.costR<0.06 && t.hour>=7 && t.hour<16,
  "costR<.06 + ADX>=25":      t => t.costR<0.06 && t.adx>=25,
  "costR<.06 + daily agree":  t => t.costR<0.06 && ((t.dir==="BUY"&&t.dailyBias==="BULLISH")||(t.dir==="SELL"&&t.dailyBias==="BEARISH")),
  "hrs7-16 + daily agree":    t => t.hour>=7&&t.hour<16 && ((t.dir==="BUY"&&t.dailyBias==="BULLISH")||(t.dir==="SELL"&&t.dailyBias==="BEARISH")),
  "ADX>=25 + daily agree":    t => t.adx>=25 && ((t.dir==="BUY"&&t.dailyBias==="BULLISH")||(t.dir==="SELL"&&t.dailyBias==="BEARISH")),
  "costR<.06+hrs7-16+dailyOK":t => t.costR<0.06 && t.hour>=7&&t.hour<16 && ((t.dir==="BUY"&&t.dailyBias==="BULLISH")||(t.dir==="SELL"&&t.dailyBias==="BEARISH")),
};
console.log(`${"rule".padEnd(28)} ${"ALL n/pf/sum".padEnd(24)} ${"TRAIN pf/sum".padEnd(18)} TEST pf/sum`);
for (const [name, fn] of Object.entries(rules)) {
  const sel = fx.filter(fn);
  const a = st(sel), tr = st(sel.filter(t=>t.ts<splitTs)), te = st(sel.filter(t=>t.ts>=splitTs));
  console.log(`${name.padEnd(28)} n=${String(a.n).padStart(4)} pf ${String(a.pf).padStart(5)} ${String(a.sum).padStart(7)} | ${String(tr.pf).padStart(5)} ${String(tr.sum).padStart(7)} | ${String(te.pf).padStart(5)} ${String(te.sum).padStart(7)}`);
}
