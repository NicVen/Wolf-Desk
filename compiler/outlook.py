"""Per-instrument daily outlook — a plain-language brief on what is driving each
market today and the potential outcomes.

Deterministic and built from the same data as the score/verdict: the mechanical
read (trend, momentum, volatility, Markov regime, edge validation) plus any
fundamental note carried in the manual signals file. It is NOT live news
headlines and NOT financial advice — it is the desk's structured read of the
tape, so a client can see at a glance what influences a pair for the day.
"""
import datetime


def _drivers(r):
    mom = r.get("mom20") or 0
    atr = r.get("atr_pct") or 0
    out = []

    # trend structure
    if r.get("above_ma50") and r.get("ma_stack_up"):
        out.append("Trend: up — price is above its rising 20- and 50-period "
                   "averages, so buyers have control.")
    elif not r.get("above_ma20") and not r.get("ma_stack_up"):
        out.append("Trend: down — price is under both its averages, so sellers "
                   "have control.")
    else:
        out.append("Trend: mixed — price is tangled in its averages, no clean "
                   "direction yet.")

    # momentum
    if abs(mom) >= 8:
        out.append("Momentum: strong (%+.1f%% over 20 bars) — the current move "
                   "has real force behind it." % mom)
    elif abs(mom) >= 3:
        out.append("Momentum: moderate (%+.1f%%) — a steady drift, not a "
                   "stampede." % mom)
    else:
        out.append("Momentum: flat (%+.1f%%) — coiling, waiting for a trigger." % mom)

    # volatility
    if atr > 5:
        out.append("Volatility: high (ATR %.1f%% of price) — expect big swings; "
                   "size down and widen stops." % atr)
    elif atr >= 1:
        out.append("Volatility: healthy (ATR %.1f%%) — moving enough to trade "
                   "cleanly." % atr)
    else:
        out.append("Volatility: low (ATR %.1f%%) — a quiet tape; breakouts may "
                   "lack follow-through." % atr)

    # Markov regime
    reg = r.get("regime") or {}
    st = (reg.get("state") or "").upper()
    if st:
        conf = reg.get("confidence") or "low"
        persist = reg.get("persist")
        pstr = (" and has held ~%d%% of the time" % round(persist * 100)) if persist is not None else ""
        out.append("Regime: %s (%s confidence)%s — the statistical state of the "
                   "tape." % (st, conf, pstr))

    # fundamental backdrop (the real 'influence' when we have one)
    note = (r.get("note") or "").strip()
    if note:
        out.append("Backdrop: " + note)

    # edge validation
    val = r.get("validation") or {}
    lab = val.get("label")
    if lab and lab not in ("n/a", "too little data", "no directional edge"):
        out.append("Edge quality: recent edge reads as “%s” on a "
                   "deflated-Sharpe test." % lab)

    # live news tilt
    tilt = (r.get("news_tilt") or "").strip()
    if tilt and tilt not in ("no news", "no recent news"):
        out.append("Headlines: %s (see the news list below)." % tilt)

    return out


def outlook(r):
    a = r.get("analysis") or {}
    verdict = a.get("verdict", "WATCH")
    bull = a.get("bull") or []
    bear = a.get("bear") or []
    name = r.get("name", "This market")

    lead = {"BUY": "buyers in control", "BUY (weak)": "a tentative bid",
            "SELL": "sellers in control", "WATCH": "no clean edge yet"}.get(verdict, "mixed")
    headline = "%s: %s." % (name, lead)

    bull_case = ("If direction holds: " + bull[0]) if bull else \
                "Upside case: reclaiming the averages would put buyers back in control."
    bear_case = ("Main risk: " + bear[0]) if bear else \
                "Downside case: losing the averages opens the door to sellers."

    return {
        "as_of": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "headline": headline,
        "verdict": verdict,
        "influences": _drivers(r),
        "bull_case": bull_case,
        "bear_case": bear_case,
        "bottom_line": a.get("summary", ""),
        "news_tilt": r.get("news_tilt", ""),
        "headlines": r.get("headlines", []),
    }
