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
import re
import time

from guardian import propfirms

DIR = os.path.join("data", "guardian_live")
STALE = 120          # seconds without a snapshot = the EA (or the PC) is off
MAX_SYMS = 80
MAX_POS = 200


def _f(x, d=0.0):
    try:
        v = float(x)
        return v if v == v and abs(v) != float("inf") else d
    except (TypeError, ValueError):
        return d


def _path(key, d=DIR):
    # the same key typed in MT5 and in the app must land on the same file,
    # whatever the case or stray spaces
    key = str(key or "").strip().upper()
    return os.path.join(d, hashlib.sha256(key.encode()).hexdigest()[:32] + ".json")


_BAD_NUM = re.compile(r'(?<=[:\[,])\s*-?(?:nan|inf)[a-z()]*\s*(?=[,}\]])', re.I)


def parse(raw):
    """The EA's JSON. MT5 writes an unusable number as 'nan', 'inf' or
    '-nan(ind)', which is not JSON; those become null instead of losing the
    whole snapshot."""
    try:
        return json.loads(raw)
    except ValueError:
        return json.loads(_BAD_NUM.sub("null", raw))


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
        if isinstance(s, dict) and s.get("s") and 0 < _f(s.get("v")) < 1e12:
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
        "day_start_bal": _f(body.get("day_start_bal")) or _f(body.get("day_start")) or _f(body.get("balance")),
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
    cfg = _cfg_read(key, d)
    if cfg.get("preset"):                         # trailing limits follow the account's highs
        pe = max(_f(cfg.get("peak_eq")), snap["equity"])
        pb = max(_f(cfg.get("peak_day_bal")), snap["day_start_bal"])
        if pe != cfg.get("peak_eq") or pb != cfg.get("peak_day_bal"):
            cfg.update(peak_eq=pe, peak_day_bal=pb)
            _cfg_write(key, cfg, d)
    return snap


# ---- the trader's challenge (firm preset + size), chosen in the app ----------
def _cfg_path(key, d=DIR):
    return _path(key, d)[:-5] + ".cfg.json"


def _cfg_read(key, d=DIR):
    try:
        with open(_cfg_path(key, d)) as f:
            c = json.load(f)
        return c if isinstance(c, dict) else {}
    except (OSError, ValueError):
        return {}


def _cfg_write(key, cfg, d=DIR):
    os.makedirs(d, exist_ok=True)
    p = _cfg_path(key, d)
    with open(p + ".tmp", "w") as f:
        json.dump(cfg, f, separators=(",", ":"))
    os.replace(p + ".tmp", p)


def preset_of(cfg):
    """The preset dict a saved setting points at (a firm's, or the trader's own)."""
    pid = cfg.get("preset")
    if pid == "custom":
        mx = _f(cfg.get("max_pct"))
        if mx <= 0:
            return None
        return {"id": "custom", "firm": "Custom", "program": "My own limits", "daily_pct": _f(cfg.get("daily_pct")) or None,
                "daily_basis": "balance", "max_pct": mx, "max_type": "static", "targets": [], "sizes": [],
                "check": False, "source": ""}
    return propfirms.get(pid) if pid else None


def set_challenge(key, body, d=DIR, now=None):
    """Save the trader's choice from the app. The trailing highs start from
    today: Guardian can't see the account's past, so they begin at the start
    size or today's figures, whichever is higher."""
    pid = str(body.get("preset") or "")
    size = _f(body.get("size"))
    cfg = {"preset": pid, "size": size, "risk_pct": _f(body.get("risk_pct")) or None, "set": int(now or time.time())}
    if pid == "custom":
        cfg.update(daily_pct=_f(body.get("daily_pct")), max_pct=_f(body.get("max_pct")))
    if pid and (size <= 0 or not preset_of(cfg)):
        raise ValueError("Pick a firm, a challenge and your account size.")
    snap = load(key, d, now) or {}
    cfg["peak_eq"] = max(size, _f(snap.get("equity")))
    cfg["peak_day_bal"] = max(size, _f(snap.get("day_start_bal")))
    if not pid:
        cfg = {"preset": "", "risk_pct": cfg["risk_pct"], "set": cfg["set"]}
    _cfg_write(key, cfg, d)
    return cfg


