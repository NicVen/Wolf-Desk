import express from "express";
import https   from "https";
import fs      from "fs";
import { markovRegimes, markovRegimesV2, selfTest, REGIME_CORE_VERSION } from "./regime-core.mjs";
import { decide, resolveCall, fmtClose, DROP_PAIRS, STOP_ATR_K, TARGET_R, HOLD_HOURS } from "./calls.mjs";

// Markov engine switch (mirrors railway/server.js). Default "legacy" = ZERO
// behaviour change. MARKOV_ENGINE=v2 uses the honest stride-sampled + verified
// engine. DRIFT SAFETY: boot self-test; if it fails, v2 is disabled and the bot
// falls back to legacy loudly rather than shipping bad regime silently.
const _requestedEngine = (process.env.MARKOV_ENGINE || "legacy").toLowerCase();
const _selfTest = selfTest();
if (!_selfTest.ok)
  console.error(`[regime-core] SELF-TEST FAILED v${_selfTest.version}: ${_selfTest.fails.join("; ")}`);
if (_requestedEngine === "v2" && !_selfTest.ok)
  console.error("[regime-core] v2 requested but self-test FAILED -> falling back to legacy engine");
const MARKOV_ENGINE = (_requestedEngine === "v2" && _selfTest.ok) ? "v2" : "legacy";
console.log(`[regime-core] v${REGIME_CORE_VERSION} engine=${MARKOV_ENGINE} (requested=${_requestedEngine}, selfTest=${_selfTest.ok ? "ok" : "FAIL"})`);
const mkRegime = (closes, window, thr) =>
  MARKOV_ENGINE === "v2" ? markovRegimesV2(closes, window, thr) : markovRegimes(closes, window, thr);

// Persisted signal ledger so STAALWAG HQ can score the bot's own performance.
// On Railway set SIGNALS_FILE to a mounted volume path to survive redeploys;
// otherwise it survives restarts but resets on each deploy.
const SIGNALS_FILE   = process.env.SIGNALS_FILE || "./signals-store.json";
// Open calls (one per pair) survive restarts here, so a restart never re-posts them.
const BOOK_FILE      = process.env.BOOK_FILE || "./open-calls.json";
// PAPER_TEST=true labels every post as a paper test (private test channel phase).
const PAPER_TEST     = process.env.PAPER_TEST === "true";
// The hourly "market scan" summary used to go to the channel too. Off by default:
// subscribers get new calls and their results, nothing else.
const SCAN_SUMMARY   = process.env.SCAN_SUMMARY === "true";

// ── Config ────────────────────────────────────────────────────────────────────
const PORT             = process.env.PORT || 3000;
const TG_TOKEN         = process.env.TELEGRAM_BOT_TOKEN;
const TG_CHAT          = process.env.TELEGRAM_CHAT_ID;
// 60min matches the 1H bar the engine reads. Scanning every 15min just re-judged
// the same unfinished bar four times.
const SCAN_INTERVAL    = parseInt(process.env.SCAN_INTERVAL_MIN  || "60") * 60 * 1000;
const QUIET_INTERVAL   = parseInt(process.env.QUIET_INTERVAL_MIN || "60") * 60 * 1000;
// Intraday only. Swing mode doubled message volume and never validated
// out-of-sample (MARKOV_BOT_STATUS.md §5).
const SWING_ENABLED    = process.env.SWING_SIGNALS === "true";

// ── Pairs to monitor ─────────────────────────────────────────────────────────
// PAIRS is the research universe (research/ imports it); LIVE_PAIRS is what the
// bot actually scans and posts. DROP_PAIRS (calls.mjs) removes the losers.
// markovThr: rolling-return threshold for Bull/Bear labelling (fraction).
//   Forex majors ~1%, Gold ~1.5%, commodities/indices ~2%, crypto ~3%.
export const PAIRS = [
  { symbol: "EURUSD",  yahoo: "EURUSD=X",  pip: 0.0001, markovThr: 0.010 },
  { symbol: "GBPUSD",  yahoo: "GBPUSD=X",  pip: 0.0001, markovThr: 0.010 },
  { symbol: "USDJPY",  yahoo: "USDJPY=X",  pip: 0.01,   markovThr: 0.010 },
  { symbol: "USDCHF",  yahoo: "USDCHF=X",  pip: 0.0001, markovThr: 0.010 },
  { symbol: "AUDUSD",  yahoo: "AUDUSD=X",  pip: 0.0001, markovThr: 0.010 },
  { symbol: "NZDUSD",  yahoo: "NZDUSD=X",  pip: 0.0001, markovThr: 0.010 },
  { symbol: "USDCAD",  yahoo: "USDCAD=X",  pip: 0.0001, markovThr: 0.010 },
  { symbol: "GBPJPY",  yahoo: "GBPJPY=X",  pip: 0.01,   markovThr: 0.010 },
  { symbol: "EURJPY",  yahoo: "EURJPY=X",  pip: 0.01,   markovThr: 0.010 },
  { symbol: "EURGBP",  yahoo: "EURGBP=X",  pip: 0.0001, markovThr: 0.010 },
  { symbol: "XAUUSD",  yahoo: "GC=F",      pip: 0.1,    markovThr: 0.015 },
  { symbol: "XAGUSD",  yahoo: "SI=F",      pip: 0.001,  markovThr: 0.020 },
  { symbol: "USOIL",   yahoo: "CL=F",      pip: 0.01,   markovThr: 0.020 },
  { symbol: "NAS100",  yahoo: "NQ=F",      pip: 1.0,    markovThr: 0.020 },
  { symbol: "SPX500",  yahoo: "ES=F",      pip: 0.25,   markovThr: 0.020 },
  { symbol: "US30",    yahoo: "YM=F",      pip: 1.0,    markovThr: 0.020 },
  { symbol: "BTCUSD",  yahoo: "BTC-USD",   pip: 1.0,    markovThr: 0.030 },
  { symbol: "ETHUSD",  yahoo: "ETH-USD",   pip: 0.1,    markovThr: 0.030 },
];

export const LIVE_PAIRS = PAIRS.filter(p => !DROP_PAIRS.includes(p.symbol));

// ── Indicator math ────────────────────────────────────────────────────────────
function ema(closes, period) {
  const k = 2 / (period + 1);
  let v = closes[0];
  for (let i = 1; i < closes.length; i++) v = closes[i] * k + v * (1 - k);
  return v;
}

function rsi(closes, period = 14) {
  if (closes.length < period + 2) return 50;
  let g = 0, l = 0;
  for (let i = 1; i <= period; i++) { const d = closes[i] - closes[i-1]; d > 0 ? g += d : l -= d; }
  let ag = g / period, al = l / period;
  for (let i = period + 1; i < closes.length; i++) {
    const d = closes[i] - closes[i-1];
    ag = (ag * (period - 1) + Math.max(d, 0)) / period;
    al = (al * (period - 1) + Math.max(-d, 0)) / period;
  }
  return al === 0 ? 100 : parseFloat((100 - 100 / (1 + ag / al)).toFixed(2));
}

