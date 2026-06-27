"""Builds the per-commodity 'case file' shown when a card is clicked:
price reasoning, score reasoning, outlook, BUY/SELL/WATCH verdict, and the
bull/bear argument backing it. Rule-based + deterministic (offline).

NOTE: this is the tool's mechanical read of the data, NOT financial advice.
"""
import config as C

LABEL = {"catalyst": "catalyst", "trend": "trend", "position": "positioning",
         "supply": "supply/demand", "volfit": "volatility fit"}
MAX = {"catalyst": C.W_CATALYST, "trend": C.W_TREND, "position": C.W_POSITION,
       "supply": C.W_SUPPLY, "volfit": C.W_VOLFIT}


def _verdict(r):
    up   = r.get("above_ma50") and r.get("ma_stack_up") and (r.get("mom20") or 0) > 0
    down = (not r.get("above_ma20")) and (not r.get("ma_stack_up")) and (r.get("mom20") or 0) < 0
    sc = r["score"]
    if up and sc >= 50:   return "BUY"
    if down:              return "SELL"
    if up:                return "BUY (weak)"
    return "WATCH"


def _conviction(sc):
    return ("High" if sc >= 65 else "Moderate" if sc >= 50 else
            "Low" if sc >= 40 else "Weak")


def _price_reasoning(r):
    p, m20, m50 = r.get("price"), r.get("ma20"), r.get("ma50")
    mom = r.get("mom20") or 0
    atr = r.get("atr_pct") or 0
    if None in (p, m20, m50):
        return "Price data unavailable."
    if r.get("above_ma50") and r.get("ma_stack_up"):
        struct = (f"Price {p} sits above both its 20-day ({m20}) and 50-day ({m50}) "
                  f"averages, with the 20 above the 50 — a confirmed uptrend.")
    elif not r.get("above_ma20") and not r.get("ma_stack_up"):
        struct = (f"Price {p} is below both its 20-day ({m20}) and 50-day ({m50}) "
                  f"averages — a confirmed downtrend.")
    else:
        struct = (f"Price {p} is mixed against its 20-day ({m20}) / 50-day ({m50}) "
                  f"averages — no clean trend yet.")
    momtxt = (f" 20-day momentum is {mom:+.1f}%, "
              + ("strong directional push." if abs(mom) >= 8 else
                 "moderate." if abs(mom) >= 3 else "flat."))
    voltxt = (f" Volatility (ATR {atr:.1f}% of price) is "
              + ("very high — big swings, size down." if atr > 5 else
                 "healthy and tradeable." if atr >= 1 else "low — quiet tape."))
    return struct + momtxt + voltxt


def _score_reasoning(r):
    bd = r["breakdown"]
    pct = {k: (bd[k] / MAX[k]) if MAX[k] else 0 for k in bd}
    top = sorted(pct, key=pct.get, reverse=True)[:2]
    low = sorted(pct, key=pct.get)[:2]
    drivers = ", ".join(f"{LABEL[k]} ({bd[k]:.0f}/{MAX[k]})" for k in top)
    drags   = ", ".join(f"{LABEL[k]} ({bd[k]:.0f}/{MAX[k]})" for k in low)
    return (f"Score {r['score']}/100 driven by {drivers}; held back by {drags}. "
            f"Coverage: {len(r.get('coverage', []))} venues offer it.")


def _bull_bear(r):
    bull, bear = [], []
    mom = r.get("mom20") or 0
    atr = r.get("atr_pct") or 0
    bd = r["breakdown"]
    if r.get("above_ma50") and r.get("ma_stack_up"):
        bull.append("Trend up — price over rising 20/50-day averages.")
    if mom >= 3:  bull.append(f"Momentum behind it ({mom:+.1f}% in 20 days).")
    if bd["supply"] >= MAX["supply"] * 0.6:
        bull.append("Supply/demand tight — structural backing: " + (r.get("note") or ""))
    if bd["catalyst"] >= MAX["catalyst"] * 0.6:
        bull.append("Near-term catalyst in play.")
    if bd["position"] >= MAX["position"] * 0.6:
        bull.append("Positioning/sentiment leaning the trade's way.")

    if not (r.get("above_ma50") and r.get("ma_stack_up")):
        bear.append("Trend not confirmed up — chasing risks a fakeout.")
    if mom <= -3: bear.append(f"Negative momentum ({mom:+.1f}%) — knife still falling.")
    if mom >= 20: bear.append("Move is extended — pullback risk after a vertical run.")
    if atr > 5:   bear.append(f"High volatility (ATR {atr:.1f}%) — wide stops, prop-DD risk.")
    if bd["catalyst"] < MAX["catalyst"] * 0.4:
        bear.append("No strong near-term catalyst — may drift.")
    tilt = r.get("news_tilt", "")
    if tilt == "bullish news flow": bull.append("Live headlines lean bullish.")
    if tilt == "bearish news flow": bear.append("Live headlines lean bearish — news contradicts the chart.")
    if not bear: bear.append("Main risk: a broad risk-off / USD spike hits the whole complex.")
    return bull, bear


def analyze(r):
    verdict = _verdict(r)
    bull, bear = _bull_bear(r)
    side = "long" if verdict.startswith("BUY") else "short" if verdict == "SELL" else "neutral"
    summary = (f"{verdict} — conviction {_conviction(r['score'])}. "
               + (f"The data leans {side}: " if side != "neutral"
                  else "No clean edge yet: ")
               + (bull[0] if side == "long" and bull else
                  bear[0] if side == "short" and bear else
                  "trend unconfirmed, wait for structure."))
    return {
        "verdict": verdict,
        "conviction": _conviction(r["score"]),
        "summary": summary,
        "price_reasoning": _price_reasoning(r),
        "score_reasoning": _score_reasoning(r),
        "bull": bull,
        "bear": bear,
    }
