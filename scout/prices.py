"""Price scout — pulls commodity prices from Yahoo's chart API and computes
trend/momentum/volatility metrics. Pure-python (no yfinance/curl).

Windows SSL fixed via truststore (uses the OS cert store), same as STAALWAG.
"""
import warnings
warnings.filterwarnings("ignore")

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass
import requests

from .regime import regime as _regime

_HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
# Intraday resolution: hourly bars so trend/momentum move through the day
# (daily bars made FX look frozen). MA20/50 + momentum now read the intraday trend.
_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{t}?range=1mo&interval=60m"


def _ma(vals, n):
    if len(vals) < n:
        return None
    return sum(vals[-n:]) / n


def price_metrics(ticker):
    try:
        r = requests.get(_URL.format(t=ticker), headers=_HDR, timeout=20)
        j = r.json()
        res = j["chart"]["result"][0]
        q = res["indicators"]["quote"][0]
        closes = [c for c in q["close"] if c is not None]
        highs  = [h for h in q["high"]  if h is not None]
        lows   = [l for l in q["low"]   if l is not None]
    except Exception as e:
        print(f"  [prices] {ticker} fetch failed: {e}")
        return None
    if len(closes) < 60:
        print(f"  [prices] {ticker} insufficient data ({len(closes)})")
        return None

    last = closes[-1]
    ma20, ma50 = _ma(closes, 20), _ma(closes, 50)
    if not last or not ma20 or not ma50 or last <= 0:
        return None
    mom20 = (closes[-1] / closes[-21] - 1) * 100 if len(closes) >= 21 else 0.0
    n = min(14, len(highs), len(lows))
    tr = sum(highs[-n:][i] - lows[-n:][i] for i in range(n)) / n if n else 0.0
    atr_pct = tr / last * 100

    return {
        "last": round(last, 2),
        "ma20": round(ma20, 2),
        "ma50": round(ma50, 2),
        "mom20": round(mom20, 2),
        "atr_pct": round(atr_pct, 2),
        "above_ma20": last > ma20,
        "above_ma50": last > ma50,
        "ma_stack_up": ma20 > ma50,
        "regime": _regime(closes),
    }
