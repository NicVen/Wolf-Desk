"""Scoring engine — combines auto price metrics + manual scout signals into a
0-100 opportunity score per commodity, then ranks them.
"""
import config as C


def trend_points(pm):
    """0-25 from price structure + momentum."""
    if not pm:
        return 0.0, "no data"
    p = 0.0
    if pm["above_ma20"]: p += 6
    if pm["above_ma50"]: p += 6
    if pm["ma_stack_up"]: p += 5
    # momentum: scale +/-8% 20d move into 0-8
    m = max(-8.0, min(8.0, pm["mom20"]))
    p += (m / 8.0) * 8.0
    p = max(0.0, min(C.W_TREND, p))
    dirn = "up" if pm["above_ma50"] and pm["ma_stack_up"] else ("down" if not pm["above_ma20"] else "mixed")
    return round(p, 1), f"{dirn}, mom {pm['mom20']:+.1f}%"


def volfit_points(pm):
    """0-10. Sweet spot ~1-3% ATR; too quiet or too wild scores low."""
    if not pm:
        return 0.0, "no data"
    a = pm["atr_pct"]
    if a <= 0:           p = 0
    elif a < 0.5:        p = 3      # too quiet
    elif a <= 3.0:       p = 10     # tradeable
    elif a <= 5.0:       p = 6      # lively
    else:                p = 2      # chaos
    return float(p), f"ATR {a:.1f}%"


def score_one(name, pm, sig):
    """sig = manual signal dict {catalyst, position, supply, note}. Each capped to its weight."""
    cat = min(C.W_CATALYST, float(sig.get("catalyst", 0)))
    pos = min(C.W_POSITION, float(sig.get("position", 0)))
    sup = min(C.W_SUPPLY,   float(sig.get("supply", 0)))
    tr, tr_d = trend_points(pm)
    vf, vf_d = volfit_points(pm)
    total = round(cat + tr + pos + sup + vf, 1)
    return {
        "name": name,
        "score": total,
        "breakdown": {"catalyst": cat, "trend": tr, "position": pos,
                      "supply": sup, "volfit": vf},
        "trend_desc": tr_d,
        "volfit_desc": vf_d,
        "note": sig.get("note", ""),
        "price": (pm or {}).get("last"),
        "mom20": (pm or {}).get("mom20"),
        "atr_pct": (pm or {}).get("atr_pct"),
        "ma20": (pm or {}).get("ma20"),
        "ma50": (pm or {}).get("ma50"),
        "above_ma20": (pm or {}).get("above_ma20"),
        "above_ma50": (pm or {}).get("above_ma50"),
        "ma_stack_up": (pm or {}).get("ma_stack_up"),
    }


def rank(rows):
    return sorted(rows, key=lambda r: r["score"], reverse=True)
