"""Carry trade test: the oldest proven edge in FX.

Hold the currencies that pay high interest, sell the ones that pay little, and
collect the difference every day. Rebalanced once a month.

    python lab/carry.py

Honest costs: spread on every position every month (no netting), plus a broker
swap markup of 1% a year taken off the interest on BOTH sides. Interest rates
are central-bank policy rates from the BIS (free, no key; FRED as backup); a month's rate
is only used from the next month on. Pass bar (monthly returns): profit factor
>= 1.3 in both halves, at least 60 months, and better than picking currencies
at random (luck).
"""
import csv
import io
import math
import random
import urllib.request
from datetime import datetime, timezone

import data

FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
USD_RATE = "IR3TIB01USM156N"
# currency: (yahoo symbol, +1 if the symbol is USD per currency, FRED rate, round-trip cost %)
CCY = {
    "EUR": ("EURUSD=X", 1, "IR3TIB01EZM156N", 0.02),
    "GBP": ("GBPUSD=X", 1, "IR3TIB01GBM156N", 0.02),
    "JPY": ("JPY=X", -1, "IR3TIB01JPM156N", 0.02),
    "AUD": ("AUDUSD=X", 1, "IR3TIB01AUM156N", 0.03),
    "NZD": ("NZDUSD=X", 1, "IR3TIB01NZM156N", 0.04),
    "CAD": ("CAD=X", -1, "IR3TIB01CAM156N", 0.03),
    "CHF": ("CHF=X", -1, "IR3TIB01CHM156N", 0.03),
    "NOK": ("NOK=X", -1, "IR3TIB01NOM156N", 0.06),
    "SEK": ("SEK=X", -1, "IR3TIB01SEM156N", 0.06),
    "MXN": ("MXN=X", -1, "IR3TIB01MXM156N", 0.10),
    "ZAR": ("ZAR=X", -1, "IR3TIB01ZAM156N", 0.15),
}
G10 = ["EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF", "NOK", "SEK"]
SWAP_MARKUP = 1.0      # % a year the broker keeps on each side
LEGS = 3               # long top 3, short bottom 3
TREND_DAYS = 63        # about 3 months
LUCK_RUNS = 20
AREA = {USD_RATE: "US", "IR3TIB01EZM156N": "XM", "IR3TIB01GBM156N": "GB",
        "IR3TIB01JPM156N": "JP", "IR3TIB01AUM156N": "AU", "IR3TIB01NZM156N": "NZ",
        "IR3TIB01CAM156N": "CA", "IR3TIB01CHM156N": "CH", "IR3TIB01NOM156N": "NO",
        "IR3TIB01SEM156N": "SE", "IR3TIB01MXM156N": "MX", "IR3TIB01ZAM156N": "ZA"}


BIS = ("https://stats.bis.org/api/v1/data/WS_CBPOL/M.{area}/all?format=csv",
       "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/M.{area}?format=csv")


def _csv(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=45).read().decode()


def fred(sid):
    """{(year, month): rate %}. Central-bank policy rates from the BIS (free, no
    key) first, then the OECD 3-month rate from FRED if the BIS is down."""
    area = AREA[sid]
    for url in BIS:
        try:
            rows = list(csv.DictReader(io.StringIO(_csv(url.format(area=area)))))
            out = {}
            for r in rows:
                try:
                    d, v = r["TIME_PERIOD"], float(r["OBS_VALUE"])
                except (KeyError, ValueError, TypeError):
                    continue
                out[(int(d[:4]), int(d[5:7]))] = v
            if out:
                return out
        except Exception as e:
            print(f"(BIS {area}: {e})")
    out = {}
    for row in list(csv.reader(io.StringIO(_csv(FRED.format(sid=sid)))))[1:]:
        try:
            d, v = row[0], float(row[1])
        except (IndexError, ValueError):
            continue
        out[(int(d[:4]), int(d[5:7]))] = v
    return out


def known_rate(series, y, m):
    """Rate a trader knew at the start of month (y, m): last month's average.
    None if the series has no value within the last 3 months (stale)."""
    for back in range(1, 4):
        k = (y, m - back) if m - back >= 1 else (y - 1, m - back + 12)
        if k in series:
            return series[k]
    return None


def load():
    usd = fred(USD_RATE)
    px, rates = {}, {}
    for c, (sym, sign, sid, _) in CCY.items():
        try:
            b = data.bars(sym, "1d", "20y")  # "max" silently gives monthly bars
            r = fred(sid)
        except Exception as e:
            print(f"(skipped {c}: {e})")
            continue
        # value of 1 unit of the currency in USD, by calendar day
        px[c] = {datetime.fromtimestamp(x["t"], tz=timezone.utc).date(): (x["c"] if sign > 0 else 1 / x["c"])
                 for x in b if x["c"] > 0}
        rates[c] = r
        last = max(r) if r else None
        print(f"({c}: {len(b)} daily prices from {min(px[c])}, rates to {last})")
    return usd, px, rates


