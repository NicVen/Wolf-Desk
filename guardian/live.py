"""Guardian live link: the EA's account snapshot, shown in the phone app.

Every few seconds the Guardian EA posts what MT5 sees: balance, equity, the
open trades with their stops, today's starting equity, the trader's settings
and, for each Market Watch symbol, the bid and the $ value of a 1.0 price
move on 1.00 lot. The app shows it live and "Ask Guardian" sizes from it, so
the phone uses the broker's own numbers and nothing is typed in by hand.

Snapshots are kept per key in data/guardian_live/ (the key is hashed for the
file name), latest wins.
"""
import hashlib
import json
import os
import time

DIR = os.path.join("data", "guardian_live")
STALE = 120          # seconds without a snapshot = the EA (or the PC) is off
MAX_SYMS = 80
MAX_POS = 200


def _f(x, d=0.0):
    try:
        v = float(x)
        return v if v == v else d
    except (TypeError, ValueError):
        return d


def _path(key, d=DIR):
    return os.path.join(d, hashlib.sha256(key.encode()).hexdigest()[:32] + ".json")


def clean(body, now=None):
    """Keep only the fields the app uses, with sane types and sizes."""
    pos = []
    for p in (body.get("positions") or [])[:MAX_POS]:
        if not isinstance(p, dict):
            continue
        risk = p.get("risk")
        pos.append({"sym": str(p.get("sym") or "")[:32], "side": str(p.get("side") or "")[:12],
                    "lots": _f(p.get("lots")), "open": _f(p.get("open")), "sl": _f(p.get("sl")),
                    "profit": _f(p.get("profit")), "risk": None if risk is None else _f(risk)})
    syms = []
    for s in (body.get("symbols") or [])[:MAX_SYMS]:
        if isinstance(s, dict) and s.get("s") and _f(s.get("v")) > 0:
            syms.append({"s": str(s["s"])[:32], "bid": _f(s.get("bid")), "v": _f(s.get("v")),
                         "digits": int(_f(s.get("digits"), 2))})
    ch = body.get("challenge") if isinstance(body.get("challenge"), dict) else {}
    return {
        "login": str(body.get("login") or "")[:20],
        "server": str(body.get("server") or "")[:64],
        "currency": str(body.get("currency") or "USD")[:8],
        "balance": _f(body.get("balance")),
        "equity": _f(body.get("equity")),
        "day_start": _f(body.get("day_start")) or _f(body.get("equity")),
        "risk_pct": _f(body.get("risk_pct"), 1.0) or 1.0,
        "challenge": {"on": bool(ch.get("on")), "start": _f(ch.get("start")),
                      "daily_pct": _f(ch.get("daily_pct")), "max_pct": _f(ch.get("max_pct"))},
        "orders": int(_f(body.get("orders"))),
        "positions": pos,
        "symbols": syms,
        "ts": int(now or time.time()),
    }


def save(key, body, d=DIR, now=None):
    snap = clean(body, now)
    os.makedirs(d, exist_ok=True)
    p = _path(key, d)
    with open(p + ".tmp", "w") as f:
        json.dump(snap, f, separators=(",", ":"))
    os.replace(p + ".tmp", p)
    return snap


def load(key, d=DIR, now=None):
    """The latest snapshot with its age, or None if the EA never linked."""
    try:
        with open(_path(key, d)) as f:
            snap = json.load(f)
    except (OSError, ValueError):
        return None
    age = int((now or time.time()) - snap.get("ts", 0))
    snap["age"] = age
    snap["live"] = age <= STALE
    risks = [p["risk"] for p in snap["positions"] if p.get("risk") is not None]
    snap["open_risk"] = round(sum(risks), 2)
    snap["open_no_stop"] = sum(1 for p in snap["positions"] if p.get("risk") is None)
    snap["today_pl"] = round(snap["equity"] - snap["day_start"], 2)
    return snap


def account(snap):
    """rules.check() account dict from a snapshot."""
    acc = {"equity": snap["equity"], "risk_pct": snap["risk_pct"], "open_trades": len(snap["positions"]),
           "open_risk": snap["open_risk"], "open_no_stop": snap["open_no_stop"]}
    ch = snap.get("challenge") or {}
    if ch.get("on"):
        acc["challenge"] = dict(ch, today_pl=snap["today_pl"])
    return acc


def trade(snap, sym, lots, stop_price):
    """rules.check() trade dict for a symbol from the trader's own Market Watch.
    The stop is a price; the distance is measured from the live bid."""
    s = next((x for x in snap["symbols"] if x["s"] == sym), None)
    if not s:
        return None
    sp = _f(stop_price)
    dist = abs(s["bid"] - sp) if sp > 0 and s["bid"] > 0 else 0
    return {"sym": sym, "lots": _f(lots), "stop": dist, "per_lot": dist * s["v"] if dist else None}
