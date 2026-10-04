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


def daily_trend(daily):
    """date -> +1 / -1 / 0 from the daily 50/200 EMA, known at that day's close.
    An hourly bar on day D uses the state from the last daily close BEFORE D."""
    c = [b["c"] for b in daily]
    e50, e200 = _ema_series(c, 50), _ema_series(c, 200)
    days = [datetime.fromtimestamp(b["t"], tz=timezone.utc).date() for b in daily]
    state = {}
    for k in range(200, len(daily)):
        state[days[k]] = 1 if e50[k] > e200[k] else -1 if e50[k] < e200[k] else 0
    order = sorted(state)

    def at(t):
        d = datetime.fromtimestamp(t, tz=timezone.utc).date()
        lo, hi = 0, len(order)
        while lo < hi:                       # last daily close strictly before d
            mid = (lo + hi) // 2
            if order[mid] < d:
                lo = mid + 1
            else:
                hi = mid
        return state[order[lo - 1]] if lo else 0
    return at


def with_daily_trend(make, trend_at):
    """Wrap an hourly rule: only take its trades in the daily trend direction."""
    def make2(bars):
        inner = make(bars)

        def s(bars, i):
            o = inner(bars, i)
            if o is None or o.direction != trend_at(bars[i]["t"]):
                return None
            return o
        return s
    return make2


def make_veldrin(bars):
    """Today's live VELDRIN rule on 1h bars: MA10 vs MA50 (0.03% band) must agree
    on 1h AND 4h (4 hourly closes per 4h bar, current one included), London/NY
    hours only (08-22 UTC). SL 1.5x average close-to-close move; TP1 1R bank 50%
    + stop to entry, TP2 2R stop to TP1, TP3 3R; 18h time-stop."""
    c = [b["c"] for b in bars]

    def bias(xs):
        if len(xs) < 50:
            return 0
        fast, slow = sum(xs[-10:]) / 10, sum(xs[-50:]) / 50
        return 1 if fast > slow * 1.0003 else -1 if fast < slow * 0.9997 else 0

    def s(bars, i):
        if i < 220:
            return None
        h = datetime.fromtimestamp(bars[i]["t"], tz=timezone.utc).hour
        if not 8 <= h < 22:
            return None
        cl = c[:i + 1]
        b1 = bias(cl)
        if not b1:
            return None
        start = (i + 1) % 4                       # 4h buckets end on bar i
        b4 = bias(c[start + 3:i + 1:4][-60:])
        if b1 != b4:
            return None
        diffs = [abs(y - x) for x, y in zip(cl[-15:], cl[-14:])]
        return Order(b1, 1.5 * sum(diffs) / len(diffs), 0, 18, runner=True)
    return s


def make_hour_of_day(bars, min_n=150, t_min=2.5, stop_atr=3.0):
    """Time-of-day pattern (Breedon & Ranaldo: currencies tend to move the same
    way at the same hours). Walk-forward, so every trade is out-of-sample: at
    each hour, look only at that clock hour's past 1h moves (all data BEFORE
    now); if their average is clearly non-zero (t-stat > 2.5 on 150+ samples),
    trade that direction for the one hour."""
    from math import sqrt
    n_, s_, q_ = [0] * 24, [0.0] * 24, [0.0] * 24
    done = [0]                            # bars already added to the stats

    def hr(b):
        return datetime.fromtimestamp(b["t"], tz=timezone.utc).hour

    def s(bars, i):
        while done[0] <= i:               # add finished bars up to and incl. i
            k = done[0]
            if k > 0:
                r = bars[k]["c"] / bars[k]["o"] - 1
                h = hr(bars[k])
                n_[h] += 1; s_[h] += r; q_[h] += r * r
            done[0] += 1
        if i < 220 or i + 1 >= len(bars):
            return None
        h = hr(bars[i + 1])               # the hour we would trade
        n = n_[h]
        if n < min_n:
            return None
        mean = s_[h] / n
        var = max(q_[h] / n - mean * mean, 1e-18)
        t = mean / sqrt(var / n)
        if abs(t) < t_min:
            return None
        return Order(1 if t > 0 else -1, stop_atr * _atr(bars, i), 0, 1)
    return s