function rsiSeries(closes, period = 14) {
  if (closes.length < period + 2) return [];
  const out = [];
  let g = 0, l = 0;
  for (let i = 1; i <= period; i++) { const d = closes[i] - closes[i-1]; d > 0 ? g += d : l -= d; }
  let ag = g / period, al = l / period;
  out.push(al === 0 ? 100 : parseFloat((100 - 100 / (1 + ag / al)).toFixed(2)));
  for (let i = period + 1; i < closes.length; i++) {
    const d = closes[i] - closes[i-1];
    ag = (ag * (period - 1) + Math.max(d, 0)) / period;
    al = (al * (period - 1) + Math.max(-d, 0)) / period;
    out.push(al === 0 ? 100 : parseFloat((100 - 100 / (1 + ag / al)).toFixed(2)));
  }
  return out;
}

function macdHistogram(closes) {
  if (closes.length < 26) return 0;
  const k12 = 2 / 13, k26 = 2 / 27;
  let e12 = closes[0], e26 = closes[0];
  for (let i = 1; i < closes.length; i++) {
    e12 = closes[i] * k12 + e12 * (1 - k12);
    e26 = closes[i] * k26 + e26 * (1 - k26);
  }
  return parseFloat((e12 - e26).toFixed(6));
}

function atr(bars, period = 14) {
  if (bars.length < period + 1) return 0;
  const trs = bars.slice(1).map((b, i) => Math.max(
    b.high - b.low,
    Math.abs(b.high - bars[i].close),
    Math.abs(b.low  - bars[i].close)
  ));
  return trs.slice(-period).reduce((a, b) => a + b, 0) / period;
}

function adx(bars, period = 14) {
  if (bars.length < period * 2 + 1) return 0;
  const trs = [], pdms = [], ndms = [];
  for (let i = 1; i < bars.length; i++) {
    trs.push(Math.max(bars[i].high - bars[i].low, Math.abs(bars[i].high - bars[i-1].close), Math.abs(bars[i].low - bars[i-1].close)));
    const up = bars[i].high - bars[i-1].high, dn = bars[i-1].low - bars[i].low;
    pdms.push(up > dn && up > 0 ? up : 0);
    ndms.push(dn > up && dn > 0 ? dn : 0);
  }
  let atrW = trs.slice(0, period).reduce((a, b) => a + b, 0);
  let pdmW = pdms.slice(0, period).reduce((a, b) => a + b, 0);
  let ndmW = ndms.slice(0, period).reduce((a, b) => a + b, 0);
  const dxs = [];
  for (let i = period; i < trs.length; i++) {
    atrW = atrW - atrW / period + trs[i];
    pdmW = pdmW - pdmW / period + pdms[i];
    ndmW = ndmW - ndmW / period + ndms[i];
    const pdi = atrW > 0 ? 100 * pdmW / atrW : 0;
    const ndi = atrW > 0 ? 100 * ndmW / atrW : 0;
    dxs.push((pdi + ndi) > 0 ? 100 * Math.abs(pdi - ndi) / (pdi + ndi) : 0);
  }
  if (dxs.length < period) return 0;
  let adxV = dxs.slice(0, period).reduce((a, b) => a + b, 0) / period;
  for (let i = period; i < dxs.length; i++) adxV = (adxV * (period - 1) + dxs[i]) / period;
  return parseFloat(adxV.toFixed(2));
}

function structure(bars) {
  const highs = [], lows = [];
  for (let i = 2; i < bars.length - 2; i++) {
    if (bars[i].high > bars[i-1].high && bars[i].high > bars[i-2].high && bars[i].high > bars[i+1].high && bars[i].high > bars[i+2].high) highs.push(bars[i].high);
    if (bars[i].low  < bars[i-1].low  && bars[i].low  < bars[i-2].low  && bars[i].low  < bars[i+1].low  && bars[i].low  < bars[i+2].low)  lows.push(bars[i].low);
  }
  const h = highs.slice(-3), l = lows.slice(-3);
  if (h.length >= 2 && l.length >= 2) {
    if (h[h.length-1] > h[h.length-2] && l[l.length-1] > l[l.length-2]) return "Uptrend";
    if (h[h.length-1] < h[h.length-2] && l[l.length-1] < l[l.length-2]) return "Downtrend";
  }
  return "Ranging";
}

function srLevels(bars) {
  const tol = (Math.max(...bars.map(b => b.high)) - Math.min(...bars.map(b => b.low))) * 0.002;
  const lvs = [];
  for (let i = 2; i < bars.length - 2; i++) {
    if (bars[i].high > bars[i-1].high && bars[i].high > bars[i+1].high) {
      const ex = lvs.find(l => Math.abs(l.price - bars[i].high) < tol);
      ex ? ex.touches++ : lvs.push({ price: parseFloat(bars[i].high.toFixed(5)), type: "R", touches: 1 });
    }
    if (bars[i].low < bars[i-1].low && bars[i].low < bars[i+1].low) {
      const ex = lvs.find(l => Math.abs(l.price - bars[i].low) < tol);
      ex ? ex.touches++ : lvs.push({ price: parseFloat(bars[i].low.toFixed(5)), type: "S", touches: 1 });
    }
  }
  return lvs.sort((a, b) => b.touches - a.touches).slice(0, 8);
}

function patterns(bars) {
  const out = { bull: 0, bear: 0, list: [] };
  if (bars.length < 4) return out;
  const [b2, b1, b0] = bars.slice(-3);
  const body = Math.abs(b0.close - b0.open);
  const range = b0.high - b0.low || 0.00001;
  const uw = b0.high - Math.max(b0.open, b0.close);
  const lw = Math.min(b0.open, b0.close) - b0.low;
  if (lw > body * 2 && lw > uw * 2)                                                              { out.bull += 2; out.list.push("Pin Bar (bull)"); }
  if (uw > body * 2 && uw > lw * 2)                                                              { out.bear += 2; out.list.push("Pin Bar (bear)"); }
  if (b1.close < b1.open && b0.close > b0.open && b0.close > b1.open && b0.open < b1.close)     { out.bull += 2; out.list.push("Bullish Engulfing"); }
  if (b1.close > b1.open && b0.close < b0.open && b0.close < b1.open && b0.open > b1.close)     { out.bear += 2; out.list.push("Bearish Engulfing"); }
  if (body < range * 0.1)                                                                         {                out.list.push("Doji"); }
  if (b2.close < b2.open && body / range < 0.3 && b0.close > b0.open && b0.close > (b2.open + b2.close) / 2) { out.bull += 2; out.list.push("Morning Star"); }
  if (b2.close > b2.open && body / range < 0.3 && b0.close < b0.open && b0.close < (b2.open + b2.close) / 2) { out.bear += 2; out.list.push("Evening Star"); }
  return out;
}

