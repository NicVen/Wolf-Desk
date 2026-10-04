// cd markov && node --test
import { test } from "node:test";
import assert from "node:assert/strict";
import { decide, resolveCall, planTrade, fmtClose, DROP_PAIRS } from "../calls.mjs";

const H = 3600;
const T0 = Date.UTC(2026, 9, 1, 8) ;          // ms
const t0 = T0 / 1000;                          // entry bar (unix s)

function valid(symbol, direction, price = 100, atr = 1) {
  return { symbol, price, ATR: atr, barT: t0, timeframe: "INTRADAY",
           setup: { quality: "VALID", direction, entry: price } };
}
const bar = (h, low, high, close) => ({ t: t0 + h * H, low, high, close });

test("stop is 6xATR and target 2R", () => {
  const c = planTrade(valid("XAUUSD", "BUY", 100, 1), T0);
  assert.equal(c.sl, 94);
  assert.equal(c.tp, 112);
  const s = planTrade(valid("XAUUSD", "SELL", 100, 1), T0);
  assert.equal(s.sl, 106);
  assert.equal(s.tp, 88);
});

test("the same idea is posted once, not every scan", () => {
  const book = {};
  let opens = 0;
  for (let i = 0; i < 12; i++) if (decide(book, valid("XAUUSD", "SELL"), T0 + i * H * 1000).open) opens++;
  assert.equal(opens, 1);
});

test("a flip closes the open call and opens the new one", () => {
  const book = {};
  decide(book, valid("USOIL", "BUY", 100), T0);
  const { open, close } = decide(book, valid("USOIL", "SELL", 101), T0 + H * 1000);
  assert.equal(close.reason, "flip");
  assert.equal(close.r, 0.17);           // +1 on a 6-point stop
  assert.equal(open.direction, "SELL");
  assert.equal(book.USOIL, open);
});

test("dropped pairs never open a call", () => {
  assert.ok(DROP_PAIRS.includes("EURUSD") && DROP_PAIRS.includes("EURGBP"));
  assert.equal(decide({}, valid("EURUSD", "BUY")).open, null);
});

test("stop, target and the 12h time-stop each close the call", () => {
  const stop = planTrade(valid("A", "BUY"), T0);
  assert.equal(resolveCall(stop, [bar(1, 99, 101, 100), bar(2, 93.5, 100, 95)], T0 + 3 * H * 1000).reason, "stop");

  const tgt = planTrade(valid("A", "SELL"), T0);
  const c = resolveCall(tgt, [bar(1, 95, 101, 96), bar(2, 87, 96, 88)], T0 + 3 * H * 1000);
  assert.equal(c.reason, "target");
  assert.equal(c.r, 2);
  assert.equal(c.result, "WIN");

  const tm = planTrade(valid("A", "BUY"), T0);
  assert.equal(resolveCall(tm, [bar(1, 99, 102, 101)], T0 + 5 * H * 1000), null);   // still open
  const bars = Array.from({ length: 14 }, (_, i) => bar(i + 1, 99, 103, 100 + (i + 1) / 10));
  const done = resolveCall(tm, bars, T0 + 13 * H * 1000);
  assert.equal(done.reason, "time");
  assert.equal(done.exit, 101.1);      // close of the last bar inside the 12h window (bar 11 starts at +11h)
  assert.match(fmtClose(done), /CLOSED A BUY: \+0\.18R \(closed at market after 12h\)/);
});

test("the entry bar itself does not decide the outcome", () => {
  const c = planTrade(valid("A", "BUY"), T0);
  assert.equal(resolveCall(c, [bar(0, 90, 101, 100)], T0 + H * 1000), null);
});
