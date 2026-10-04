"""Published edges for gold and FX, tested on free data with costs.

    python lab/research.py

Each idea comes from a paper (named next to it). Rules are taken as published,
never tuned here. Results are % returns per trade (or per month) after costs.
Pass bar: profit factor >= 1.3 in BOTH halves, at least 30 trades, and better
than the same trades with random directions (luck, 95th percentile of 20).
"""
import random
import re
import urllib.request
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import carry
import data

NY, LDN = ZoneInfo("America/New_York"), ZoneInfo("Europe/London")
LUCK_RUNS = 20


# ---------- scorecard ----------

def pf(rs):
    g, l = sum(r for r in rs if r > 0), -sum(r for r in rs if r < 0)
    return round(g / l, 2) if l else (99.0 if g else 0.0)


def card(name, trades, unit="trades", note=""):
    """trades: [(ts, ret%)] oldest first, costs already taken off."""
    if not trades:
        print(f"| {name} | 0 | | | | | | | | no data | {note} |")
        return
    trades = sorted(trades)
    rs = [r for _, r in trades]
    half = trades[len(trades) // 2][0]
    a = [r for t, r in trades if t < half]
    b = [r for t, r in trades if t >= half]
    yrs = max((trades[-1][0] - trades[0][0]) / 31557600, 0.5)
    last = [r for t, r in trades if t >= trades[-1][0] - 365 * 86400]
    rng = random.Random(7)
    lucks = sorted(pf([r * rng.choice((1, -1)) for r in rs]) for _ in range(LUCK_RUNS))
    luck = lucks[int(0.95 * (LUCK_RUNS - 1))]
    ok = pf(a) >= 1.3 and pf(b) >= 1.3 and len(rs) >= 30 and pf(rs) > luck
    win = round(100 * sum(r > 0 for r in rs) / len(rs))
    span = f"{datetime.fromtimestamp(trades[0][0], timezone.utc).year}-{datetime.fromtimestamp(trades[-1][0], timezone.utc).year}"
    print(f"| {name} | {len(rs)} {unit} | {span} | {win}% | {pf(rs)} | {pf(a)} | {pf(b)} | "
          f"{pf(last)} | {sum(rs) / yrs:+.1f}% | {luck} | {'PASS' if ok else 'no'} | {note} |")


HEAD = ("| idea | trades | years | win | PF | PF 1st half | PF 2nd half | PF last 12m | "
        "return per year | luck PF (95%) | verdict | note |\n|---|---|---|---|---|---|---|---|---|---|---|---|")


def ema(xs, n):
    k, e, out = 2 / (n + 1), xs[0], []
    for x in xs:
        e = x * k + e * (1 - k)
        out.append(e)
    return out


# ---------- 1. gold: overnight vs day (Blose, Gondhalekar & Kort 2018) ----------

def gold_overnight():
    print("\n## 1. Gold earns overnight, not in US hours (J. Economics & Finance 2018)\n")
    print(HEAD)
    d = data.bars("GLD", "1d", "20y")              # NYSE hours: open 9:30, close 16:00 ET
    cost = 0.015                                    # % per trade, about 0.45 on spot gold
    c = [x["c"] for x in d]
    e50, e200 = ema(c, 50), ema(c, 200)
    night = [(d[i]["t"], 100 * (d[i]["o"] / d[i - 1]["c"] - 1) - cost) for i in range(1, len(d))]
    day = [(x["t"], 100 * (x["c"] / x["o"] - 1) - cost) for x in d]
    hold = [(d[i]["t"], 100 * (d[i]["c"] / d[i - 1]["c"] - 1)) for i in range(1, len(d))]
    trend = [(d[i]["t"], r) for i, (_, r) in enumerate(night, 1) if e50[i - 1] > e200[i - 1]]
    card("gold long overnight (US close to US open), daily since 2004", night, "nights")
    card("gold long in US hours (open to close)", day, "days", "the opposite leg")
    card("gold held all day and night (no cost)", hold, "days", "benchmark")
    card("gold overnight, only when daily trend is up", trend, "nights")
    # hourly COMEX: long 14:00 ET (after the day session) to 08:00 ET next day
    h = data.bars("GC=F", "60m", "730d")
    trades, entry = [], None
    for b in h:
        et = datetime.fromtimestamp(b["t"], NY)
        if et.hour == 13 and entry is None:
            entry = (b["t"], b["c"])
        elif et.hour == 8 and entry and b["t"] - entry[0] < 30 * 3600:
            trades.append((entry[0], 100 * ((b["o"] - 0.45) / entry[1] - 1)))
            entry = None
        elif entry and b["t"] - entry[0] >= 30 * 3600:
            entry = None
    card("gold futures long 14:00-08:00 ET (hourly, 2 years)", trades, "nights", "cost 0.45")


# ---------- 2. FOMC day (Mueller, Tahbaz-Salehi & Vedolin, J. Finance 2017) ----------

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"


def fomc_dates():
    """Announcement days of scheduled FOMC meetings, from the Fed's own pages."""
    out = set()
    pages = ["https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"]
    pages += [f"https://www.federalreserve.gov/monetarypolicy/fomchistorical{y}.htm" for y in range(2006, 2021)]
    for url in pages:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
        except Exception as e:
            print(f"(FOMC page {url[-22:]}: {e})")
            continue
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text)
        if "historical" in url:
            y = int(url[-8:-4])
            for m in re.finditer(rf"({MONTHS})\s+(\d{{1,2}})(?:\s*-\s*(?:({MONTHS})\s+)?(\d{{1,2}}))?\s+Meeting", text):
                if "nscheduled" in text[m.end():m.end() + 40] or "onference" in text[m.end():m.end() + 30]:
                    continue
                mon = m.group(3) or m.group(1)
                day = int(m.group(4) or m.group(2))
                out.add(date(y, MONTHS.split("|").index(mon) + 1, day))
        else:
            for ym in re.finditer(r"(20\d\d) FOMC Meetings(.*?)(?=20\d\d FOMC Meetings|$)", text):
                y = int(ym.group(1))
                for m in re.finditer(rf"({MONTHS})(?:/({MONTHS}))?\s+(\d{{1,2}})\s*-\s*(\d{{1,2}})(\*?)", ym.group(2)):
                    mon = m.group(2) or m.group(1)
                    out.add(date(y, MONTHS.split("|").index(mon) + 1, int(m.group(4))))
    return sorted(out)