function rsidiv(closes) {
  if (closes.length < 60) return { type: "None", strength: 0 };
  const rs = rsiSeries(closes);
  if (rs.length < 40) return { type: "None", strength: 0 };
  const px = closes.slice(-40), rv = rs.slice(-40);
  const [p1, p2] = [px.slice(5, 15), px.slice(25, 40)];
  const [r1, r2] = [rv.slice(5, 15), rv.slice(25, 40)];
  const p1lo = Math.min(...p1), p2lo = Math.min(...p2), r1lo = Math.min(...r1), r2lo = Math.min(...r2);
  const p1hi = Math.max(...p1), p2hi = Math.max(...p2), r1hi = Math.max(...r1), r2hi = Math.max(...r2);
  if (p2lo < p1lo * 0.9995 && r2lo > r1lo + 3) return { type: "Bullish", desc: "RSI Bullish Divergence", strength: Math.min(3, Math.max(1, Math.round((r2lo - r1lo) / 5))) };
  if (p2hi > p1hi * 1.0005 && r2hi < r1hi - 3) return { type: "Bearish", desc: "RSI Bearish Divergence", strength: Math.min(3, Math.max(1, Math.round((r1hi - r2hi) / 5))) };
  return { type: "None", strength: 0 };
}

function sweep(bars, lvs) {
  if (bars.length < 3 || !lvs.length) return { detected: false };
  const last = bars[bars.length - 1];
  for (const lv of lvs) {
    if (lv.type === "S" && last.low < lv.price && last.close > lv.price && last.close > last.open)
      return { detected: true, direction: "Bullish", desc: `Sweep below S ${lv.price.toFixed(5)}` };
    if (lv.type === "R" && last.high > lv.price && last.close < lv.price && last.close < last.open)
      return { detected: true, direction: "Bearish", desc: `Sweep above R ${lv.price.toFixed(5)}` };
  }
  return { detected: false };
}

function volumeSignal(bars) {
  const vols = bars.map(b => b.volume || 0).filter(v => v > 0);
  if (vols.length < 5) return { signal: "N/A", ratio: 1 };
  const avg = vols.slice(-20).reduce((a, b) => a + b, 0) / Math.min(vols.length, 20);
  const ratio = parseFloat((vols[vols.length - 1] / avg).toFixed(2));
  const signal = ratio >= 2 ? "SPIKE" : ratio >= 1.4 ? "HIGH" : ratio >= 0.7 ? "NORMAL" : "LOW";
  return { signal, ratio };
}

// ── Markov regime model ───────────────────────────────────────────────────────
// Markov regime engine consolidated -> regime-core.mjs (vendored from STAALWAG-HQ/core)

// ── Full analysis ─────────────────────────────────────────────────────────────
export function analyze(symbol, bars, dailyBars, pip, markovThr = 0.015, markovCloses = null) {
  if (!bars || bars.length < 50) return null;

  const closes  = bars.map(b => b.close);
  const price   = parseFloat(closes[closes.length - 1].toFixed(5));
  const RSI     = rsi(closes);
  const EMA50   = parseFloat(ema(closes, 50).toFixed(5));
  const EMA200  = parseFloat(ema(closes, 200).toFixed(5));
  const MACD    = macdHistogram(closes);
  const ATR     = atr(bars);
  const ADX     = adx(bars);
  const TREND   = structure(bars);
  const LEVELS  = srLevels(bars);
  const PAT     = patterns(bars);
  const DIV     = rsidiv(closes);
  const SWEEP   = sweep(bars, LEVELS);
  const VOL     = volumeSignal(bars);

  // Daily bias (multi-timeframe)
  let daily = null;
  if (dailyBars && dailyBars.length > 50) {
    const dc = dailyBars.map(b => b.close);
    const dp = dc[dc.length - 1];
    const d50  = ema(dc, 50);
    const d200 = dc.length >= 200 ? ema(dc, 200) : null;
    const dt   = structure(dailyBars);
    let db = 0, dr = 0;
    if (dp > d50) db += 2; else dr += 2;
    if (d200) { dp > d200 ? db += 3 : dr += 3; }
    if (dt === "Uptrend") db += 3; if (dt === "Downtrend") dr += 3;
    daily = { bias: db > dr ? "BULLISH" : dr > db ? "BEARISH" : "NEUTRAL", trend: dt };
  }

  // Markov regime (from daily bars — macro regime context for intraday trades).
  // v2 uses markovCloses (long history) when provided; else the 12mo daily closes.
  const mkCloses = markovCloses || (dailyBars ? dailyBars.map(b => b.close) : null);
  const markov = mkCloses && mkCloses.length > 50
    ? mkRegime(mkCloses, 20, markovThr)
    : null;

  const nearS = LEVELS.filter(l => l.type === "S" && l.price < price).sort((a, b) => b.price - a.price)[0];
  const nearR = LEVELS.filter(l => l.type === "R" && l.price > price).sort((a, b) => a.price - b.price)[0];

  // Scoring
  let bull = 0, bear = 0;
  if (RSI > 60 && RSI <= 70) bull += 2; else if (RSI < 40 && RSI >= 30) bear += 2;
  if (RSI > 70) bull++; if (RSI < 30) bear++;
  if (EMA50 > EMA200) bull++; else bear++;
  if (price > EMA50) bull++; else bear++;
  if (price > EMA200) bull += 2; else bear += 2;
  if (price > EMA50 && EMA50 > EMA200) bull += 2; else if (price < EMA50 && EMA50 < EMA200) bear += 2;
  if (TREND === "Uptrend") bull += 3; if (TREND === "Downtrend") bear += 3;
  if (MACD > 0) bull += 2; else bear += 2;
  if (daily) { if (daily.bias === "BULLISH") bull += 3; else if (daily.bias === "BEARISH") bear += 3; }
  bull += PAT.bull; bear += PAT.bear;
  if (DIV.type === "Bullish") bull += DIV.strength * 2; if (DIV.type === "Bearish") bear += DIV.strength * 2;
  if (SWEEP.detected) { SWEEP.direction === "Bullish" ? bull += 3 : bear += 3; }
  if (VOL.signal === "SPIKE") { bull > bear ? bull += 2 : bear += 2; }
  else if (VOL.signal === "HIGH") { bull > bear ? bull++ : bear++; }
  // Markov regime contributes to scoring
  if (markov) {
    if (markov.regimeIdx === 1) bull += 3;         // Bull regime
    else if (markov.regimeIdx === 2) bear += 3;    // Bear regime
    if (markov.conviction > 0.5) bull += 2;        // Strong bull conviction from transition matrix
    else if (markov.conviction < -0.5) bear += 2;  // Strong bear conviction
  }

  const bias    = bull > bear ? "BULLISH" : bear > bull ? "BEARISH" : "NEUTRAL";
  const rawDiff = Math.abs(bull - bear);
  const ranging = ADX < 20 && ADX > 0;
  const mtfConflict = daily && daily.bias !== "NEUTRAL" && daily.bias !== bias && bias !== "NEUTRAL";
  const markovConflict = markov && markov.persistence > 0.80 &&
    ((bias === "BULLISH" && markov.regimeIdx === 2) || (bias === "BEARISH" && markov.regimeIdx === 1));
  const conf    = (ranging || mtfConflict || markovConflict) ? "Low" : rawDiff >= 10 ? "High" : rawDiff >= 6 ? "Medium" : "Low";

  // Setup generation
  let setup = null;
  if (bias !== "NEUTRAL" && nearS && nearR) {
    let entry, sl, tp1, tp2, rr, pips1, pips2, pipsRisk;
    if (bias === "BULLISH") {
      entry = price;
      sl    = parseFloat(Math.min(nearS.price - ATR * 0.5, entry - ATR * 2.0).toFixed(5));
      tp1   = parseFloat((entry + (entry - sl) * 2.0).toFixed(5));
      const tp2lv = LEVELS.filter(l => l.type === "R" && l.price > tp1).sort((a, b) => a.price - b.price)[0];
      tp2   = tp2lv ? tp2lv.price : parseFloat((entry + (entry - sl) * 2.5).toFixed(5));
      rr    = entry - sl > 0 ? parseFloat(((tp1 - entry) / (entry - sl)).toFixed(2)) : 0;
      pips1 = parseFloat(((tp1 - entry) / pip).toFixed(1));
      pips2 = parseFloat(((tp2 - entry) / pip).toFixed(1));
      pipsRisk = parseFloat(((entry - sl) / pip).toFixed(1));
    } else {
      entry = price;
      sl    = parseFloat(Math.max(nearR.price + ATR * 0.5, entry + ATR * 2.0).toFixed(5));
      tp1   = parseFloat((entry - (sl - entry) * 2.0).toFixed(5));
      const tp2lv = LEVELS.filter(l => l.type === "S" && l.price < tp1).sort((a, b) => b.price - a.price)[0];
      tp2   = tp2lv ? tp2lv.price : parseFloat((entry - (sl - entry) * 2.5).toFixed(5));
      rr    = sl - entry > 0 ? parseFloat(((entry - tp1) / (sl - entry)).toFixed(2)) : 0;
      pips1 = parseFloat(((entry - tp1) / pip).toFixed(1));
      pips2 = parseFloat(((entry - tp2) / pip).toFixed(1));
      pipsRisk = parseFloat(((sl - entry) / pip).toFixed(1));
    }

    // Quality gate
    let gate = "";
    if      (rr < 1.5)         gate = `R:R ${rr}:1 below 1.5:1 minimum`;
    else if (ranging)           gate = `Ranging market (ADX ${ADX} needs 20+)`;
    else if (mtfConflict)       gate = `MTF conflict - Daily ${daily.bias} vs intraday ${bias}`;
    else if (markovConflict)    gate = `Markov ${markov.regime} regime (${(markov.persistence * 100).toFixed(0)}% persistent) vs ${bias}`;
    else if (markov && bias === "BULLISH" && markov.forecast3.bear > 0.55)
                                gate = `3-bar Markov forecast ${(markov.forecast3.bear * 100).toFixed(0)}% Bear`;
    else if (markov && bias === "BEARISH" && markov.forecast3.bull > 0.55)
                                gate = `3-bar Markov forecast ${(markov.forecast3.bull * 100).toFixed(0)}% Bull`;
    else if (conf === "Low")    gate = `Low confluence (Bull:${bull} Bear:${bear})`;

    setup = {
      direction: bias === "BULLISH" ? "BUY" : "SELL",
      entry, sl, tp1, tp2, rr,
      pips1, pips2, pipsRisk,
      quality: gate === "" ? "VALID" : "FILTERED",
      gate,
    };
  }

  return {
    symbol, price, RSI, EMA50, EMA200, MACD, ATR, ADX,
    TREND, bias, conf, bull, bear, ranging, mtfConflict,
    patterns: PAT.list,
    divergence: DIV.type !== "None" ? DIV.desc : null,
    sweep: SWEEP.detected ? SWEEP.desc : null,
    volume: VOL.signal,
    dailyBias: daily ? daily.bias : "N/A",
    markov,
    nearS: nearS ? nearS.price : null,
    nearR: nearR ? nearR.price : null,
    setup,
    timeframe: "INTRADAY",
    barT: bars[bars.length - 1].t ?? null,
  };
}