def make_fade(bars, stop_atr=2.0, target_r=1.0, hold=12, asia_only=False):
    """Mean reversion: FX majors chop more than they trend. Fade a 2-bar RSI
    extreme (below 5 buy, above 95 sell), no trend filter. Asia variant: only
    22:00-07:00 UTC, the quiet hours when ranges hold best."""
    c = [b["c"] for b in bars]

    def rsi2(i):
        up = dn = 0.0
        for a, b in zip(c[i - 2:i], c[i - 1:i + 1]):
            up += max(b - a, 0)
            dn += max(a - b, 0)
        return 100.0 if dn == 0 else 100 - 100 / (1 + up / dn)

    def s(bars, i):
        if i < 220:
            return None
        if asia_only:
            h = datetime.fromtimestamp(bars[i]["t"], tz=timezone.utc).hour
            if 7 <= h < 22:
                return None
        r = rsi2(i)
        if r < 5:
            return Order(1, stop_atr * _atr(bars, i), target_r, hold)
        if r > 95:
            return Order(-1, stop_atr * _atr(bars, i), target_r, hold)
        return None
    return s


def make_fade_asia(bars):
    return make_fade(bars, asia_only=True)


_LONDON = None


def _london_hour(t):
    global _LONDON
    if _LONDON is None:
        from zoneinfo import ZoneInfo
        _LONDON = ZoneInfo("Europe/London")
    return datetime.fromtimestamp(t, tz=_LONDON).hour


def make_fix_reversal(bars, look=2, min_atr=0.5, stop_atr=2.0, hold=3):
    """London 4pm fix (WM/Reuters): banks fill large orders at the fix, pushing
    price into it, and the move tends to snap back afterwards (Melvin & Prins;
    Evans). On the 1h bar that ends at 16:00 London, if the last 2 hours moved
    more than half an ATR, fade it from the fix for 3 hours."""
    def s(bars, i):
        if i < 220 or _london_hour(bars[i]["t"]) != 15:
            return None
        move = bars[i]["c"] - bars[i - look + 1]["o"]
        atr = _atr(bars, i)
        if abs(move) < min_atr * atr:
            return None
        return Order(-1 if move > 0 else 1, stop_atr * atr, 0, hold)
    return s


def make_weekend_gap(bars, min_atr=0.3):
    """Sunday gap fill: when the week opens away from Friday's close, trade back
    toward Friday's close. Target = the gap filled, stop = the same distance the
    other way, out after 24h."""
    def s(bars, i):
        if i < 220 or bars[i]["t"] - bars[i - 1]["t"] < 24 * 3600:
            return None                     # only the first bar of the week
        gap = bars[i]["o"] - bars[i - 1]["c"]
        atr = _atr(bars, i - 1)
        if abs(gap) < min_atr * atr:
            return None
        # signal on the first bar; the engine enters at the next bar's open,
        # so measure what is left of the gap from there
        left = bars[i]["c"] - bars[i - 1]["c"]
        if left * gap <= 0 or abs(left) < 0.2 * atr:
            return None                     # already filled
        return Order(-1 if gap > 0 else 1, abs(left), 1.0, 24)
    return s


def make_month_end(bars, min_n=60, t_min=2.0, stop_atr=3.0):
    """Month-end rebalancing flows, daily bars, walk-forward: for the last 2
    trading days of each month, use only PAST month-ends to learn the pair's
    usual direction; trade it if the evidence is clear (t > 2)."""
    from math import sqrt
    st = {"n": 0, "s": 0.0, "q": 0.0, "next": 1}

    def ym(k):
        d = datetime.fromtimestamp(bars[k]["t"], tz=timezone.utc)
        return d.year, d.month

    def month_end(k):             # bar k is one of the last 2 bars of its month
        return k + 2 < len(bars) and ym(k + 2) != ym(k)

    def s(bars, i):
        while st["next"] + 2 <= i:                # month-end status known by now
            k = st["next"]
            if month_end(k):
                r = bars[k]["c"] / bars[k]["o"] - 1
                st["n"] += 1; st["s"] += r; st["q"] += r * r
            st["next"] += 1
        if i < 220 or not month_end(i + 1) or st["n"] < min_n:
            return None
        n = st["n"]
        mean = st["s"] / n
        var = max(st["q"] / n - mean * mean, 1e-18)
        t = mean / sqrt(var / n)
        if abs(t) < t_min:
            return None
        return Order(1 if t > 0 else -1, stop_atr * _atr(bars, i), 0, 1)
    return s


