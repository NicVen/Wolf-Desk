"""Gold: rules that trade more often (intraday breakouts), same pass bar.

    python lab/intraday.py

Why: on 27 Nov 2026 gold broke out hard (about +$60 in 2 hours, Asia
session) and nothing traded it. Every system we run only allows trades with
the slow daily/weekly trend, which had been DOWN for weeks, so all longs were
blocked. This file tests faster rules, both directions, against the same bar
as everything else: PF >= 1.3 in both halves after costs, n >= 30, and better
than the shuffled-market luck test. Textbook parameters, never tuned here.
"""
from datetime import datetime, timezone

import data
import engine
import run as lab
import strategies as st
from engine import Order


def _hour(b):
    return datetime.fromtimestamp(b["t"], tz=timezone.utc).hour


def _day(b):
    return datetime.fromtimestamp(b["t"], tz=timezone.utc).date()


def _atrs(bars, n=14):
    out = [0.0] * len(bars)
    for i in range(n + 1, len(bars)):
        out[i] = st._atr(bars, i, n)
    return out


def skip_us(make):
    """No new entries 13:00-20:59 UTC (the live channel's US-hours filter)."""
    def make2(bars):
        inner = make(bars)

        def s(bars, i):
            return None if 13 <= _hour(bars[i]) <= 20 else inner(bars, i)
        return s
    return make2


def make_prev_day_break(bars, stop_atr=2.0, target_r=2.0, hold=24):
    """Close above yesterday's high = long, below yesterday's low = short.
    One trade per day per side. Stop 2 x ATR, target 2R, out after 24h."""
    atr = _atrs(bars)
    hi_lo, cur, taken = {}, None, set()
    for b in bars:                                   # daily high/low by UTC day
        d = _day(b)
        h, l = hi_lo.get(d, (b["h"], b["l"]))
        hi_lo[d] = (max(h, b["h"]), min(l, b["l"]))
    days = sorted(hi_lo)
    prev = {d: hi_lo[days[k - 1]] for k, d in enumerate(days) if k}

    def s(bars, i):
        if i < 20:
            return None
        d = _day(bars[i])
        if d not in prev:
            return None
        ph, pl = prev[d]
        c = bars[i]["c"]
        if c > ph and (d, 1) not in taken and bars[i - 1]["c"] <= ph:
            taken.add((d, 1))
            return Order(1, stop_atr * atr[i], target_r, hold)
        if c < pl and (d, -1) not in taken and bars[i - 1]["c"] >= pl:
            taken.add((d, -1))
            return Order(-1, stop_atr * atr[i], target_r, hold)
        return None
    return s


def make_asia_break(bars, target_r=1.5, start=2, end=8, close_hour=12):
    """Tokyo opening range: high/low of 00:00-01:59 UTC, trade the first close
    outside it between 02:00 and 07:59 UTC, stop at the other side, out at
    12:00 UTC. (Today's breakout started about 01:00-03:00 UTC.)"""
    taken = set()

    def s(bars, i):
        b = bars[i]
        h = _hour(b)
        if not (start <= h < end) or _day(b) in taken:
            return None
        rng_bars = [x for x in bars[max(0, i - 10):i] if _day(x) == _day(b) and _hour(x) < start]
        if len(rng_bars) < 2:
            return None
        hi, lo = max(x["h"] for x in rng_bars), min(x["l"] for x in rng_bars)
        if hi <= lo:
            return None
        if b["c"] > hi:
            taken.add(_day(b))
            return Order(1, b["c"] - lo, target_r, close_hour - h)
        if b["c"] < lo:
            taken.add(_day(b))
            return Order(-1, hi - b["c"], target_r, close_hour - h)
        return None
    return s


def make_burst(bars, mult=2.0, stop_atr=1.5, target_r=2.0, hold=12):
    """Momentum burst: an hour at least 2 x ATR tall that closes in its top
    (or bottom) quarter. Follow it. Stop 1.5 x ATR, target 2R, out after 12h."""
    atr = _atrs(bars)

    def s(bars, i):
        if i < 20 or not atr[i - 1]:
            return None
        b = bars[i]
        rng = b["h"] - b["l"]
        if rng < mult * atr[i - 1]:
            return None
        if b["c"] >= b["h"] - 0.25 * rng:
            return Order(1, stop_atr * atr[i], target_r, hold)
        if b["c"] <= b["l"] + 0.25 * rng:
            return Order(-1, stop_atr * atr[i], target_r, hold)
        return None
    return s