// ── Yahoo Finance fetch ───────────────────────────────────────────────────────
export function yahooFetch(symbol, interval, range) {
  return new Promise((resolve, reject) => {
    const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?interval=${interval}&range=${range}`;
    const req = https.get(url, { headers: { "User-Agent": "Mozilla/5.0" } }, (res) => {
      let data = "";
      res.on("data", c => data += c);
      res.on("end", () => {
        try {
          const j = JSON.parse(data)?.chart?.result?.[0];
          if (!j) { reject(new Error("No data")); return; }
          const q = j.indicators.quote[0];
          const bars = [];
          for (let i = 0; i < j.timestamp.length; i++) {
            if (q.close[i] != null)
              bars.push({ t: j.timestamp[i], open: q.open[i], high: q.high[i], low: q.low[i], close: q.close[i], volume: q.volume?.[i] || 0 });
          }
          resolve(bars);
        } catch (e) { reject(e); }
      });
    });
    req.on("error", reject);
    req.setTimeout(12000, () => { req.destroy(); reject(new Error("Timeout")); });
  });
}

async function fetchPair(pair) {
  const [bars1h, barsD, barsW] = await Promise.all([
    yahooFetch(pair.yahoo, "1h",  "1mo"),
    yahooFetch(pair.yahoo, "1d", "12mo"),
    yahooFetch(pair.yahoo, "1wk", "5y").catch(() => []),
  ]);
  return { bars1h, barsD, barsW };
}

// ── Swing analysis (daily bars, weekly MTF) ───────────────────────────────────
export function analyzeSwing(symbol, barsD, barsW, pip, markovThr = 0.015, markovCloses = null) {
  if (!barsD || barsD.length < 60) return null;

  const closes = barsD.map(b => b.close);
  const price  = closes[closes.length - 1];

  const RSI   = parseFloat(rsi(closes).toFixed(1));
  const EMA50 = parseFloat(ema(closes, 50).toFixed(5));
  const EMA200= closes.length >= 200 ? parseFloat(ema(closes, 200).toFixed(5)) : EMA50;
  const MACD  = parseFloat(macdHistogram(closes).toFixed(5));
  const ATR   = parseFloat(atr(barsD, 14).toFixed(5));
  const ADX   = parseFloat(adx(barsD, 14).toFixed(1));
  const TREND = structure(barsD);
  const LEVELS= srLevels(barsD);
  const PAT   = patterns(barsD);
  const DIV   = rsidiv(closes);
  const SWEEP = sweep(barsD, LEVELS);
  const VOL   = volumeSignal(barsD);

  // Weekly MTF bias
  let weekly = null;
  if (barsW && barsW.length > 20) {
    const wc = barsW.map(b => b.close);
    const wp = wc[wc.length - 1];
    const w50 = ema(wc, 50);
    const wt  = structure(barsW);
    let wb = 0, wr = 0;
    if (wp > w50) wb += 3; else wr += 3;
    if (wt === "Uptrend") wb += 3; if (wt === "Downtrend") wr += 3;
    weekly = { bias: wb > wr ? "BULLISH" : wr > wb ? "BEARISH" : "NEUTRAL" };
  }

  // Markov regime (from daily bars — same timeframe as swing analysis)
  const markov = mkRegime(markovCloses || closes, 20, markovThr);

  const nearS = LEVELS.filter(l => l.type === "S" && l.price < price).sort((a, b) => b.price - a.price)[0];
  const nearR = LEVELS.filter(l => l.type === "R" && l.price > price).sort((a, b) => a.price - b.price)[0];

  let bull = 0, bear = 0;
  if (RSI > 60 && RSI <= 70) bull += 2; else if (RSI < 40 && RSI >= 30) bear += 2;
  if (RSI > 70) bull++; if (RSI < 30) bear++;
  if (EMA50 > EMA200) bull++; else bear++;
  if (price > EMA50) bull++; else bear++;
  if (price > EMA200) bull += 2; else bear += 2;
  if (price > EMA50 && EMA50 > EMA200) bull += 2; else if (price < EMA50 && EMA50 < EMA200) bear += 2;
  if (TREND === "Uptrend") bull += 3; if (TREND === "Downtrend") bear += 3;
  if (MACD > 0) bull += 2; else bear += 2;
  if (weekly) { if (weekly.bias === "BULLISH") bull += 3; else if (weekly.bias === "BEARISH") bear += 3; }
  bull += PAT.bull; bear += PAT.bear;
  if (DIV.type === "Bullish") bull += DIV.strength * 2; if (DIV.type === "Bearish") bear += DIV.strength * 2;
  if (SWEEP.detected) { SWEEP.direction === "Bullish" ? bull += 3 : bear += 3; }
  if (VOL.signal === "SPIKE") { bull > bear ? bull += 2 : bear += 2; }
  else if (VOL.signal === "HIGH") { bull > bear ? bull++ : bear++; }
  // Markov regime contributes to scoring
  if (markov) {
    if (markov.regimeIdx === 1) bull += 3;
    else if (markov.regimeIdx === 2) bear += 3;
    if (markov.conviction > 0.5) bull += 2;
    else if (markov.conviction < -0.5) bear += 2;
  }

  const bias       = bull > bear ? "BULLISH" : bear > bull ? "BEARISH" : "NEUTRAL";
  const rawDiff    = Math.abs(bull - bear);
  const ranging    = ADX < 18 && ADX > 0;
  const mtfConflict= weekly && weekly.bias !== "NEUTRAL" && weekly.bias !== bias && bias !== "NEUTRAL";
  const markovConflict = markov && markov.persistence > 0.80 &&
    ((bias === "BULLISH" && markov.regimeIdx === 2) || (bias === "BEARISH" && markov.regimeIdx === 1));
  const conf       = (ranging || mtfConflict || markovConflict) ? "Low" : rawDiff >= 10 ? "High" : rawDiff >= 6 ? "Medium" : "Low";

  let setup = null;
  if (bias !== "NEUTRAL" && nearS && nearR) {
    let entry, sl, tp1, tp2, rr, pips1, pips2, pipsRisk;
    if (bias === "BULLISH") {
      entry = price;
      sl    = parseFloat(Math.min(nearS.price - ATR * 0.3, entry - ATR * 1.5).toFixed(5));
      tp1   = parseFloat((entry + (entry - sl) * 2.0).toFixed(5));
      const tp2lv = LEVELS.filter(l => l.type === "R" && l.price > tp1).sort((a, b) => a.price - b.price)[0];
      tp2   = tp2lv ? tp2lv.price : parseFloat((entry + (entry - sl) * 3.0).toFixed(5));
      rr    = entry - sl > 0 ? parseFloat(((tp1 - entry) / (entry - sl)).toFixed(2)) : 0;
      pips1 = parseFloat(((tp1 - entry) / pip).toFixed(1));
      pips2 = parseFloat(((tp2 - entry) / pip).toFixed(1));
      pipsRisk = parseFloat(((entry - sl) / pip).toFixed(1));
    } else {
      entry = price;
      sl    = parseFloat(Math.max(nearR.price + ATR * 0.3, entry + ATR * 1.5).toFixed(5));
      tp1   = parseFloat((entry - (sl - entry) * 2.0).toFixed(5));
      const tp2lv = LEVELS.filter(l => l.type === "S" && l.price < tp1).sort((a, b) => b.price - a.price)[0];
      tp2   = tp2lv ? tp2lv.price : parseFloat((entry - (sl - entry) * 3.0).toFixed(5));
      rr    = sl - entry > 0 ? parseFloat(((entry - tp1) / (sl - entry)).toFixed(2)) : 0;
      pips1 = parseFloat(((entry - tp1) / pip).toFixed(1));
      pips2 = parseFloat(((entry - tp2) / pip).toFixed(1));
      pipsRisk = parseFloat(((sl - entry) / pip).toFixed(1));
    }

    let gate = "";
    if      (rr < 1.5)         gate = `R:R ${rr}:1 below 1.5:1 minimum`;
    else if (ranging)           gate = `Ranging market (ADX ${ADX} needs 18+)`;
    else if (mtfConflict)       gate = `MTF conflict - Weekly ${weekly.bias} vs daily ${bias}`;
    else if (markovConflict)    gate = `Markov ${markov.regime} regime (${(markov.persistence * 100).toFixed(0)}% persistent) vs ${bias}`;
    else if (markov && bias === "BULLISH" && markov.forecast3.bear > 0.55)
                                gate = `3-bar Markov forecast ${(markov.forecast3.bear * 100).toFixed(0)}% Bear`;
    else if (markov && bias === "BEARISH" && markov.forecast3.bull > 0.55)
                                gate = `3-bar Markov forecast ${(markov.forecast3.bull * 100).toFixed(0)}% Bull`;
    else if (conf === "Low")    gate = `Low confluence (Bull:${bull} Bear:${bear})`;

    setup = {
      direction: bias === "BULLISH" ? "BUY" : "SELL",
      entry, sl, tp1, tp2, rr,
      pips1, pips2, pipsRisk,
      quality: gate === "" ? "VALID" : "FILTERED",
      gate,
      timeframe: "SWING",
    };
  }

  return {
    symbol, price, RSI, EMA50, EMA200, MACD, ATR, ADX,
    TREND, bias, conf, bull, bear, ranging, mtfConflict,
    patterns: PAT.list,
    divergence: DIV.type !== "None" ? DIV.desc : null,
    sweep: SWEEP.detected ? SWEEP.desc : null,
    volume: VOL.signal,
    dailyBias: weekly ? weekly.bias : "N/A",
    markov,
    nearS: nearS ? nearS.price : null,
    nearR: nearR ? nearR.price : null,
    setup,
    timeframe: "SWING",
  };
}

// ── Telegram ──────────────────────────────────────────────────────────────────
function tgSend(text) {
  if (!TG_TOKEN || !TG_CHAT) {
    console.error(`[TG] MISSING CONFIG - TOKEN:${!!TG_TOKEN} CHAT:${!!TG_CHAT}`);
    return Promise.resolve();
  }
  console.log(`[TG] sending to ${TG_CHAT}: ${String(text).substring(0, 60)}`);
  return new Promise((resolve) => {
    const body = JSON.stringify({ chat_id: TG_CHAT, text: String(text), disable_web_page_preview: true });
    const req  = https.request(
      `https://api.telegram.org/bot${TG_TOKEN}/sendMessage`,
      { method: "POST", headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) } },
      (res) => {
        let d = ""; res.on("data", c => d += c);
        res.on("end", () => {
          if (res.statusCode !== 200) console.error(`[TG] send failed ${res.statusCode}: ${d}`);
          else console.log(`[TG] sent OK`);
          resolve();
        });
      }
    );
    req.on("error", (e) => { console.error(`[TG] send error: ${e.message}`); resolve(); });
    req.write(body); req.end();
  });
}

