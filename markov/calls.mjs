// One call per trade idea, with the exits the July walk-forward study picked
// (research/adaptive.mjs, MARKOV_BOT_STATUS.md §8):
//   stop   = entry -/+ STOP_ATR_K x ATR(1H)        (k=6)
//   target = TARGET_R x the stop distance           (2R)
//   exit   = whichever comes first: stop, target, or market close after HOLD_HOURS (12)
// A pair with an open call is silent until that call closes. A flip in direction
// closes the open call at market and opens the new one.
//
// Pure logic, no network or Telegram: server.js feeds it bars and posts what it
// returns. Tests: cd markov && node --test

export const STOP_ATR_K = parseFloat(process.env.STOP_ATR_K || "6");
export const TARGET_R   = parseFloat(process.env.TARGET_R   || "2");
export const HOLD_HOURS = parseFloat(process.env.HOLD_HOURS || "12");
// EURUSD and EURGBP lost in both halves of the July test, at every stop width.
export const DROP_PAIRS = (process.env.DROP_PAIRS ?? "EURUSD,EURGBP")
  .split(",").map(s => s.trim().toUpperCase()).filter(Boolean);

const round = (x) => parseFloat(Number(x).toFixed(5));

// Entry/stop/target for a VALID analyze() result. Selection (which setups are
// VALID) is unchanged; only the exits are replaced, exactly as the study did.
export function planTrade(r, now = Date.now()) {
  const s = r.setup;
  const risk = r.ATR * STOP_ATR_K;
  if (!(risk > 0)) return null;
  const buy = s.direction === "BUY";
  const entry = s.entry;
  return {
    id:        `${r.symbol}-${now}`,
    pair:      r.symbol,
    direction: s.direction,
    entry,
    sl:        round(buy ? entry - risk : entry + risk),
    tp:        round(buy ? entry + TARGET_R * risk : entry - TARGET_R * risk),
    risk,
    time:      new Date(now).toISOString(),
    expires:   new Date(now + HOLD_HOURS * 3600 * 1000).toISOString(),
    barT:      r.barT ?? null,          // last bar (unix s) at entry; later bars decide the outcome
    status:    "OPEN",
  };
}

function rOf(call, exit) {
  const move = call.direction === "BUY" ? exit - call.entry : call.entry - exit;
  return parseFloat((move / Math.abs(call.entry - call.sl)).toFixed(2));
}

export function closeCall(call, exit, reason, now = Date.now()) {
  const r = rOf(call, exit);
  return Object.assign(call, {
    status: "CLOSED",
    result: r > 0 ? "WIN" : r < 0 ? "LOSS" : "FLAT",
    reason,                              // "target" | "stop" | "time" | "flip"
    exit:   round(exit),
    r,
    closed: new Date(now).toISOString(),
  });
}

// Check an open call against 1H bars ({t, high, low, close}). Stop is checked
// before target inside a bar (the conservative order the backtest used).
// Returns the closed call, or null if it is still open.
export function resolveCall(call, bars, now = Date.now()) {
  const after = (bars || []).filter(b => call.barT == null || b.t > call.barT);
  const deadline = Date.parse(call.expires);
  for (const b of after) {
    if (b.t != null && b.t * 1000 >= deadline) break;   // past the time-stop
    if (call.direction === "BUY") {
      if (b.low  <= call.sl) return closeCall(call, call.sl, "stop", now);
      if (b.high >= call.tp) return closeCall(call, call.tp, "target", now);
    } else {
      if (b.high >= call.sl) return closeCall(call, call.sl, "stop", now);
      if (b.low  <= call.tp) return closeCall(call, call.tp, "target", now);
    }
  }
  if (now >= deadline) {
    const inWindow = after.filter(b => b.t == null || b.t * 1000 < deadline);
    const last = inWindow[inWindow.length - 1] || (bars || [])[bars.length - 1];
    if (last && last.close != null) return closeCall(call, last.close, "time", now);
  }
  return null;
}

// Decide what one scan result means for the book.
//   book: { [pair]: openCall }
// Returns { open: call|null, close: closedCall|null } -- at most one of each.
export function decide(book, r, now = Date.now()) {
  if (r?.setup?.quality !== "VALID" || DROP_PAIRS.includes(r.symbol)) return { open: null, close: null };
  const cur = book[r.symbol];
  if (cur && cur.direction === r.setup.direction) return { open: null, close: null };  // same idea, stay quiet
  let close = null;
  if (cur) { close = closeCall(cur, r.price, "flip", now); delete book[r.symbol]; }
  const call = planTrade(r, now);
  if (call) book[r.symbol] = call;
  return { open: call, close };
}

const REASON = {
  target: "target hit",
  stop:   "stop hit",
  time:   `closed at market after ${HOLD_HOURS}h`,
  flip:   "closed at market, direction flipped",
};

export function fmtClose(c) {
  const sign = c.r > 0 ? "+" : "";
  return [
    `CLOSED ${c.pair} ${c.direction}: ${sign}${c.r}R (${REASON[c.reason] || c.reason})`,
    `Entry ${c.entry} -> exit ${c.exit}`,
    `Opened ${c.time.replace("T", " ").slice(0, 16)} UTC`,
  ].join("\n");
}
