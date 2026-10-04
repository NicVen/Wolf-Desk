// VENDORED from STAALWAG-HQ/core/regime.js (canonical source of truth).
// ESM mirror for this ESM bot. Byte-identical output to the bot's former inline
// markovRegimes (golden-output proven). Edit the canonical, re-vendor here.
// Consolidation Phase 1 — one Markov engine shared across the estate.
//
// DRIFT SAFETY: this file is duplicated across railway/ and "Markov - Claude BOT/".
// Bump REGIME_CORE_VERSION on any change and keep the copies identical. Each bot
// calls selfTest() at boot; a corrupted/drifted engine fails LOUDLY and the bot
// falls back to the legacy engine instead of shipping bad regime silently.

export const REGIME_CORE_VERSION = "2.0.0";

function _matMul(A, B) {
  const n = A.length, C = Array.from({ length: n }, () => new Array(n).fill(0));
  for (let i = 0; i < n; i++) for (let k = 0; k < n; k++) for (let j = 0; j < n; j++)
    C[i][j] += A[i][k] * B[k][j];
  return C;
}
function _matPow(P, n) {
  if (n <= 1) return P;
  if (n % 2 === 0) { const h = _matPow(P, n / 2); return _matMul(h, h); }
  return _matMul(P, _matPow(P, n - 1));
}

// Exact reproduction of the bot's original markovRegimes (log-return labels,
// overlapping transition matrix, conviction, N-step forecasts, stationary).
export function markovRegimes(closes, window = 20, threshold = 0.015) {
  if (closes.length < window + 15) return null;
  const labels = [];
  for (let i = 1; i < closes.length; i++) {
    if (i < window) { labels.push(0); continue; }
    let roll = 0;
    for (let j = i - window + 1; j <= i; j++) roll += Math.log(closes[j] / closes[j - 1]);
    labels.push(roll > threshold ? 1 : roll < -threshold ? 2 : 0);
  }
  const cnt = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
  for (let i = 0; i < labels.length - 1; i++) cnt[labels[i]][labels[i + 1]]++;
  const P = cnt.map(row => {
    const s = row.reduce((a, b) => a + b, 0);
    return s > 0 ? row.map(v => v / s) : [1 / 3, 1 / 3, 1 / 3];
  });
  const cur = labels[labels.length - 1];
  const conviction = parseFloat((P[cur][1] - P[cur][2]).toFixed(3));
  const P3 = _matPow(P, 3), P5 = _matPow(P, 5);
  let pi = [1 / 3, 1 / 3, 1 / 3];
  for (let k = 0; k < 80; k++) {
    const next = [0, 0, 0];
    for (let j = 0; j < 3; j++) for (let i = 0; i < 3; i++) next[j] += pi[i] * P[i][j];
    pi = next;
  }
  return {
    regime: ["Sideways", "Bull", "Bear"][cur], regimeIdx: cur, conviction,
    persistence: parseFloat(P[cur][cur].toFixed(3)),
    forecast3: { bull: parseFloat(P3[cur][1].toFixed(3)), bear: parseFloat(P3[cur][2].toFixed(3)) },
    forecast5: { bull: parseFloat(P5[cur][1].toFixed(3)), bear: parseFloat(P5[cur][2].toFixed(3)) },
    stationary: { side: parseFloat(pi[0].toFixed(3)), bull: parseFloat(pi[1].toFixed(3)), bear: parseFloat(pi[2].toFixed(3)) },
    engine: "legacy",
  };
}

