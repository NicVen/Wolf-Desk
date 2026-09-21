"""Daily trade plan for STAALWAG HQ — press-a-button, once a day.

Pulls the estate's own findings (data/opportunities_*.json) plus a live gold
quote, computes a structure-based gold setup, and asks Gemini (free tier) for a
short reasoning narrative. ONE AI call per run, and only on demand.

The money-making estate keeps zero AI dependency: this is the single place an
AI is touched, it is optional (falls back to the computed setup), and it costs
nothing on the Gemini free tier.
"""
import datetime
import json
import os
import urllib.request

import config as C  # root estate config (ASSET_CLASSES, DATA_DIR)

GOLD_TICKER = "GC=F"


def _num(x, d=0.0):
    try:
        return float(x)
    except Exception:
        return d


def _load_opps():
    """Every scored opportunity across asset classes, tagged with its class."""
    rows = []
    for clskey in C.ASSET_CLASSES:
        path = os.path.join(C.DATA_DIR, "opportunities_%s.json" % clskey)
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            continue
        for r in d.get("opportunities", []):
            r = dict(r)
            r["_class"] = clskey
            r["_generated"] = d.get("generated")
            rows.append(r)
    return rows


def _gold_setup(m, opp):
    """Structure-based entry / stop / targets from a live quote.

    Stop sits beyond the recent swing plus a 0.25*ATR buffer (falls back to a
    1.5*ATR stop), clamped to a 0.5-3.5*ATR band; targets are 1R and 2R.
    """
    opp = opp or {}
    last = _num(m.get("last")) or _num(opp.get("price"))
    atr = _num(m.get("atr_abs"))
    if not atr and last:
        atr = last * (_num(m.get("atr_pct")) or _num(opp.get("atr_pct"), 1.0)) / 100.0
    if not atr:
        atr = last * 0.01 if last else 1.0
    swing_lo, swing_hi = m.get("swing_lo"), m.get("swing_hi")
    mom = _num(opp.get("mom20"))
    if mom != 0:
        bias = "SHORT" if mom < 0 else "LONG"
    else:
        bias = "LONG" if opp.get("above_ma20") else "SHORT"
    buf = 0.25 * atr
    if bias == "SHORT":
        entry_lo, entry_hi = last, last + 0.3 * atr
        mid = (entry_lo + entry_hi) / 2.0
        raw = (_num(swing_hi) + buf) if swing_hi else last + 1.5 * atr
        risk = min(max(raw - mid, 0.5 * atr), 3.5 * atr)
        stop = mid + risk
        t1, t2 = mid - risk, mid - 2 * risk
    else:
        entry_hi, entry_lo = last, last - 0.3 * atr
        mid = (entry_lo + entry_hi) / 2.0
        raw = (_num(swing_lo) - buf) if swing_lo else last - 1.5 * atr
        risk = min(max(mid - raw, 0.5 * atr), 3.5 * atr)
        stop = mid - risk
        t1, t2 = mid + risk, mid + 2 * risk
    rr = round(abs(t1 - mid) / max(risk, 1e-9), 1)
    r = lambda v: round(v, 2)
    return {
        "bias": bias, "last": r(last), "atr": r(atr),
        "entry_low": r(entry_lo), "entry_high": r(entry_hi),
        "stop": r(stop), "t1": r(t1), "t2": r(t2), "rr": rr,
        "risk_pct": 1, "regime": m.get("regime") or "",
    }


def _gemini(prompt):
    """One free-tier Gemini call. Returns '' on any failure (caller falls back)."""
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        return ""
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           "%s:generateContent?key=%s" % (model, key))
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            d = json.load(resp)
        return d["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        return ""


def build_day_plan():
    """Assemble today's plan: live gold + top signals + one Gemini reasoning pass."""
    try:
        from scout.prices import price_metrics
        m = price_metrics(GOLD_TICKER) or {}
    except Exception:
        m = {}
    opps = _load_opps()
    gold = next((o for o in opps
                 if o.get("ticker") == GOLD_TICKER or o.get("name") == "Gold"), None)
    top = sorted([o for o in opps if o.get("score") is not None],
                 key=lambda o: o.get("score", 0), reverse=True)[:6]
    setup = _gold_setup(m, gold)
    top_out = [{"name": o.get("name"), "class": o.get("_class"),
                "score": o.get("score"), "trend": o.get("trend_desc"),
                "note": o.get("note"), "price": o.get("price")} for o in top]

    facts = ["Gold (XAUUSD / GC=F) live: price %s, ATR %s, regime %s -> computed bias %s."
             % (setup["last"], setup["atr"], setup["regime"], setup["bias"])]
    if gold:
        facts.append("Gold analysis: %s | %s | note: %s"
                     % (gold.get("trend_desc"), gold.get("volfit_desc"), gold.get("note")))
    facts.append("Computed setup: %s, entry %s-%s, stop %s, T1 %s, T2 %s, R:R 1:%s (risk 1%%)."
                 % (setup["bias"], setup["entry_low"], setup["entry_high"],
                    setup["stop"], setup["t1"], setup["t2"], setup["rr"]))
    if top_out:
        facts.append("Top estate signals: " + "; ".join(
            "%s (%s) score %s, %s" % (t["name"], t["class"], t["score"], t["trend"])
            for t in top_out))
    prompt = (
        "You are the head strategist of STAALWAG Trading Desk. Using ONLY the data "
        "below, write today's brief in markdown with exactly these sections:\n"
        "## Reasoning\n(3-4 sentences on the gold bias and why)\n"
        "## Key findings\n(3-5 bullets across gold and the top signals)\n"
        "## Risk note\n(one line)\n"
        "Be concrete and concise. Do NOT invent numbers that are not in the data.\n\n"
        "DATA:\n" + "\n".join(facts))
    reasoning = _gemini(prompt) or (
        "_AI reasoning is unavailable right now (free-tier limit or no key) — "
        "the computed setup below still stands._")

    return {
        "date": datetime.datetime.utcnow().strftime("%A %d %B %Y"),
        "generated_utc": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "setup": setup,
        "gold_note": (gold or {}).get("note"),
        "gold_score": (gold or {}).get("score"),
        "top_signals": top_out,
        "reasoning": reasoning,
        "data_asof": (gold or {}).get("_generated"),
    }