def fomc():
    print("\n## 2. FOMC announcement days: short the dollar (J. Finance 2017)\n")
    days = fomc_dates()
    by_year = {}
    for d in days:
        by_year[d.year] = by_year.get(d.year, 0) + 1
    print("(FOMC days found per year: " + ", ".join(f"{y}:{n}" for y, n in sorted(by_year.items())) + ")\n")
    print(HEAD)
    legs = {"AUDUSD=X": 1, "NZDUSD=X": 1, "EURUSD=X": 1, "JPY=X": -1}
    px = {}
    for s in list(legs) + ["GC=F"]:
        b = data.bars(s, "1d", "20y")
        px[s] = {datetime.fromtimestamp(x["t"], timezone.utc).date(): x["c"] for x in b}

    def day_ret(s, d):
        ds = sorted(k for k in px[s] if k <= d)
        if not ds or ds[-1] != d or len(ds) < 2:
            return None
        return 100 * (px[s][d] / px[s][ds[-2]] - 1)

    fset = set(days)
    basket, hy, gold, other = [], [], [], []
    for d in days:
        rs = [legs[s] * day_ret(s, d) for s in legs if day_ret(s, d) is not None]
        ts = datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()
        if len(rs) == 4:
            basket.append((ts, sum(rs) / 4 - 0.012))
            hy.append((ts, (rs[0] + rs[1]) / 2 - 0.015))
        g = day_ret("GC=F", d)
        if g is not None:
            gold.append((ts, g - 0.015))
    card("short dollar basket (AUD, NZD, EUR, JPY) on FOMC day", basket, "days")
    card("long AUD + NZD vs USD on FOMC day", hy, "days")
    card("gold long on FOMC day", gold, "days", "no paper for gold: extension")
    since = [(t, r) for t, r in basket if t >= datetime(2011, 1, 1, tzinfo=timezone.utc).timestamp()]
    card("short dollar basket on FOMC day, 2011 on (after the paper)", since, "days", "out of sample")


# ---------- 3. currencies weaken in their own hours (Breedon & Ranaldo, SNB 2011) ----------

