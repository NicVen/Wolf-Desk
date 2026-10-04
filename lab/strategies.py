"""Candidate rules. Parameters are fixed textbook values, NOT tuned to this
data, so the two halves of the test are a fair check.

Each make_*() returns strategy(bars, i) -> Order | None, using bars[0..i] only.
"""
from datetime import datetime, timezone

from engine import Order


def _sma(xs, n):
    return sum(xs[-n:]) / n


def _ema_series(xs, n):
    k, e, out = 2 / (n + 1), xs[0], []
    for x in xs:
        e = x * k + e * (1 - k)
        out.append(e)
    return out


def _atr(bars, i, n=14):
    trs = [max(b["h"] - b["l"], abs(b["h"] - p["c"]), abs(b["l"] - p["c"]))
           for p, b in zip(bars[i - n:i], bars[i - n + 1:i + 1])]
    return sum(trs) / len(trs)


class Cache:
    """Per-bar indicator arrays, built once per data set."""
    def __init__(self, bars):
        self.c = [b["c"] for b in bars]
        self.ema200 = _ema_series(self.c, 200)
        self.ema50 = _ema_series(self.c, 50)


def make_current(bars):
    """Today's live Gold rule, on 1h bars: MA10/50 + 20-bar regime, SL 1.5x
    average close-to-close move, TP 2.5x, 12h time-stop."""
    c = [b["c"] for b in bars]

    def s(bars, i):
        if i < 80:
            return None
        cl = c[:i + 1]
        fast, slow = _sma(cl, 10), _sma(cl, 50)
        ret = (cl[-1] - cl[-21]) / cl[-21]
        regime = "BULL" if ret > 0.0015 else "BEAR" if ret < -0.0015 else "SIDE"
        diffs = [abs(b - a) for a, b in zip(cl[-15:], cl[-14:])]
        atrp = sum(diffs) / len(diffs)
        if fast > slow and regime == "BULL":
            return Order(1, 1.5 * atrp, 2.5 / 1.5, 12)
        if fast < slow and regime == "BEAR":
            return Order(-1, 1.5 * atrp, 2.5 / 1.5, 12)
        return None
    return s


def make_donchian(bars, look=20, stop_atr=2.0, target_r=3.0, hold=48):
    """Classic Turtle-style breakout, only with the 200-bar trend."""
    cache = Cache(bars)

    def s(bars, i):
        if i < 220:
            return None
        hi = max(b["h"] for b in bars[i - look:i])
        lo = min(b["l"] for b in bars[i - look:i])
        c, atr = bars[i]["c"], _atr(bars, i)
        if c > hi and c > cache.ema200[i]:
            return Order(1, stop_atr * atr, target_r, hold)
        if c < lo and c < cache.ema200[i]:
            return Order(-1, stop_atr * atr, target_r, hold)
        return None
    return s


def make_pullback(bars, stop_atr=2.0, target_r=1.5, hold=24):
    """Trend pullback (Connors RSI-2 idea): with the 200 trend, buy a 2-bar
    RSI below 10 / sell above 90."""
    cache = Cache(bars)
    c = cache.c

    def rsi2(i):
        up = dn = 0.0
        for a, b in zip(c[i - 2:i], c[i - 1:i + 1]):
            up += max(b - a, 0)
            dn += max(a - b, 0)
        return 100.0 if dn == 0 else 100 - 100 / (1 + up / dn)

    def s(bars, i):
        if i < 220:
            return None
        r, atr = rsi2(i), _atr(bars, i)
        if c[i] > cache.ema200[i] and r < 10:
            return Order(1, stop_atr * atr, target_r, hold)
        if c[i] < cache.ema200[i] and r > 90:
            return Order(-1, stop_atr * atr, target_r, hold)
        return None
    return s


def make_session_break(bars, target_r=1.5, start=7, end=12, close_hour=20):
    """London breakout of the Asian range (00:00-07:00 UTC), stop at the other
    side of the range, one trade a day, out by 20:00 UTC."""
    taken = set()

    def hour(b):
        return datetime.fromtimestamp(b["t"], tz=timezone.utc).hour

    def day(b):
        return datetime.fromtimestamp(b["t"], tz=timezone.utc).date()

    def s(bars, i):
        b = bars[i]
        h = hour(b)
        if not (start <= h < end) or day(b) in taken:
            return None
        asia = [x for x in bars[max(0, i - 14):i] if day(x) == day(b) and hour(x) < start]
        if len(asia) < 5:
            return None
        hi, lo = max(x["h"] for x in asia), min(x["l"] for x in asia)
        rng = hi - lo
        hold = close_hour - h
        if b["c"] > hi:
            taken.add(day(b))
            return Order(1, b["c"] - lo, target_r, hold) if rng > 0 else None
        if b["c"] < lo:
            taken.add(day(b))
            return Order(-1, hi - b["c"], target_r, hold) if rng > 0 else None
        return None
    return s


def make_trend_daily(bars, stop_atr=3.0, hold=20):
    """Time-series momentum on daily bars: hold the side of the 50/200 EMA
    trend, enter on a fresh 20-day high/low, wide stop, no fixed target."""
    cache = Cache(bars)

    def s(bars, i):
        if i < 220:
            return None
        hi = max(b["h"] for b in bars[i - 20:i])
        lo = min(b["l"] for b in bars[i - 20:i])
        c, atr = bars[i]["c"], _atr(bars, i)
        if cache.ema50[i] > cache.ema200[i] and c > hi:
            return Order(1, stop_atr * atr, 0, hold)
        if cache.ema50[i] < cache.ema200[i] and c < lo:
            return Order(-1, stop_atr * atr, 0, hold)
        return None
    return s


HOURLY = {
    "current (live rule)": make_current,
    "breakout + trend": make_donchian,
    "trend pullback": make_pullback,
    "London breakout": make_session_break,
}
DAILY = {
    "daily trend (20y)": make_trend_daily,
}