def backtest(usd, px, rates, ccys, trend=False, pick=None):
    """Monthly returns in % of the money in play, oldest first: [(month, ret)]."""
    days = sorted(set().union(*(px[c].keys() for c in ccys)))
    months, out = {}, []
    for d in days:
        months.setdefault((d.year, d.month), []).append(d)
    keys = sorted(months)
    for i, (y, m) in enumerate(keys[:-1]):
        start, end = months[(y, m)][0], months[keys[i + 1]][0]
        ur = known_rate(usd, y, m)
        if ur is None:
            continue
        diffs = {}
        for c in ccys:
            r = known_rate(rates[c], y, m)
            if r is None or start not in px[c] or end not in px[c]:
                continue
            diffs[c] = r - ur
        if len(diffs) < 2 * LEGS:
            continue
        ranked = sorted(diffs, key=diffs.get, reverse=True)
        if pick:                                    # luck benchmark: random picks
            pick.shuffle(ranked)
        legs = [(c, 1) for c in ranked[:LEGS]] + [(c, -1) for c in ranked[-LEGS:]]
        if trend:                                   # keep a leg only if price agrees
            past = [d for d in days if d < start]
            if len(past) < TREND_DAYS:
                continue
            ref = past[-TREND_DAYS]
            legs = [(c, s) for c, s in legs
                    if ref in px[c] and s * (px[c][start] / px[c][ref] - 1) > 0]
        if not legs:
            out.append(((y, m), 0.0))
            continue
        span = (end - start).days / 365
        rets = []
        for c, s in legs:
            move = 100 * s * (px[c][end] / px[c][start] - 1)
            carry = (s * diffs[c] - SWAP_MARKUP) * span
            rets.append(move + carry - CCY[c][3])
        # money split equally over all 2*LEGS slots; an empty slot sits in cash
        out.append(((y, m), sum(rets) / (2 * LEGS)))
    return out


def stats(rets):
    if not rets:
        return {"n": 0, "pf": 0, "pos": 0, "yr": 0, "dd": 0}
    r = [x for _, x in rets]
    gain, loss = sum(x for x in r if x > 0), -sum(x for x in r if x < 0)
    eq, peak, dd = 1.0, 1.0, 0.0
    for x in r:
        eq *= 1 + x / 100
        peak = max(peak, eq)
        dd = max(dd, 1 - eq / peak)
    return {"n": len(r), "pf": round(gain / loss, 2) if loss else 99.0,
            "pos": round(100 * sum(x > 0 for x in r) / len(r)),
            "yr": round(100 * (eq ** (12 / len(r)) - 1), 1), "dd": round(100 * dd, 1)}


def scorecard(name, usd, px, rates, ccys, trend):
    rets = backtest(usd, px, rates, ccys, trend)
    half = len(rets) // 2
    s, a, b = stats(rets), stats(rets[:half]), stats(rets[half:])
    l12 = stats(rets[-12:])
    lucks = sorted(stats(backtest(usd, px, rates, ccys, trend, random.Random(k)))["pf"]
                   for k in range(LUCK_RUNS))
    luck = lucks[int(0.95 * (LUCK_RUNS - 1))]
    ok = a["pf"] >= 1.3 and b["pf"] >= 1.3 and s["n"] >= 60 and s["pf"] > luck
    span = f"{rets[0][0][0]}-{rets[-1][0][0]}" if rets else ""
    print(f"| {name} | {span} | {s['n']} | {s['pos']}% | {s['pf']} | {a['pf']} | {b['pf']} | "
          f"{l12['yr']}% | {s['yr']}% | {s['dd']}% | {luck} | {'PASS' if ok else 'no'} |")


def main():
    usd, px, rates = load()
    allc = [c for c in CCY if c in px]
    g10 = [c for c in G10 if c in px]
    print("\n## VELDRIN: carry trade (hold high-interest currencies, sell low-interest ones)\n")
    print("| rule | years | months | months up | PF (monthly) | PF 1st half | PF 2nd half | "
          "last 12m | per year | worst drawdown | luck PF (95%) | verdict |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    scorecard("carry, G10 + MXN/ZAR", usd, px, rates, allc, False)
    scorecard("carry + 3-month trend, G10 + MXN/ZAR", usd, px, rates, allc, True)
    scorecard("carry, G10 only", usd, px, rates, g10, False)
    scorecard("carry + 3-month trend, G10 only", usd, px, rates, g10, True)
    print(f"\nCosts: spread every month on every position, swap markup {SWAP_MARKUP}%/yr "
          "on each side. Returns are on the money in play, no leverage.")


if __name__ == "__main__":
    main()
