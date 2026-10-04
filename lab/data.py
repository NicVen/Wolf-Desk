"""Free price history from Yahoo's chart API (no key).

1h bars go back about 730 days; daily bars go back decades. Runs on the GitHub
runner or the VPS (Claude's cloud container can't reach Yahoo).
"""
import json
import urllib.request

URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval={iv}"


def bars(sym: str, interval: str = "60m", rng: str = "730d") -> list[dict]:
    req = urllib.request.Request(URL.format(sym=sym, rng=rng, iv=interval),
                                 headers={"User-Agent": "Mozilla/5.0"})
    res = json.load(urllib.request.urlopen(req, timeout=30))["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    out = []
    for t, o, h, l, c in zip(res["timestamp"], q["open"], q["high"], q["low"], q["close"]):
        if None in (o, h, l, c):
            continue
        out.append({"t": t, "o": o, "h": h, "l": l, "c": c})
    return out