def own_hours():
    print("\n## 3. Currencies weaken in their own trading hours (SNB working paper 2011)\n")
    print(HEAD)
    rules = {   # symbol: [(tz, start hour, end hour, direction, label)]
        "EURUSD=X": [(LDN, 7, 12, -1, "short EUR, European morning"), (LDN, 16, 21, 1, "long EUR, US afternoon")],
        "JPY=X": [(timezone.utc, 0, 6, 1, "long USDJPY, Tokyo hours"), (LDN, 16, 21, -1, "short USDJPY, US afternoon")],
    }
    cost = {"EURUSD=X": 0.00012, "JPY=X": 0.012}
    for sym, legs in rules.items():
        h = data.bars(sym, "60m", "730d")
        allt = []
        for tz, s, e, d, label in legs:
            tr, entry = [], None
            for b in h:
                hr = datetime.fromtimestamp(b["t"], tz).hour
                if hr == s and entry is None:
                    entry = (b["t"], b["o"])
                elif hr == e and entry:
                    if b["t"] - entry[0] < 12 * 3600:
                        tr.append((entry[0], 100 * (d * (b["o"] - entry[1]) - cost[sym]) / entry[1]))
                    entry = None
            card(f"{sym[:6]}: {label}", tr, "days")
            allt += tr
        card(f"{sym[:6]}: both legs", allt, "legs")


# ---------- 4/5. dollar carry (Lustig, Roussanov & Verdelhan, JFE 2014), carry crash switch ----------

def monthly_card(name, rets, note=""):
    card(name, [(datetime(y, m, 1, tzinfo=timezone.utc).timestamp(), r) for (y, m), r in rets], "months", note)


def dollar_carry(usd, px, rates, ccys):
    days = sorted(set().union(*(px[c].keys() for c in ccys)))
    months = {}
    for d in days:
        months.setdefault((d.year, d.month), []).append(d)
    keys, out = sorted(months), []
    for i, (y, m) in enumerate(keys[:-1]):
        start, end = months[(y, m)][0], months[keys[i + 1]][0]
        ur = carry.known_rate(usd, y, m)
        fr = [(c, carry.known_rate(rates[c], y, m)) for c in ccys]
        fr = [(c, r) for c, r in fr if r is not None and start in px[c] and end in px[c]]
        if ur is None or len(fr) < 5:
            continue
        avg = sum(r for _, r in fr) / len(fr)
        s = 1 if avg > ur else -1            # +1 = short USD (long the basket)
        span = (end - start).days / 365
        move = sum(px[c][end] / px[c][start] - 1 for c, _ in fr) / len(fr) * 100
        out.append(((y, m), s * move + (s * (avg - ur) - carry.SWAP_MARKUP) * span - 0.03))
    return out