def rules_for(key, equity=None, snap=None, d=DIR, now=None):
    """What the chosen challenge means right now: (challenge dict for
    rules.check, the trader's risk %, a description for the app). (None,
    risk, None) when no firm is chosen."""
    cfg = _cfg_read(key, d)
    risk = _f(cfg.get("risk_pct")) or None
    p = preset_of(cfg)
    if not p or _f(cfg.get("size")) <= 0:
        return None, risk, None
    size = _f(cfg["size"])
    snap = snap if snap is not None else (load(key, d, now) or {})
    eq = _f(equity) if equity is not None else _f(snap.get("equity"), size)
    st = {"day_bal": snap.get("day_start_bal") or size, "day_eq": snap.get("day_start") or size,
          "peak_eq": max(_f(cfg.get("peak_eq")), eq), "peak_day_bal": cfg.get("peak_day_bal")}
    daily, mx = propfirms.floors(p, size, st)
    ch = {"on": True, "start": size, "daily_floor": daily, "max_floor": mx}
    info = {"id": p["id"], "firm": p["firm"], "program": p["program"], "size": size,
            "summary": propfirms.summary(p, size), "check": p["check"], "source": p["source"],
            "daily_floor": None if daily is None else round(daily, 2), "max_floor": round(mx, 2),
            "daily_left": None if daily is None else round(eq - daily, 2), "max_left": round(eq - mx, 2)}
    if snap.get("balance") and p["targets"]:
        info["target"] = round(size * (1 + p["targets"][0] / 100), 2)
    return ch, risk, info


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
    snap.setdefault("day_start_bal", snap["day_start"])
    ch, risk, info = rules_for(key, snap=snap, d=d, now=now)
    if risk:
        snap["risk_pct"] = risk
    if ch:                                        # the firm chosen in the app wins over the EA's inputs
        snap["challenge"], snap["firm"] = ch, info
    return snap


def account(snap):
    """rules.check() account dict from a snapshot."""
    acc = {"equity": snap["equity"], "risk_pct": snap["risk_pct"], "open_trades": len(snap["positions"]),
           "open_risk": snap["open_risk"], "open_no_stop": snap["open_no_stop"]}
    ch = snap.get("challenge") or {}
    if ch.get("on"):
        acc["challenge"] = dict(ch, today_pl=snap["today_pl"])
    return acc


# ---- one MT5 account per key (stops a key being shared) ----------------------
SWITCH_WAIT = 86400          # the linked account can be changed once a day


def claim_account(key, login, d=DIR, now=None):
    """True when this MT5 login may use the key: the first account to connect
    claims it, and only that account works until the owner switches it from
    the app (which only runs on the owner's own phone). A request without a
    login (EA before 1.14) is let through."""
    login = str(login or "").strip()
    if not login:
        return True
    cfg = _cfg_read(key, d)
    if not cfg.get("mt5"):
        cfg.update(mt5=login, mt5_set=int(now or time.time()))
        _cfg_write(key, cfg, d)
        return True
    return cfg["mt5"] == login


def linked_account(key, d=DIR):
    return _cfg_read(key, d).get("mt5") or ""


def release_account(key, d=DIR, now=None):
    """Free the key for another MT5 account. Returns an error string or None."""
    now = int(now or time.time())
    cfg = _cfg_read(key, d)
    if not cfg.get("mt5"):
        return None
    if now - int(cfg.get("mt5_set") or 0) < SWITCH_WAIT:
        return "You can switch accounts once a day. Try again tomorrow."
    cfg.pop("mt5", None)
    cfg["mt5_set"] = now                       # the next account to connect starts a new day
    if cfg.get("size"):                        # trailing highs belong to the old account
        cfg["peak_eq"] = cfg["peak_day_bal"] = cfg["size"]
    _cfg_write(key, cfg, d)
    return None


def settings(key, d=DIR):
    """The saved choice, for the app's form."""
    cfg = _cfg_read(key, d)
    return {k: cfg.get(k) for k in ("preset", "size", "risk_pct", "daily_pct", "max_pct") if cfg.get(k) is not None}


def trade(snap, sym, lots, stop_price):
    """rules.check() trade dict for a symbol from the trader's own Market Watch.
    The stop is a price; the distance is measured from the live bid."""
    s = next((x for x in snap["symbols"] if x["s"] == sym), None)
    if not s:
        return None
    sp = _f(stop_price)
    dist = abs(s["bid"] - sp) if sp > 0 and s["bid"] > 0 else 0
    return {"sym": sym, "lots": _f(lots), "stop": dist, "per_lot": dist * s["v"] if dist else None}