def make_squeeze(bars, n=20, look=120, pct=0.2, recent=5, stop_atr=2.0, target_r=2.0, hold=24):
    """Squeeze breakout: Bollinger(20, 2) width was in its lowest 20% of the
    last 120 hours within the last 5 hours, then price closes outside the band."""
    c = [b["c"] for b in bars]
    atr = _atrs(bars)
    mid, up, dn, wid = [0.0] * len(c), [0.0] * len(c), [0.0] * len(c), [0.0] * len(c)
    for i in range(n, len(c)):
        w = c[i - n + 1:i + 1]
        m = sum(w) / n
        sd = (sum((x - m) ** 2 for x in w) / n) ** 0.5
        mid[i], up[i], dn[i], wid[i] = m, m + 2 * sd, m - 2 * sd, 4 * sd / m

    def s(bars, i):
        if i < look + n:
            return None
        hist = sorted(wid[i - look:i])
        cut = hist[int(pct * (len(hist) - 1))]
        if min(wid[i - recent:i]) > cut:
            return None
        if c[i] > up[i] and c[i - 1] <= up[i - 1]:
            return Order(1, stop_atr * atr[i], target_r, hold)
        if c[i] < dn[i] and c[i - 1] >= dn[i - 1]:
            return Order(-1, stop_atr * atr[i], target_r, hold)
        return None
    return s


def fast_trend(bars_h):
    """+1 / -1 from the 1h EMA 20 vs EMA 50 (about 1-2 days), known at the close."""
    c = [b["c"] for b in bars_h]
    e20, e50 = st._ema_series(c, 20), st._ema_series(c, 50)
    return [1 if a > b else -1 if a < b else 0 for a, b in zip(e20, e50)]


def with_fast_trend(make):
    """Only trades in the direction of the FAST (1-2 day) trend, so longs
    come back within a day or two of a turn instead of weeks later."""
    def make2(bars):
        inner, ft = make(bars), fast_trend(bars)

        def s(bars, i):
            o = inner(bars, i)
            return o if o is not None and o.direction == ft[i] else None
        return s
    return make2


RULES = {
    "breakout + 200-hour trend (live rule without the daily filter)": st.make_donchian,
    "yesterday's high/low breakout": make_prev_day_break,
    "Tokyo opening range breakout": make_asia_break,
    "momentum burst (2x ATR hour)": make_burst,
    "squeeze breakout (Bollinger)": make_squeeze,
}


def main():
    sym, cost = lab.MARKETS["gold"]
    h = data.bars(sym, "60m", "730d")
    d = data.bars(sym, "1d", "20y")
    trend = st.daily_trend(d)
    print(f"## Gold intraday: rules that trade more often ({sym}, cost {cost}/trade)\n")
    print("| rule | trades | per month | win | PF | PF 1st half | PF 2nd half | PF last 6m (n) | PF longs (n) | PF shorts (n) | total R | worst drawdown R | luck PF (95%) | verdict |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    live = st.with_daily_trend(st.make_donchian, trend)
    print(lab.score("LIVE channel rule (breakout + daily trend + skip US)", h, skip_us(live), cost))
    for name, make in RULES.items():
        print(lab.score(name, h, make, cost))
        print(lab.score(name + ", skip US hours", h, skip_us(make), cost))
        print(lab.score(name + ", with 1-2 day trend", h, with_fast_trend(make), cost))
        print(lab.score(name + ", with daily trend", h, st.with_daily_trend(make, trend), cost))
    print(f"\n1h bars: {len(h)}. Gold over the window: "
          f"{100 * (h[-1]['c'] / h[0]['c'] - 1):+.0f}%. Last close {h[-1]['c']:.2f}.")


if __name__ == "__main__":
    main()