// Metals, oil and indices are priced on futures, which sit away from the spot /
// CFD price a broker shows (gold ~$20 on 4 Oct). Say so, and give distances.
function futuresNote(symbol) {
  const p = PAIRS.find(x => x.symbol === symbol);
  if (!p || !p.yahoo.endsWith("=F")) return "";
  return `Priced on ${p.yahoo} futures: your broker's price may differ. Use the pip distances from your own entry.`;
}

function fmtSignal(r, call) {
  const icon = call.direction;
  const tf   = r.timeframe || "INTRADAY";
  const pip  = (PAIRS.find(p => p.symbol === r.symbol) || {}).pip || 0.0001;
  const pips = (a, b) => Math.abs((a - b) / pip).toFixed(1);
  const mkv  = r.markov
    ? `${r.markov.regime} (conviction ${r.markov.conviction >= 0 ? "+" : ""}${r.markov.conviction}, persist ${(r.markov.persistence * 100).toFixed(0)}%)`
    : "N/A";
  return [
    PAPER_TEST ? `[PAPER TEST - not a live call]` : "",
    `=== ${r.symbol} - ${icon} | ${tf} | ${r.conf} Confidence ===`,
    `Entry:    ${call.entry}`,
    `Stop:     ${call.sl}  (-${pips(call.entry, call.sl)} pips)`,
    `Target:   ${call.tp}  (+${pips(call.tp, call.entry)} pips, ${TARGET_R}R)`,
    `Time-stop: closes at market after ${HOLD_HOURS}h if neither is hit`,
    futuresNote(r.symbol),
    `---`,
    `Trend:  ${r.TREND} | ADX: ${r.ADX}`,
    `RSI:    ${r.RSI} | MACD: ${r.MACD > 0 ? "+" : ""}${r.MACD}`,
    `Daily:  ${r.dailyBias}`,
    `Regime: ${mkv}`,
    r.patterns.length ? `Patterns: ${r.patterns.join(", ")}` : "",
    r.divergence ? `Signal: ${r.divergence}` : "",
    r.sweep      ? `Sweep:  ${r.sweep}`      : "",
    `One post per trade idea; the result is posted when it closes.`,
    new Date().toUTCString(),
  ].filter(Boolean).join("\n");
}