def carry_ideas():
    print("\n## 4-5. Dollar carry (J. Financial Economics 2014) and carry with a crash switch\n")
    usd, px, rates = carry.load()
    g10 = [c for c in carry.G10 if c in px]
    print("\n" + HEAD)
    monthly_card("dollar carry: short USD vs G10 when their rates are higher, else long", dollar_carry(usd, px, rates, g10))
    vix = data.bars("^VIX", "1d", "20y")
    vd = [(datetime.fromtimestamp(x["t"], timezone.utc).date(), x["c"]) for x in vix]
    calm, ok = set(), {}
    for i in range(252, len(vd)):         # state as of each day's close
        past = sorted(x for _, x in vd[i - 252:i])
        ok[vd[i][0]] = vd[i][1] < past[126] and vd[i][1] <= vd[i - 21][1]
    for d in sorted(ok):                   # a month is calm if the last close before it was
        nxt = (d.year + d.month // 12, d.month % 12 + 1)
        if ok[d]:
            calm.add(nxt)
        else:
            calm.discard(nxt)
    allc = [c for c in carry.CCY if c in px]
    base = carry.backtest(usd, px, rates, allc)
    monthly_card("carry (top 3 / bottom 3), only when VIX is calm and falling", [x for x in base if x[0] in calm])
    monthly_card("carry (top 3 / bottom 3), every month", base, "for comparison")


# ---------- 6/7. momentum (Moskowitz-Ooi-Pedersen 2012; Menkhoff et al. 2012) ----------

def momentum():
    print("\n## 6-7. Currency momentum, many pairs, monthly\n")
    print(HEAD)
    syms = ["EURUSD=X", "GBPUSD=X", "JPY=X", "AUDUSD=X", "NZDUSD=X", "CAD=X", "CHF=X",
            "EURJPY=X", "GBPJPY=X", "AUDJPY=X", "EURGBP=X", "EURCHF=X", "NOK=X", "SEK=X"]
    px = {}
    for s in syms:
        try:
            px[s] = [(datetime.fromtimestamp(x["t"], timezone.utc).date(), x["c"]) for x in data.bars(s, "1d", "20y")]
        except Exception as e:
            print(f"(skipped {s}: {e})")
    out = []
    firsts = {}
    for s, p in px.items():
        idx = {}
        for k, (d, c) in enumerate(p):
            idx.setdefault((d.year, d.month), k)
        firsts[s] = idx
    months = sorted(set().union(*(set(f) for f in firsts.values())))
    for i in range(13, len(months) - 1):
        ym, nxt = months[i], months[i + 1]
        tot, n = 0.0, 0
        for s, p in px.items():
            f = firsts[s]
            if not all(k in f for k in (months[i - 12], ym, nxt)):
                continue
            k0, k1, k2 = f[months[i - 12]], f[ym], f[nxt]
            if k1 < 61:
                continue
            sig = 1 if p[k1][1] > p[k0][1] else -1
            rets = [p[j][1] / p[j - 1][1] - 1 for j in range(k1 - 60, k1)]
            vol = (sum(r * r for r in rets) / len(rets)) ** 0.5 * 252 ** 0.5
            w = min(3.0, 0.10 / vol) if vol else 0
            span = (p[k2][0] - p[k1][0]).days / 365
            tot += w * (100 * sig * (p[k2][1] / p[k1][1] - 1) - carry.SWAP_MARKUP * span - 0.02)
            n += 1
        if n:
            out.append((ym, tot / n))
    monthly_card("trend: 12-month direction, 14 pairs, risk-balanced", out)


# ---------- 8. improve gold: time the live rule with the overnight effect ----------

def gold_timing():
    import run
    import strategies
    print("\n## 8. Gold channel rule, timed with the overnight effect\n")
    print("| rule | trades | per month | win | PF | PF 1st half | PF 2nd half | PF last 6m (n) | PF longs (n) | PF shorts (n) | total R | worst drawdown R | luck PF (95%) | verdict | detail |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    h = data.bars("GC=F", "60m", "730d")
    d = data.bars("GC=F", "1d", "20y")
    live = strategies.with_daily_trend(strategies.make_donchian, strategies.daily_trend(d))

    def hours(make, keep):
        def make2(bars):
            inner = make(bars)

            def s(bars, i):
                o = inner(bars, i)
                if o is None or not keep(datetime.fromtimestamp(bars[i]["t"], NY).hour):
                    return None
                return o
            return s
        return make2
    us = lambda hr: 8 <= hr < 14
    run.pooled("live Gold rule (as now)", [("GC", h, live, 0.45)])
    run.pooled("live Gold rule, only signals outside US hours", [("GC", h, hours(live, lambda hr: not us(hr)), 0.45)])
    run.pooled("live Gold rule, only signals in US hours", [("GC", h, hours(live, us), 0.45)])


# ---------- 9. the gold rule on other markets (a new home for VELDRIN?) ----------

MARKETS = {   # symbol: round-trip cost as a share of price
    "SI=F": 0.0008, "HG=F": 0.0008, "CL=F": 0.0005, "ES=F": 0.0002, "NQ=F": 0.0002,
    "YM=F": 0.0002, "BTC-USD": 0.001, "ETH-USD": 0.0015,
    "GBPJPY=X": 0.0002, "AUDJPY=X": 0.0002, "EURJPY=X": 0.0002, "NZDJPY=X": 0.0003,
    "CADJPY=X": 0.0003, "MXN=X": 0.0005, "ZAR=X": 0.0006,
}


def markets():
    import run
    import strategies
    print("\n## 9. The winning Gold rule (breakout + trend + daily trend) on other markets\n")
    print("| market | trades | per month | win | PF | PF 1st half | PF 2nd half | PF last 6m (n) | PF longs (n) | PF shorts (n) | total R | worst drawdown R | luck PF (95%) | verdict | detail |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for sym, pct in MARKETS.items():
        try:
            h = data.bars(sym, "60m", "730d")
            d = data.bars(sym, "1d", "20y")
        except Exception as e:
            print(f"| {sym} | | | | | | | | | | | | | no data | {e} |")
            continue
        live = strategies.with_daily_trend(strategies.make_donchian, strategies.daily_trend(d))
        run.pooled(sym, [(sym, h, live, h[-1]["c"] * pct)])


def main():
    for f in (gold_timing, markets, gold_overnight, fomc, own_hours, carry_ideas, momentum):
        try:
            f()
        except Exception as e:
            print(f"\n({f.__name__} failed: {type(e).__name__}: {e})")


if __name__ == "__main__":
    main()
