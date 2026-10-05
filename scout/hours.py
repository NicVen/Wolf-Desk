"""Prime Hours — when each market really moves.

From ~2 years of hourly Yahoo bars, works out for one symbol:
  * how much it moves in each hour of the day (UTC), scored 0-100
  * the PRIME window (the busiest run of hours) and the DEAD zone (the quietest)
  * the best weekdays (average hourly movement per day of the week)

The app shifts the UTC hours into the trader's own time zone. Pure maths over
real prices: no AI, no hand-typed inputs. Built once a week, served as
data/prime_hours.json.

Run on the VPS/PC (Yahoo is reachable there):  python -m scout.hours
"""
import json
import os
import time
from datetime import datetime, timezone

_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{t}?range=730d&interval=60m"
_HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
OUT = os.path.join("data", "prime_hours.json")
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def profile(times, highs, lows, closes, window=3):
    """Hour-of-day movement profile from parallel lists of hourly bars.

    times are unix seconds. Movement = (high - low) / close, so gold at 4,000
    and EURUSD at 1.10 compare on the same scale. Returns None with too little
    data (under 20 trading days)."""
    by_hour = [[] for _ in range(24)]
    by_day = [[] for _ in range(7)]
    days_seen = set()
    for t, h, l, c in zip(times, highs, lows, closes):
        if t is None or h is None or l is None or not c or h < l:
            continue
        d = datetime.fromtimestamp(t, tz=timezone.utc)
        m = (h - l) / c * 100
        by_hour[d.hour].append(m)
        by_day[d.weekday()].append(m)
        days_seen.add(d.date())
    if len(days_seen) < 20:
        return None
    avg = [sum(v) / len(v) if v else 0.0 for v in by_hour]
    # An hour that only trades now and then (a thin pre-open bar) isn't a real
    # trading hour: keep it out of the prime/dead search.
    need = max(5, len(days_seen) // 4)
    live = [len(v) >= need for v in by_hour]
    top = max(avg) or 1.0
    score = [round(a / top * 100) if live[i] else 0 for i, a in enumerate(avg)]

    def run(best):
        pick = None
        for s in range(24):
            hrs = [(s + k) % 24 for k in range(window)]
            if not all(live[h] for h in hrs):
                continue
            v = sum(avg[h] for h in hrs)
            if pick is None or (v > pick[0] if best else v < pick[0]):
                pick = (v, s)
        return None if pick is None else {"start": pick[1], "end": (pick[1] + window) % 24}

    day_avg = [sum(v) / len(v) if v else None for v in by_day]
    traded = [i for i in range(7) if day_avg[i] is not None and len(by_day[i]) >= need]
    dtop = max([day_avg[i] for i in traded] or [1.0]) or 1.0
    return {
        "hours": score,                 # 24 values, index = UTC hour
        "prime": run(True),             # {"start": UTC hour, "end": UTC hour}
        "dead": run(False),
        "days": [{"day": DAYS[i], "score": round(day_avg[i] / dtop * 100)} for i in traded],
        "bars": sum(len(v) for v in by_hour),
        "trading_days": len(days_seen),
    }


def _fetch(ticker):
    import requests
    r = requests.get(_URL.format(t=ticker), headers=_HDR, timeout=30)
    res = r.json()["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    return res["timestamp"], q["high"], q["low"], q["close"]


def _app_symbols():
    """Every (ticker, name) the app already shows, from the built class files."""
    seen = {}
    for cls in ("commodities", "fx", "indices", "stocks", "crypto"):
        try:
            with open(os.path.join("data", "opportunities_%s.json" % cls)) as f:
                for o in json.load(f).get("opportunities", []):
                    if o.get("ticker") and o["ticker"] not in seen:
                        seen[o["ticker"]] = o.get("name") or o["ticker"]
        except Exception:
            pass
    return seen


def build(out=OUT, pause=0.5):
    """Fetch every app symbol, write data/prime_hours.json. A symbol that fails
    keeps its previous profile rather than vanishing."""
    try:
        with open(out) as f:
            old = json.load(f).get("symbols", {})
    except Exception:
        old = {}
    syms = {}
    for ticker, name in _app_symbols().items():
        try:
            p = profile(*_fetch(ticker))
        except Exception as e:
            print(f"  [hours] {ticker} failed: {e}")
            p = None
        if p:
            p["name"] = name
            syms[ticker] = p
        elif ticker in old:
            syms[ticker] = old[ticker]
        time.sleep(pause)
    data = {"built": int(time.time()), "source": "Yahoo hourly bars, ~2 years", "symbols": syms}
    tmp = out + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    os.replace(tmp, out)
    print(f"  [hours] wrote {len(syms)} symbols to {out}")
    return data


if __name__ == "__main__":
    build()
