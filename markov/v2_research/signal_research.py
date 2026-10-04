"""SIGNAL RESEARCH ENGINE — the honest way to build the new bot.

Everything the old 18-pair bot got wrong, inverted:

  OLD                                    NEW
  ---------------------------------      ------------------------------------
  shipped signals with no proof          nothing trades until it PASSES a gate
  momentum bias + squeeze/market entry   simple, separable, testable rules
  net_pips (sums BTC + FX pips)          R-multiples only, per instrument
  one blended 18-pair edge               per-(instrument, strategy) edges
  no walk-forward, no deflation          walk-forward thirds + Deflated Sharpe
  never looked at outcomes               the gate IS the outcome check

Method: sweep a handful of well-founded strategies × a few params × every
instrument on 2y of DAILY bars (less noise than the old hourly). Resolve each
trade on real forward bars (ATR stop, fixed R:R). Score by expectancy in R,
then keep ONLY combos that are (a) positive, (b) positive in >=2/3 chronological
thirds, and (c) survive the Deflated Sharpe Ratio — DSR deflates the best
result by HOW MANY combos we tried, which is exactly the overfitting the old
bot never guarded against.

Run:  python signal_research.py          (writes survivors.json + prints table)
"""
from __future__ import annotations
import json
import math
from datetime import datetime
from pathlib import Path

try:
    import truststore; truststore.inject_into_ssl()
except Exception:
    pass
import urllib.request

HERE = Path(__file__).resolve().parent
OUT = HERE / "survivors.json"
HDR = {"User-Agent": "Mozilla/5.0"}

# instrument -> yahoo ticker (daily). Mirrors the old bot's universe.
UNIVERSE = {
    "XAUUSD": "GC=F", "XAGUSD": "SI=F",
    "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "USDJPY=X",
    "USDCHF": "USDCHF=X", "AUDUSD": "AUDUSD=X", "NZDUSD": "NZDUSD=X",
    "USDCAD": "USDCAD=X", "GBPJPY": "GBPJPY=X", "EURJPY": "EURJPY=X",
    "EURGBP": "EURGBP=X",
    "BTCUSD": "BTC-USD", "ETHUSD": "ETH-USD",
    "USOIL": "CL=F", "NAS100": "NQ=F", "SPX500": "ES=F", "US30": "YM=F",
}


# ── data ──────────────────────────────────────────────────────────────────
def fetch_daily(ticker: str, rng: str = "2y"):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/%s"
           "?range=%s&interval=1d" % (urllib.parse.quote(ticker), rng))
    try:
        req = urllib.request.Request(url, headers=HDR)
        j = json.loads(urllib.request.urlopen(req, timeout=25).read())
        res = j["chart"]["result"][0]
        q = res["indicators"]["quote"][0]
        o, h, l, c = q["open"], q["high"], q["low"], q["close"]
        bars = []
        for i in range(len(c)):
            if None in (o[i], h[i], l[i], c[i]):
                continue
            bars.append((o[i], h[i], l[i], c[i]))
        return bars
    except Exception:
        return []


import urllib.parse  # noqa: E402  (kept next to use)


# ── indicators (own code) ─────────────────────────────────────────────────
def atr(bars, i, period=14):
    if i < period:
        return None
    s = 0.0
    for k in range(i - period + 1, i + 1):
        h, l, pc = bars[k][1], bars[k][2], bars[k - 1][3]
        s += max(h - l, abs(h - pc), abs(l - pc))
    return s / period


def ema_series(closes, period):
    k = 2 / (period + 1)
    out = [closes[0]]
    for x in closes[1:]:
        out.append(out[-1] + k * (x - out[-1]))
    return out


def rsi(closes, i, period=14):
    if i < period:
        return None
    g = l = 0.0
    for k in range(i - period + 1, i + 1):
        d = closes[k] - closes[k - 1]
        if d > 0:
            g += d
        else:
            l -= d
    if l == 0:
        return 100.0
    rs = (g / period) / (l / period)
    return 100 - 100 / (1 + rs)


# ── strategies: each yields (entry_index, "BUY"/"SELL") on a CLOSED bar ─────
def s_donchian(bars, n):
    closes = [b[3] for b in bars]
    out = []
    for i in range(n + 1, len(bars) - 1):
        hi = max(closes[i - n:i])
        lo = min(closes[i - n:i])
        if closes[i] > hi:
            out.append((i, "BUY"))
        elif closes[i] < lo:
            out.append((i, "SELL"))
    return out


