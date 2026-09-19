"""Price scout — pulls prices from Yahoo's chart API and computes
trend/momentum/volatility metrics. Pure-python (no yfinance/curl).

Two timeframes per instrument:
  * 1H  — range=1mo, interval=60m  (the primary read: scoring, verdict, chart)
  * Daily — range=1y, interval=1d  (attached as `daily`, for the app's toggle)

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
# (daily bars made FX look frozen). MA20/50 + momentum read the intraday trend.
_URL_1H = "https://query1.finance.yahoo.com/v8/finance/chart/{t}?range=1mo&interval=60m"
# Daily resolution: a year of daily bars for the swing/positional view.
_URL_1D = "https://query1.finance.yahoo.com/v8/finance/chart/{t}?range=1y&interval=1d"


def _ma(vals, n):
    if len(vals) < n:
        return None
    return sum(vals[-n:]) / n


def _fetch(ticker, url):
    """Return (closes, highs, lows) with Nones stripped, or None on failure."""
    try:
        r = requests.get(url.format(t=ticker), headers=_HDR, timeout=20)
        j = r.json()
        res = j["chart"]["result"][0]
        q = res["indicators"]["quote"][0]
        closes = [c for c in q["close"] if c is not None]
        highs  = [h for h in q["high"]  if h is not None]
        lows   = [l for l in q["low"]   if l is not None]
        return closes, highs, lows
    except Exception as e:
        print(f"  [prices] {ticker} fetch failed: {e}")
        return None


def _metrics_core(closes, highs, lows, min_bars=60):
    """Metrics common to any timeframe. None if there isn't enough data."""
    if len(closes) < min_bars:
        return None
    last = closes[-1]
    ma20, ma50 = _ma(closes, 20), _ma(closes, 50)
    if not last or not ma20 or not ma50 or last <= 0:
        return None
    mom20 = (closes[-1] / closes[-21] - 1) * 100 if len(closes) >= 21 else 0.0
    n = min(14, len(highs), len(lows))
    tr = sum(highs[-n:][i] - lows[-n:][i] for i in range(n)) / n if n else 0.0
    atr_pct = tr / last * 100
    # recent structural swing extremes (last ~20 bars) — for structure-based stops.
    sw = min(20, len(highs), len(lows))
    swing_lo = min(lows[-sw:]) if sw else None
    swing_hi = max(highs[-sw:]) if sw else None
    # compact recent-price series for the app's direction chart (~48 points).
    tail = closes[-60:]
    if len(tail) > 48:
        step = len(tail) / 48.0
        tail = [tail[int(i * step)] for i in range(48)]
    spark = [round(c, 4) for c in tail]
    return {
        "last": round(last, 4),
        "ma20": round(ma20, 4),
        "ma50": round(ma50, 4),
        "mom20": round(mom20, 2),
        "atr_pct": round(atr_pct, 2),
        "atr_abs": round(tr, 6),
        "above_ma20": last > ma20,
        "above_ma50": last > ma50,
        "ma_stack_up": ma20 > ma50,
        "swing_lo": round(swing_lo, 6) if swing_lo is not None else None,
        "swing_hi": round(swing_hi, 6) if swing_hi is not None else None,
        "regime": _regime(closes),
        "spark": spark,
    }


def price_metrics(ticker):
    """Primary (1H) metrics for scoring, plus a `daily` block for the app toggle."""
    got = _fetch(ticker, _URL_1H)
    if not got:
        return None
    closes, highs, lows = got
    m = _metrics_core(closes, highs, lows)
    if m is None:
        print(f"  [prices] {ticker} insufficient 1H data ({len(closes)})")
        return None

    # per-bar returns for statistical validation (DSR). Transient: the caller
    # uses it to compute the validation label and does NOT persist it.
    m["returns"] = [closes[i] / closes[i - 1] - 1.0
                    for i in range(1, len(closes)) if closes[i - 1]]

    # daily block — best effort; the toggle just hides if it's missing.
    dgot = _fetch(ticker, _URL_1D)
    if dgot:
        dm = _metrics_core(dgot[0], dgot[1], dgot[2], min_bars=55)
        if dm is not None:
            m["daily"] = dm

    return m
