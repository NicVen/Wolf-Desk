"""Signal-bot and paper-trading scoreboard for the HQ "Bots" tab.

Reads the public records the bots already publish (no new storage, no AI):
  * Markov bot   -> /markov/signals.json   (each call closes itself with an R result)
  * STAALWAG Gold -> /desks/gold/track_record.json (live outcomes + paper/swing tests)
  * VELDRIN FX    -> /desks/fx/track_record.json

Every number is computed from those files on request, so HQ always shows the
current record. A bot that cannot be reached, or that logs no results, is shown
as broken instead of being hidden.
"""
from __future__ import annotations

import datetime
import json
import os
import urllib.request

MIN_SAMPLE = 30  # closed trades before a verdict is more than noise

SOURCES = {
    "markov": os.environ.get("HQ_MARKOV_SIGNALS_URL", "https://staalwag.com/markov/signals.json"),
    "gold": os.environ.get("HQ_GOLD_RECORD_URL", "https://staalwag.com/desks/gold/track_record.json"),
    "fx": os.environ.get("HQ_FX_RECORD_URL", "https://staalwag.com/desks/fx/track_record.json"),
}


def _fetch(url: str, timeout: float = 8.0):
    req = urllib.request.Request(url, headers={"User-Agent": "staalwag-hq"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _parse_ts(ts):
    """ISO string or unix seconds -> aware UTC datetime (None if unknown)."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
    try:
        d = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return d.astimezone(datetime.timezone.utc)


def _iso(ts):
    d = _parse_ts(ts)
    return d.isoformat() if d else None


def r_stats(rs):
    """Win/loss/net/PF over a list of R results. Zero-R trades count as flat."""
    rs = [r for r in rs if r is not None]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    gross_loss = -sum(losses)
    return {
        "closed": len(rs),
        "wins": len(wins),
        "losses": len(losses),
        "flat": len(rs) - len(wins) - len(losses),
        "win_rate": round(100.0 * len(wins) / len(rs), 1) if rs else None,
        "net_r": round(sum(rs), 2),
        "avg_r": round(sum(rs) / len(rs), 3) if rs else None,
        "pf": round(sum(wins) / gross_loss, 2) if gross_loss > 0 else None,
    }


def verdict(stats, unit="R"):
    n = stats.get("closed") or 0
    if n == 0:
        return {"level": "broken", "text": "No closed results recorded"}
    net = stats.get("net_r") if unit == "R" else stats.get("net")
    if n < MIN_SAMPLE:
        return {"level": "early", "text": "Too few trades to judge (%d of %d)" % (n, MIN_SAMPLE)}
    if net is not None and net > 0:
        return {"level": "good", "text": "Making money on paper"}
    return {"level": "bad", "text": "Losing on paper"}


def markov_card(data, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    rows = data.get("signals", []) if isinstance(data, dict) else (data or [])
    closed = [s for s in rows if str(s.get("status", "")).upper() == "CLOSED"]
    opened = [s for s in rows if str(s.get("status", "")).upper() == "OPEN"]
    stats = r_stats([_num(s.get("r")) for s in closed])
    cutoff = now - datetime.timedelta(days=30)
    recent = [s for s in closed if (_parse_ts(s.get("closed") or s.get("time")) or now) >= cutoff]
    by_pair = {}
    for s in closed:
        by_pair.setdefault(s.get("pair") or "?", []).append(_num(s.get("r")))
    pairs = sorted(({"pair": p, **r_stats(v)} for p, v in by_pair.items()),
                   key=lambda x: x["net_r"], reverse=True)
    times = [t for t in (_parse_ts(s.get("time")) for s in rows) if t]
    return {
        "name": "Markov bot",
        "what": "Telegram signals, 16 markets, paper test (bot closes each call itself)",
        "stats": stats,
        "last_30d": r_stats([_num(s.get("r")) for s in recent]),
        "verdict": verdict(stats),
        "first": min(times).isoformat() if times else None,
        "last_signal": max(times).isoformat() if times else None,
        "open": [{"pair": s.get("pair"), "direction": s.get("direction"), "entry": s.get("entry"),
                  "sl": s.get("sl"), "tp": s.get("tp") or s.get("tp1"), "time": s.get("time")}
                 for s in opened],
        "best": pairs[:3],
        "worst": list(reversed(pairs[-3:])) if len(pairs) > 3 else [],
        "recent": [{"pair": s.get("pair"), "direction": s.get("direction"), "result": s.get("result"),
                    "r": _num(s.get("r")), "closed": s.get("closed")}
                   for s in sorted(closed, key=lambda s: str(s.get("closed") or ""), reverse=True)[:10]],
        "rules": data.get("rules") if isinstance(data, dict) else None,
    }


def _test_card(name, what, rows, time_key, close_key):
    closed = [t for t in rows if t.get("result")]
    opened = [t for t in rows if not t.get("result")]
    stats = r_stats([_num(t.get("r")) for t in closed])
    v = verdict(stats)
    if not closed and opened:
        v = {"level": "early", "text": "No closed trades yet (%d open)" % len(opened)}
    return {
        "name": name,
        "what": what,
        "stats": stats,
        "verdict": v,
        "open": [{"symbol": t.get("symbol") or t.get("rule"), "direction": t.get("direction"),
                  "entry": t.get("entry"), "sl": t.get("sl"), "tp": t.get("tp"),
                  "time": _iso(t.get(time_key))}
                 for t in opened],
        "recent": [{"symbol": t.get("symbol") or t.get("rule"), "direction": t.get("direction"),
                    "result": t.get("result"), "r": _num(t.get("r")),
                    "closed": _iso(t.get(close_key))}
                   for t in reversed(closed[-10:])],
    }


def desk_cards(name, data):
    """A desk record -> one live card, plus a card per paper/swing test it carries."""
    data = data if isinstance(data, dict) else {}
    outs = data.get("outcomes") or []
    pips = [_num(o.get("pips")) for o in outs]
    pips = [p for p in pips if p is not None]
    wins = [p for p in pips if p > 0]
    losses = [p for p in pips if p < 0]
    gross_loss = -sum(losses)
    live = {"closed": len(pips), "wins": len(wins), "losses": len(losses),
            "win_rate": round(100.0 * len(wins) / len(pips), 1) if pips else None,
            "net": round(sum(pips), 1), "unit": data.get("unit") or "pips",
            "pf": round(sum(wins) / gross_loss, 2) if gross_loss > 0 else None}
    v = verdict(live, unit="pips")
    if not pips and data.get("signals"):
        v = {"level": "broken",
             "text": "Scans run (%s) but no trade results are recorded" % data.get("signals")}
    last = [o.get("ts") for o in outs if o.get("ts")]
    cards = [{
        "name": name + " desk",
        "what": "Telegram desk signals (%s), results in %s" % (data.get("pair") or "?", live["unit"]),
        "stats": live,
        "verdict": v,
        "last_result": max(last) if last else None,
        "recent": [{"symbol": data.get("pair"), "result": o.get("result"), "pips": _num(o.get("pips")),
                    "closed": o.get("ts")}
                   for o in reversed(outs[-10:])],
    }]
    if data.get("paper_test"):
        rules = sorted({t.get("rule") for t in data["paper_test"] if t.get("rule")})
        cards.append(_test_card(name + " paper test", "Paper rule: " + (", ".join(rules) or "?"),
                                data["paper_test"], "ts", "closed_ts"))
    if data.get("swing_test"):
        cards.append(_test_card(name + " swing test", "Swing paper test (commodities/crypto)",
                                data["swing_test"], "signal_t", "exit_t"))
    return cards


def build(fetch=_fetch):
    cards, errors = [], []
    try:
        cards.append(markov_card(fetch(SOURCES["markov"])))
    except Exception as e:  # noqa: BLE001
        errors.append({"name": "Markov bot", "error": str(e)[:160]})
    for key, name in (("gold", "STAALWAG Gold"), ("fx", "VELDRIN FX")):
        try:
            cards.extend(desk_cards(name, fetch(SOURCES[key])))
        except Exception as e:  # noqa: BLE001
            errors.append({"name": name + " desk", "error": str(e)[:160]})
    for e in errors:
        cards.append({"name": e["name"], "what": "Could not load the record", "stats": {},
                      "verdict": {"level": "broken", "text": "Unreachable: " + e["error"]}})
    return {"generated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "min_sample": MIN_SAMPLE, "bots": cards}