def make_cot(cot_rows, sign, who="lev", fade=True, window=156, hi=0.9, lo=0.1,
             stop_atr=3.0, hold=5):
    """Big-player positioning (CFTC weekly report), daily bars, walk-forward.
    who: "lev" = hedge funds (leveraged money), "am" = asset managers.
    Each new report: rank this week's net position against the past 3 years.
    Crowded (top 10%) / empty (bottom 10%): fade=True trades against the
    crowd (crowded trades unwind), fade=False goes with it.
    sign: +1 when the pair rises with the currency (EURUSD), -1 when it falls
    (USDJPY: yen futures long = USDJPY down)."""
    col = 1 if who == "lev" else 2

    def make(bars):
        used = {"k": -1}

        def s(bars, i):
            if i < 60 or i + 1 >= len(bars):
                return None
            known = bars[i + 1]["t"]          # we enter at the next bar's open
            k = used["k"]
            while k + 1 < len(cot_rows) and cot_rows[k + 1][0] <= known:
                k += 1
            if k == used["k"]:
                return None                   # no new report since last look
            used["k"] = k
            if k < window:
                return None
            past = sorted(r[col] for r in cot_rows[k - window:k])
            x = cot_rows[k][col]
            rank = sum(p < x for p in past) / len(past)
            if lo < rank < hi:
                return None
            crowd = 1 if rank >= hi else -1   # crowd long / short the currency
            d = (-crowd if fade else crowd) * sign
            return Order(d, stop_atr * _atr(bars, i), 0, hold)
        return s
    return make


def with_cot_filter(make, cot_rows, who="lev", window=156, crowded=0.9):
    """Wrap a rule: skip a long when that group's net long is in its top 10%
    of the past 3 years (everyone is already in), and a short when it's in the
    bottom 10%. Uses only reports already released at the trade's entry."""
    col = 1 if who == "lev" else 2

    def make2(bars):
        inner = make(bars)

        def s(bars, i):
            o = inner(bars, i)
            if o is None or i + 1 >= len(bars):
                return o
            known = bars[i + 1]["t"]
            k = -1
            lo, hi = 0, len(cot_rows)
            while lo < hi:
                mid = (lo + hi) // 2
                if cot_rows[mid][0] <= known:
                    lo = mid + 1
                else:
                    hi = mid
            k = lo - 1
            if k < window:
                return o
            past = sorted(r[col] for r in cot_rows[k - window:k])
            rank = sum(p < cot_rows[k][col] for p in past) / len(past)
            if (o.direction > 0 and rank >= crowded) or (o.direction < 0 and rank <= 1 - crowded):
                return None
            return o
        return s
    return make2


def make_volume_spike(bars, mult=3.0, body_atr=1.0, follow=True, stop_atr=2.0, hold=6):
    """Futures volume surge: an hour with 3x the usual volume AND a big candle
    means real money arrived. follow=True rides it for 6h, False fades it."""
    v = [b.get("v", 0) for b in bars]

    def s(bars, i):
        if i < 220:
            return None
        base = sum(v[i - 20:i]) / 20
        if base <= 0 or v[i] < mult * base:
            return None
        body = bars[i]["c"] - bars[i]["o"]
        atr = _atr(bars, i)
        if abs(body) < body_atr * atr:
            return None
        d = 1 if body > 0 else -1
        return Order(d if follow else -d, stop_atr * atr, 0, hold)
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