function fmtScanSummary(results) {
  const valid    = results.filter(r => r.setup?.quality === "VALID");
  const filtered = results.filter(r => r.setup?.quality === "FILTERED");
  const time     = new Date().toLocaleTimeString("en-GB", { timeZone: "UTC", hour: "2-digit", minute: "2-digit" });

  const lines = [`MARKET SCAN - ${time} UTC | ${results.length} pairs`, `---`];

  if (valid.length > 0) {
    lines.push(`${valid.length} VALID SETUP${valid.length > 1 ? "S" : ""}:`);
    for (const r of valid) {
      const tf = r.timeframe || "INTRADAY";
      lines.push(`  ${r.symbol} ${r.setup.direction}  [${tf}]  R:R 1:${r.setup.rr}  ${r.conf}  @ ${r.setup.entry}`);
    }
  } else {
    lines.push("No valid setups - market not ready.");
  }

  if (filtered.length > 0) {
    lines.push(``, `${filtered.length} filtered (do not trade):`);
    for (const r of filtered) lines.push(`  ${r.symbol}: ${r.setup.gate}`);
  }

  lines.push(``, new Date().toUTCString());
  return lines.join("\n");
}

// ── State ─────────────────────────────────────────────────────────────────────
const state = {
  startTime:      Date.now(),
  lastScan:       null,
  lastNotify:     null,
  lastResults:    [],
  scanning:       false,
  // A restart used to silently un-pause the bot, because this was hard-coded true
  // and the pause flag only ever lived in memory. START_ACTIVE=false keeps a
  // deploy from putting it back on air behind your back -- resume from Telegram.
  active:         process.env.START_ACTIVE !== "false",
  signals:        [],   // every call ever posted, with its result once closed (HQ reads this)
  book:           {},   // pair -> the open call
};

function loadJson(file, fallback) {
  try { return JSON.parse(fs.readFileSync(file, "utf8")) || fallback; } catch { return fallback; }
}
state.signals = loadJson(SIGNALS_FILE, []);
state.book    = loadJson(BOOK_FILE, {});

function persist() {
  try { fs.writeFileSync(SIGNALS_FILE, JSON.stringify(state.signals)); }
  catch (e) { console.error("persist signals:", e.message); }
  try { fs.writeFileSync(BOOK_FILE, JSON.stringify(state.book)); }
  catch (e) { console.error("persist book:", e.message); }
}

function ledgerOpen(call) {
  const { risk, barT, ...row } = call;
  state.signals.push({ ...row, tp1: call.tp, paper: PAPER_TEST });
  if (state.signals.length > 2000) state.signals = state.signals.slice(-2000);
}

function ledgerClose(call) {
  const row = state.signals.find(s => s.id === call.id);
  if (row) Object.assign(row, { status: call.status, result: call.result, reason: call.reason,
                                exit: call.exit, r: call.r, closed: call.closed });
}

async function postClose(call) {
  ledgerClose(call);
  await tgSend((PAPER_TEST ? "[PAPER TEST] " : "") + fmtClose(call));
}

