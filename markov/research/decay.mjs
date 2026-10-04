// decay.mjs — month-by-month decomposition of the k=6/hold=24 config.
// Answers: is the recent decay broad, pair-specific, FX-specific, or regime-specific?
// Usage: node decay.mjs [k] [hold]
import fs from "fs";

const K = process.argv[2] || "6";
const HOLD = process.argv[3] || "24";
const KEY = `${K}_${HOLD}`;

const sigs = JSON.parse(fs.readFileSync("./adaptive_signals.json", "utf8"));
const list = Object.values(sigs).filter((s) => s.R && s.R[KEY] !== undefined);

const FX = new Set([
  "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "NZDUSD", "USDCAD",
  "EURGBP", "EURJPY", "GBPJPY", "AUDJPY", "EURAUD",
]);

const month = (ts) => new Date(ts * 1000).toISOString().slice(0, 7);

function stats(rows) {
  const n = rows.length;
  if (!n) return { n: 0 };
  const win = rows.filter((r) => r.R[KEY] > 0);
  const gp = win.reduce((a, r) => a + r.R[KEY], 0);
  const gl = rows.filter((r) => r.R[KEY] <= 0).reduce((a, r) => a - r.R[KEY], 0);
  const sum = rows.reduce((a, r) => a + r.R[KEY], 0);
  return {
    n,
    sumR: +sum.toFixed(1),
    wr: +((win.length / n) * 100).toFixed(1),
    pf: gl ? +(gp / gl).toFixed(2) : Infinity,
    avgR: +(sum / n).toFixed(3),
  };
}

const byMonth = new Map();
for (const s of list) {
  const m = month(s.ts);
  if (!byMonth.has(m)) byMonth.set(m, []);
  byMonth.get(m).push(s);
}
const months = [...byMonth.keys()].sort();

console.log(`\n=== MONTHLY, k=${K} hold=${HOLD} (all pairs) ===`);
console.log("month    |    n |   sumR |  PF  |  WR% | FX sumR | nonFX sumR");
for (const m of months) {
  const rows = byMonth.get(m);
  const a = stats(rows);
  const fx = stats(rows.filter((r) => FX.has(r.sym)));
  const nf = stats(rows.filter((r) => !FX.has(r.sym)));
  console.log(
    `${m}  | ${String(a.n).padStart(4)} | ${String(a.sumR).padStart(6)} | ` +
      `${String(a.pf).padStart(4)} | ${String(a.wr).padStart(4)} | ` +
      `${String(fx.sumR ?? 0).padStart(7)} | ${String(nf.sumR ?? 0).padStart(10)}`
  );
}

// last-N vs prior split
for (const N of [3, 5, 6]) {
  const recent = months.slice(-N);
  const prior = months.slice(0, -N);
  const rl = list.filter((s) => recent.includes(month(s.ts)));
  const pl = list.filter((s) => prior.includes(month(s.ts)));
  console.log(
    `\n--- last ${N}m (${recent[0]}..${recent.at(-1)}) vs prior ---\n` +
      `  recent: ${JSON.stringify(stats(rl))}\n` +
      `  prior : ${JSON.stringify(stats(pl))}`
  );
}

// per-pair recent vs prior (5m split)
const recent5 = months.slice(-5);
const isRecent = (s) => recent5.includes(month(s.ts));
const pairs = [...new Set(list.map((s) => s.sym))].sort();
console.log(`\n=== PER PAIR: prior vs last 5m (${recent5[0]}..${recent5.at(-1)}) ===`);
console.log("pair     | prior n/sumR/PF        | recent n/sumR/PF       | delta sumR");
const rows = [];
for (const p of pairs) {
  const pr = stats(list.filter((s) => s.sym === p && !isRecent(s)));
  const re = stats(list.filter((s) => s.sym === p && isRecent(s)));
  rows.push({ p, pr, re, d: (re.sumR ?? 0) });
}
rows.sort((a, b) => a.d - b.d);
for (const { p, pr, re } of rows) {
  console.log(
    `${p.padEnd(8)} | ${String(pr.n).padStart(4)} ${String(pr.sumR).padStart(7)} ${String(pr.pf).padStart(5)} | ` +
      `${String(re.n).padStart(4)} ${String(re.sumR).padStart(7)} ${String(re.pf).padStart(5)} | ` +
      `${String(((re.sumR ?? 0) - (pr.sumR ?? 0) * (re.n / Math.max(pr.n, 1))).toFixed(1)).padStart(7)}`
  );
}

// does signal COUNT or signal QUALITY drive it?
console.log(`\n=== per-month avg R (quality) vs count (volume) ===`);
for (const m of months) {
  const a = stats(byMonth.get(m));
  console.log(`${m}  n=${String(a.n).padStart(4)}  avgR=${String(a.avgR).padStart(7)}`);
}