def s_ma_trend(bars, fast, slow):
    closes = [b[3] for b in bars]
    ef, es = ema_series(closes, fast), ema_series(closes, slow)
    out = []
    for i in range(slow + 1, len(bars) - 1):
        if ef[i] > es[i] and ef[i - 1] <= es[i - 1]:
            out.append((i, "BUY"))
        elif ef[i] < es[i] and ef[i - 1] >= es[i - 1]:
            out.append((i, "SELL"))
    return out


def s_boll_revert(bars, n, dev):
    closes = [b[3] for b in bars]
    out = []
    for i in range(n + 1, len(bars) - 1):
        window = closes[i - n:i]
        m = sum(window) / n
        sd = (sum((x - m) ** 2 for x in window) / n) ** 0.5
        if closes[i] < m - dev * sd:
            out.append((i, "BUY"))       # fade the stretch
        elif closes[i] > m + dev * sd:
            out.append((i, "SELL"))
    return out


def s_rsi2(bars, lo, hi):
    """Connors RSI(2): buy deep oversold in an uptrend, sell overbought in a
    downtrend. Trend filter = 200-EMA."""
    closes = [b[3] for b in bars]
    e200 = ema_series(closes, 200)
    out = []
    for i in range(200, len(bars) - 1):
        r = rsi(closes, i, 2)
        if r is None:
            continue
        if closes[i] > e200[i] and r < lo:
            out.append((i, "BUY"))
        elif closes[i] < e200[i] and r > hi:
            out.append((i, "SELL"))
    return out


STRATS = []
for n in (20, 55):
    STRATS.append((f"donchian{n}", lambda b, n=n: s_donchian(b, n)))
for f, s in ((20, 50), (10, 30)):
    STRATS.append((f"matrend{f}_{s}", lambda b, f=f, s=s: s_ma_trend(b, f, s)))
for dev in (2.0, 2.5):
    STRATS.append((f"boll{dev}", lambda b, dev=dev: s_boll_revert(b, 20, dev)))
STRATS.append(("rsi2", lambda b: s_rsi2(b, 5, 95)))


# ── trade resolution (ATR stop, fixed R:R, no lookahead) ───────────────────
def resolve_trades(bars, entries, atr_mult=2.0, rr=2.0, res_window=60):
    trades = []
    for (i, d) in entries:
        a = atr(bars, i)
        if not a or a <= 0:
            continue
        entry = bars[i][3]
        if d == "BUY":
            sl, tp = entry - atr_mult * a, entry + atr_mult * a * rr
        else:
            sl, tp = entry + atr_mult * a, entry - atr_mult * a * rr
        res = None
        for k in range(i + 1, min(len(bars), i + 1 + res_window)):
            h, l = bars[k][1], bars[k][2]
            if d == "BUY":
                if l <= sl:
                    res = "LOSS"; break
                if h >= tp:
                    res = "WIN"; break
            else:
                if h >= sl:
                    res = "LOSS"; break
                if l <= tp:
                    res = "WIN"; break
        if res:
            trades.append((i, rr if res == "WIN" else -1.0))
    return trades


# ── validation stats ───────────────────────────────────────────────────────
def sharpe(rs):
    n = len(rs)
    if n < 2:
        return 0.0
    mu = sum(rs) / n
    sd = (sum((x - mu) ** 2 for x in rs) / (n - 1)) ** 0.5
    return mu / sd if sd else 0.0


def norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def psr(rs, sr_star=0.0):
    n = len(rs)
    if n < 3:
        return 0.0
    mu = sum(rs) / n
    sd = (sum((x - mu) ** 2 for x in rs) / (n - 1)) ** 0.5
    if sd == 0:
        return 0.0
    sr = mu / sd
    g3 = (sum((x - mu) ** 3 for x in rs) / n) / sd ** 3
    g4 = (sum((x - mu) ** 4 for x in rs) / n) / sd ** 4
    denom = math.sqrt(max(1e-9, 1 - g3 * sr + (g4 - 1) / 4 * sr ** 2))
    return norm_cdf((sr - sr_star) * math.sqrt(n - 1) / denom)