// ── Market scanner ────────────────────────────────────────────────────────────
// Every scan: (1) settle open calls against the newest bars and post any result,
// (2) post NEW calls only -- a pair with an open call in the same direction stays
// silent; a flip closes the old call first. post=false (diagnostics) analyses
// without opening calls; results of calls already open are always posted.
async function scanMarkets(post = true, manual = false) {
  if (state.scanning) return state.lastResults;
  if (!state.active && !manual) return state.lastResults;
  state.scanning = true;
  console.log(`[${new Date().toISOString()}] Scanning ${LIVE_PAIRS.length} pairs...`);

  const results = [];
  const scanErrors = [];
  const closed = [];
  for (const pair of LIVE_PAIRS) {
    try {
      const { bars1h, barsD, barsW } = await fetchPair(pair);

      const open = state.book[pair.symbol];
      if (open) {
        const done = resolveCall(open, bars1h);
        if (done) { delete state.book[pair.symbol]; closed.push(done); }
      }

      // v2 engine needs long daily history for honest stride sampling; legacy
      // (default) leaves this null and behaves exactly as before.
      let markovCloses = null;
      if (MARKOV_ENGINE === "v2") {
        const barsD5y = await yahooFetch(pair.yahoo, "1d", "5y").catch(() => null);
        if (barsD5y && barsD5y.length) markovCloses = barsD5y.map(b => b.close);
      }

      const intraday = analyze(pair.symbol, bars1h, barsD, pair.pip, pair.markovThr || 0.015, markovCloses);
      if (intraday) {
        results.push(intraday);
        const tag = intraday.setup?.quality === "VALID" ? "VALID" : intraday.setup?.quality === "FILTERED" ? "filtered" : "no setup";
        const mkv = intraday.markov ? ` [${intraday.markov.regime}]` : "";
        console.log(`  ${pair.symbol.padEnd(8)} 1H    ${intraday.bias.padEnd(8)} ${intraday.conf.padEnd(6)} ${tag}${mkv}`);
      }

      // Swing signals are OFF by design. They doubled the message volume (36 rows
      // for 18 pairs) and the walk-forward study never validated the daily-swing
      // mode -- it scored TRAIN PF 0.53-0.78 against TEST 1.29-1.43, i.e. the two
      // halves disagreed, which is the signature of noise rather than an edge.
      // Set SWING_SIGNALS=true to re-enable (shown in the summary only; swing
      // setups never open calls).
      if (SWING_ENABLED) {
        const swing = analyzeSwing(pair.symbol, barsD, barsW, pair.pip, pair.markovThr || 0.015, markovCloses);
        if (swing) results.push(swing);
      }
    } catch (e) {
      console.error(`  ${pair.symbol}: ${e.message}`);
      scanErrors.push(`${pair.symbol}: ${e.message}`);
    }
  }

  state.lastScan    = Date.now();
  state.lastResults = results;
  state.lastErrors  = scanErrors;

  try {
    for (const c of closed) await postClose(c);

    let opened = 0;
    if (post) {
      for (const r of results) {
        if (r.timeframe !== "INTRADAY") continue;
        const { open, close } = decide(state.book, r);
        if (close) await postClose(close);
        if (open) {
          ledgerOpen(open);
          await tgSend(fmtSignal(r, open));
          opened++;
        }
      }
    }
    persist();

    if (post && (opened || closed.length)) state.lastNotify = Date.now();
    if (post && SCAN_SUMMARY) {
      const sinceNotify = state.lastNotify ? Date.now() - state.lastNotify : Infinity;
      if (opened || sinceNotify >= QUIET_INTERVAL) {
        await tgSend(fmtScanSummary(results));
        state.lastNotify = Date.now();
      }
    }
  } finally {
    state.scanning = false;
  }
  return results;
}

function fmtOpenCalls() {
  const open = Object.values(state.book);
  if (!open.length) return "No open calls.";
  return [`Open calls (${open.length}):`,
          ...open.map(c => `  ${c.pair} ${c.direction} @ ${c.entry}  stop ${c.sl}  target ${c.tp}  until ${c.expires.slice(11, 16)} UTC`)]
         .join("\n");
}

// ── Express app ───────────────────────────────────────────────────────────────
const app = express();
app.use(express.json());