// ── markovRegimesV2 — the honest engine (Markov-2.0 fixes) ─────────────────────
// SAME output schema as markovRegimes (drop-in), SAME log-return labelling and
// per-pair threshold (so the bot's vol-calibrated markovThr stays valid), but:
//   FIX 1 stride — transition matrix from NON-overlapping windows (stride=window),
//         so consecutive windows sharing window-1 bars can't fake persistence.
//   FIX 2 verify — mean log-roll per label must order Bear < Sideways < Bull,
//         else `verified:false`.
//   forecast3/5 are now 3/5 BLOCKS ahead (each step = `window` bars), not days —
//         the statistically correct multi-step horizon for a stride matrix.
//   Adds `nSamples` + `lowSample`: stride sampling needs history. On 12mo daily
//         (~250 bars) only ~11 samples exist = unreliable. Feed >=5y daily.
export function markovRegimesV2(closes, window = 20, threshold = 0.015, stride = null) {
  stride = stride || window;
  if (closes.length < window + stride * 2) return null;

  // per-bar log-roll labels (identical rule to markovRegimes) + the roll value
  const labels = [], rolls = [];
  for (let i = window; i < closes.length; i++) {
    let roll = 0;
    for (let j = i - window + 1; j <= i; j++) roll += Math.log(closes[j] / closes[j - 1]);
    labels.push(roll > threshold ? 1 : roll < -threshold ? 2 : 0);
    rolls.push(roll);
  }
  if (labels.length < stride * 2) return null;

  // FIX 2 — verify label ordering by mean roll (idx 2=Bear, 0=Side, 1=Bull)
  const mean = {};
  for (const k of [0, 1, 2]) {
    const v = rolls.filter((_, i) => labels[i] === k);
    if (v.length) mean[k] = v.reduce((a, b) => a + b, 0) / v.length;
  }
  let verified = true;
  if (2 in mean && 0 in mean && !(mean[2] < mean[0])) verified = false;
  if (0 in mean && 1 in mean && !(mean[0] < mean[1])) verified = false;
  if (2 in mean && 1 in mean && !(mean[2] < mean[1])) verified = false;

  // FIX 1 — stride-sample so overlapping windows don't manufacture persistence
  const sampled = [];
  for (let i = 0; i < labels.length; i += stride) sampled.push(labels[i]);
  const cnt = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
  for (let i = 0; i < sampled.length - 1; i++) cnt[sampled[i]][sampled[i + 1]]++;
  const P = cnt.map(row => {
    const s = row.reduce((a, b) => a + b, 0);
    return s > 0 ? row.map(v => v / s) : [1 / 3, 1 / 3, 1 / 3];
  });

  const cur = labels[labels.length - 1];          // current regime = latest full window
  const conviction = parseFloat((P[cur][1] - P[cur][2]).toFixed(3));
  const P3 = _matPow(P, 3), P5 = _matPow(P, 5);
  let pi = [1 / 3, 1 / 3, 1 / 3];
  for (let k = 0; k < 80; k++) {
    const next = [0, 0, 0];
    for (let j = 0; j < 3; j++) for (let i = 0; i < 3; i++) next[j] += pi[i] * P[i][j];
    pi = next;
  }
  const nSamples = sampled.length;
  return {
    regime: ["Sideways", "Bull", "Bear"][cur], regimeIdx: cur, conviction,
    persistence: parseFloat(P[cur][cur].toFixed(3)),
    forecast3: { bull: parseFloat(P3[cur][1].toFixed(3)), bear: parseFloat(P3[cur][2].toFixed(3)) },
    forecast5: { bull: parseFloat(P5[cur][1].toFixed(3)), bear: parseFloat(P5[cur][2].toFixed(3)) },
    stationary: { side: parseFloat(pi[0].toFixed(3)), bull: parseFloat(pi[1].toFixed(3)), bear: parseFloat(pi[2].toFixed(3)) },
    engine: "v2", verified, nSamples, lowSample: nSamples < 20,
  };
}

// ── selfTest — boot-time integrity check (drift / bad-overwrite guard) ─────────
// Runs fixed synthetic series through both engines and asserts invariants that
// must ALWAYS hold. Returns {ok, version, fails[]}; never throws. Callers that
// intend to use v2 should fall back to legacy when ok===false.
export function selfTest() {
  const fails = [];
  const N = 600;
  const up   = Array.from({ length: N }, (_, i) => 100 * Math.pow(1.01,  i)); // strong uptrend
  const down = Array.from({ length: N }, (_, i) => 100 * Math.pow(0.99,  i)); // strong downtrend
  try {
    const Lu = markovRegimes(up, 20, 0.015), Ld = markovRegimes(down, 20, 0.015);
    const Vu = markovRegimesV2(up, 20, 0.015), Vd = markovRegimesV2(down, 20, 0.015);
    // regime index mapping must be 1=Bull, 2=Bear on both engines
    if (!Lu || Lu.regimeIdx !== 1) fails.push("legacy uptrend not Bull");
    if (!Ld || Ld.regimeIdx !== 2) fails.push("legacy downtrend not Bear");
    if (!Vu || Vu.regimeIdx !== 1) fails.push("v2 uptrend not Bull");
    if (!Vd || Vd.regimeIdx !== 2) fails.push("v2 downtrend not Bear");
    // v2 must self-verify label ordering and expose its schema
    if (Vu && Vu.verified !== true) fails.push("v2 label verify failed on clean uptrend");
    if (Vu && Vu.engine !== "v2")   fails.push("v2 engine tag missing");
    if (Vu && typeof Vu.nSamples !== "number") fails.push("v2 nSamples missing");
    // both engines expose the schema server.js reads
    for (const [name, r] of [["legacy", Lu], ["v2", Vu]]) {
      for (const k of ["regime", "regimeIdx", "conviction", "persistence", "forecast3", "forecast5", "stationary"])
        if (r && !(k in r)) fails.push(`${name} missing field ${k}`);
    }
  } catch (e) {
    fails.push("threw: " + e.message);
  }
  return { ok: fails.length === 0, version: REGIME_CORE_VERSION, fails };
}