def dsr(rs, all_trial_sharpes):
    nt = max(1, len(all_trial_sharpes))
    if nt < 2:
        sr_star = 0.0
    else:
        m = sum(all_trial_sharpes) / nt
        var = sum((s - m) ** 2 for s in all_trial_sharpes) / (nt - 1)
        euler = 0.5772156649
        e_max = math.sqrt(2 * math.log(nt)) - (euler + math.log(nt)) / (2 * math.sqrt(2 * math.log(nt)))
        sr_star = math.sqrt(var) * e_max
    return psr(rs, sr_star)


def thirds_positive(trades):
    if len(trades) < 6:
        return 0, 0
    rs = [r for _, r in trades]
    t = len(rs) // 3
    segs = [rs[:t], rs[t:2 * t], rs[2 * t:]]
    pos = sum(1 for s in segs if s and sum(s) / len(s) > 0)
    return pos, 3


# ── sweep ──────────────────────────────────────────────────────────────────
def main():
    data = {}
    for sym, tk in UNIVERSE.items():
        b = fetch_daily(tk)
        if len(b) > 260:
            data[sym] = b

    results = []       # every (sym, strat, params) combo we evaluated
    trial_sharpes = []
    for sym, bars in data.items():
        for name, fn in STRATS:
            entries = fn(bars)
            for atr_mult, rr in ((2.0, 2.0), (2.0, 3.0), (3.0, 2.0)):
                trades = resolve_trades(bars, entries, atr_mult, rr)
                if len(trades) < 12:
                    continue
                rs = [r for _, r in trades]
                exp = sum(rs) / len(rs)
                sh = sharpe(rs)
                trial_sharpes.append(sh)
                pos, tot = thirds_positive(trades)
                results.append({
                    "instrument": sym, "strategy": name,
                    "atr_mult": atr_mult, "rr": rr,
                    "trades": len(trades),
                    "win_rate": round(100 * sum(1 for r in rs if r > 0) / len(rs), 1),
                    "expectancy_r": round(exp, 3),
                    "net_r": round(sum(rs), 2),
                    "sharpe": round(sh, 3),
                    "thirds_positive": pos,
                    "_rs": rs,
                })

    # DSR uses the WHOLE set of trial Sharpes = honest deflation for the search
    for r in results:
        r["dsr"] = round(dsr(r["_rs"], trial_sharpes), 3)
        r["psr"] = round(psr(r["_rs"], 0.0), 3)

    survivors = [r for r in results
                 if r["expectancy_r"] > 0
                 and r["thirds_positive"] >= 2
                 and r["dsr"] >= 0.95]
    survivors.sort(key=lambda r: (-r["dsr"], -r["expectancy_r"]))
    for r in results:
        r.pop("_rs", None)
    for r in survivors:
        r.pop("_rs", None)

    out = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "instruments_with_data": len(data),
        "combos_tested": len(results),
        "gate": "expectancy>0 AND >=2/3 thirds positive AND DSR>=0.95 (deflated over ALL combos tried)",
        "survivors": survivors,
        "n_survivors": len(survivors),
        "top_10_by_dsr": sorted(results, key=lambda r: -r["dsr"])[:10],
    }
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")

    print("SIGNAL RESEARCH — %d instruments, %d combos tested" %
          (len(data), len(results)))
    print("SURVIVORS (passed expectancy + walk-forward + DSR>=0.95): %d" %
          len(survivors))
    for r in survivors[:25]:
        print("  %-7s %-12s atr%.0f rr%.0f | %3d tr · %4.1f%% · exp %+.3fR · DSR %.3f · thirds %d/3"
              % (r["instrument"], r["strategy"], r["atr_mult"], r["rr"],
                 r["trades"], r["win_rate"], r["expectancy_r"], r["dsr"],
                 r["thirds_positive"]))
    if not survivors:
        print("  NONE. Honest result — no combo in this sweep beats the deflation.")
        print("  Best by DSR (still failed the gate):")
        for r in out["top_10_by_dsr"][:5]:
            print("    %-7s %-12s exp %+.3fR DSR %.3f thirds %d/3"
                  % (r["instrument"], r["strategy"], r["expectancy_r"], r["dsr"],
                     r["thirds_positive"]))


if __name__ == "__main__":
    main()