// Telegram command handler
app.post("/telegram", async (req, res) => {
  res.sendStatus(200);
  const msg = req.body?.message;
  if (!msg?.text) return;

  const raw    = msg.text.trim();
  const text   = raw.toLowerCase().replace(/^\//, "").split("@")[0];
  const chatId = String(msg.chat.id);
  if (TG_CHAT && chatId !== String(TG_CHAT)) return;

  console.log(`[TG] ${raw}`);

  if (text === "start" || text === "help") {
    await tgSend([
      `Nico's Trading Bot - ${state.active ? "ACTIVE" : "PAUSED"}`,
      `---`,
      `Auto-scanning ${LIVE_PAIRS.length} pairs every ${Math.round(SCAN_INTERVAL / 60000)} min.`,
      ``,
      `Commands (with or without /):`,
      `stop   - pause auto scans (save data)`,
      `resume - resume auto scans`,
      `scan   - manual scan right now`,
      `analyze BTCUSD - deep analysis on one pair`,
      `status - uptime, next scan, active/paused`,
      `pairs  - full list of monitored pairs`,
      `last   - results from last scan`,
    ].join("\n"));
    return;
  }

  if (text === "stop") {
    state.active = false;
    await tgSend([
      `Bot PAUSED.`,
      `Auto scans stopped - no data will be used.`,
      `Send: resume  to turn alerts back on.`,
      `Send: scan    to run a one-off scan anytime.`,
    ].join("\n"));
    return;
  }

  if (text === "resume") {
    state.active = true;
    await tgSend([
      `Bot RESUMED.`,
      `Auto scans restarted every ${Math.round(SCAN_INTERVAL / 60000)} min.`,
      `Running first scan now...`,
    ].join("\n"));
    const results = await scanMarkets(true, true);
    await tgSend(fmtScanSummary(results) + "\n\n" + fmtOpenCalls());
    return;
  }

  if (text === "scan") {
    await tgSend("Scanning all pairs now...");
    // New calls go out as usual; an idea that is already open is not re-posted.
    const results = await scanMarkets(true, true);
    await tgSend(fmtScanSummary(results) + "\n\n" + fmtOpenCalls());
    return;
  }

  if (text.startsWith("analyze ") || text.startsWith("a ")) {
    const sym  = raw.split(" ")[1]?.toUpperCase().replace(/[^A-Z0-9]/g, "");
    if (!sym) { await tgSend("Usage: /analyze EURUSD"); return; }
    const pair = PAIRS.find(p => p.symbol === sym) || { symbol: sym, yahoo: sym + "=X", pip: 0.0001 };
    await tgSend(`Analyzing ${sym}...`);
    try {
      const { bars1h, barsD } = await fetchPair(pair);
      const r = analyze(pair.symbol, bars1h, barsD, pair.pip, pair.markovThr || 0.015);
      if (!r) { await tgSend(`No data for ${sym}.`); return; }
      const mkvLine = r.markov
        ? `Regime: ${r.markov.regime} (conviction ${r.markov.conviction >= 0 ? "+" : ""}${r.markov.conviction})`
        : "";
      const lines = [
        `*${r.symbol} Analysis*`,
        `─────────────────────`,
        `Price:  ${r.price}`,
        `Bias:   ${r.bias} | Confidence: ${r.conf}`,
        `Trend:  ${r.TREND} | ADX: ${r.ADX}`,
        `RSI:    ${r.RSI} | MACD: ${r.MACD > 0 ? "+" : ""}${r.MACD}`,
        `EMA50:  ${r.EMA50} | EMA200: ${r.EMA200}`,
        `Daily:  ${r.dailyBias}`,
        mkvLine,
        `R: ${r.nearR || "N/A"} | S: ${r.nearS || "N/A"}`,
        r.patterns.length ? `Patterns: ${r.patterns.join(", ")}` : "",
        r.divergence ? `Signal: ${r.divergence}` : "",
        r.sweep      ? `Sweep:  ${r.sweep}`      : "",
        `Volume: ${r.volume}`,
        `─────────────────────`,
      ];
      if (r.setup?.quality === "VALID") {
        // Analysis only: calls are opened by the scanner, once per idea.
        lines.push(`Setup VALID: ${r.setup.direction} (the scanner posts it as a call if none is open)`);
        await tgSend(lines.filter(Boolean).join("\n"));
      } else if (r.setup?.quality === "FILTERED") {
        lines.push(`Setup filtered: ${r.setup.gate}`);
        await tgSend(lines.filter(Boolean).join("\n"));
      } else {
        lines.push("No setup - wait for better confluence.");
        await tgSend(lines.filter(Boolean).join("\n"));
      }
    } catch (e) { await tgSend(`Error: ${e.message}`); }
    return;
  }

  if (text === "status") {
    const upMin   = Math.floor((Date.now() - state.startTime) / 60000);
    const lastMin = state.lastScan ? Math.floor((Date.now() - state.lastScan) / 60000) : null;
    const nextMin = lastMin != null ? Math.max(0, Math.round(SCAN_INTERVAL / 60000) - lastMin) : "soon";
    await tgSend([
      `BOT STATUS`,
      `Mode:          ${state.active ? "ACTIVE - scanning" : "PAUSED - send: resume"}`,
      `Uptime:        ${upMin} min`,
      `Last scan:     ${lastMin != null ? lastMin + " min ago" : "not yet"}`,
      `Next scan:     ${state.active ? "~" + nextMin + " min" : "paused"}`,
      `Pairs watched: ${LIVE_PAIRS.length}`,
      `Exits:         stop ${STOP_ATR_K}xATR, target ${TARGET_R}R, time-stop ${HOLD_HOURS}h`,
      fmtOpenCalls(),
      `Scan interval: ${Math.round(SCAN_INTERVAL / 60000)} min`,
    ].join("\n"));
    return;
  }

  if (text === "pairs") {
    const list = LIVE_PAIRS.map(p => `  ${p.symbol}`).join("\n");
    await tgSend(`Monitored Pairs (${LIVE_PAIRS.length}):\n${list}`);
    return;
  }

  if (text === "last") {
    if (!state.lastResults.length) { await tgSend("No scan run yet. Send: scan"); return; }
    await tgSend(fmtScanSummary(state.lastResults));
    return;
  }

  await tgSend("Unknown command. Send: help");
});

// Health check
app.get("/", (req, res) => res.json({
  status:    "Claude Trading Bot - running",
  uptime:    Math.floor((Date.now() - state.startTime) / 60000) + " min",
  lastScan:  state.lastScan ? new Date(state.lastScan).toISOString() : "never",
  nextScan:  state.lastScan ? new Date(state.lastScan + SCAN_INTERVAL).toISOString() : "soon",
  pairs:     LIVE_PAIRS.length,
  open:      Object.keys(state.book).length,
}));
app.get("/health", (req, res) => res.json({ ok: true, lastScan: state.lastScan ? new Date(state.lastScan).toISOString() : null }));

// Manual scan trigger (diagnostics + on-demand refresh). Runs a scan without
// Telegram spam and returns how it went + any per-pair fetch errors.
app.get("/scan-now", async (req, res) => {
  res.set("Access-Control-Allow-Origin", "*");
  try {
    const results = await scanMarkets(false, true);
    res.json({
      ok: true, ran: true, results: results.length,
      valid: results.filter(r => r.setup?.quality === "VALID").length,
      errors: state.lastErrors || [],
    });
  } catch (e) {
    res.json({ ok: false, error: e.message });
  }
});

// HQ integration: read-only 18-pair regime scan for the STAALWAG HQ single pane.
app.get("/scan.json", (req, res) => {
  res.set("Access-Control-Allow-Origin", "*");
  res.json({
    generated: new Date().toISOString(),
    lastScan:  state.lastScan ? new Date(state.lastScan).toISOString() : null,
    resultCount: (state.lastResults || []).length,
    errors:    state.lastErrors || [],
    pairs: (state.lastResults || []).map(r => ({
      symbol:      r.symbol,
      regime:      r.markov ? r.markov.regime : null,
      conviction:  r.markov ? r.markov.conviction : null,
      persistence: r.markov ? r.markov.persistence : null,
      setup:       r.setup ? r.setup.quality : null,
      direction:   r.setup ? r.setup.direction : null,
      conf:        r.conf || null,
    })),
  });
});


// HQ integration: the bot's own emitted signals, so HQ can score its record.
app.get("/signals.json", (req, res) => {
  res.set("Access-Control-Allow-Origin", "*");
  res.json({
    generated: new Date().toISOString(),
    rules:     { stop_atr: STOP_ATR_K, target_r: TARGET_R, hold_hours: HOLD_HOURS, paper_test: PAPER_TEST,
                 one_post_per_idea: true, dropped: DROP_PAIRS },
    count:     (state.signals || []).length,
    open:      Object.values(state.book),
    signals:   state.signals || [],
  });
});

// Legacy TradingView webhook. Off unless WEBHOOK_ENABLED=true: anyone who can
// reach it could otherwise make the bot post. When on, it goes through the same
// one-call-per-idea book as the scanner.
app.post("/webhook", async (req, res) => {
  res.json({ received: true });
  if (process.env.WEBHOOK_ENABLED !== "true") return;
  const sym  = req.body?.symbol?.toUpperCase().replace(/[^A-Z0-9]/g, "");
  if (!sym) return;
  const pair = PAIRS.find(p => p.symbol === sym) || { symbol: sym, yahoo: sym + "=X", pip: 0.0001 };
  try {
    const { bars1h, barsD } = await fetchPair(pair);
    const result = analyze(pair.symbol, bars1h, barsD, pair.pip, pair.markovThr || 0.015);
    const { open, close } = decide(state.book, result);
    if (close) await postClose(close);
    if (open) { ledgerOpen(open); await tgSend(fmtSignal(result, open)); }
    persist();
  } catch (e) { console.error("Webhook:", e.message); }
});

// ── Start ─────────────────────────────────────────────────────────────────────
// BACKTEST=1 lets tools import analyze()/PAIRS/fetchPair without booting the live
// server or starting the scan loop. Production run (no flag) is unchanged.
if (process.env.BACKTEST !== "1") {
  app.listen(PORT, async () => {
    console.log(`Claude Trading Bot running on port ${PORT}`);
    console.log(`Scanning ${LIVE_PAIRS.length} pairs every ${Math.round(SCAN_INTERVAL / 60000)} min`);
    console.log(`TG_TOKEN set: ${!!TG_TOKEN} | TG_CHAT: ${TG_CHAT || "NOT SET"} | paper test: ${PAPER_TEST}`);
    console.log(`Exits: stop ${STOP_ATR_K}xATR, target ${TARGET_R}R, time-stop ${HOLD_HOURS}h | open calls: ${Object.keys(state.book).length}`);
    // Startup scan after 8 seconds (let server settle first)
    setTimeout(() => scanMarkets(true), 8000);
    // Recurring scans
    setInterval(() => scanMarkets(true), SCAN_INTERVAL);
  });
}
