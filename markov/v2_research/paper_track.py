"""Forward paper-track for the validated Signal Engine.

Backtest validation is necessary but not sufficient — the old bot's mistake was
trusting a backtest. This records every signal the engine emits GOING FORWARD
and scores it in R against real price, so the gold edge earns live proof one
trade at a time. Nothing here invents outcomes; a signal stays OPEN until real
price prints its SL or TP.

Run daily (cron or manual):  python paper_track.py
  * appends any new live engine signal to paper_log.json (dedup)
  * resolves open logged signals on fresh daily bars
  * reports FORWARD expectancy in R, per edge

This is the gate between "validated in backtest" and "allowed to feed a channel".
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

try:
    import truststore; truststore.inject_into_ssl()
except Exception:
    pass
import urllib.request
import urllib.parse

import signal_engine as ENG

HERE = Path(__file__).resolve().parent
LOG = HERE / "paper_log.json"
OUT = HERE / "paper_track.json"
# Mirror the engine's live state into HQ so the admin dashboard is always
# current after the daily run (no separate sync needed).
HQ = Path(r"C:\Users\nvent\OneDrive\Desktop\CLAUDE\Projects\STAALWAG-HQ")
HDR = {"User-Agent": "Mozilla/5.0"}


def fetch_daily_ts(ticker: str, rng: str = "6mo"):
    """Daily bars WITH timestamps: [(ts, o, h, l, c)]. The engine's own fetch
    drops timestamps; the tracker needs them to resolve only bars after emit."""
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/%s"
           "?range=%s&interval=1d" % (urllib.parse.quote(ticker), rng))
    try:
        req = urllib.request.Request(url, headers=HDR)
        j = json.loads(urllib.request.urlopen(req, timeout=25).read())
        res = j["chart"]["result"][0]
        ts = res["timestamp"]
        q = res["indicators"]["quote"][0]
        o, h, l, c = q["open"], q["high"], q["low"], q["close"]
        out = []
        for i in range(len(c)):
            if None in (o[i], h[i], l[i], c[i]):
                continue
            out.append((ts[i], o[i], h[i], l[i], c[i]))
        return out
    except Exception:
        return []


def _load():
    if LOG.exists():
        try:
            return json.loads(LOG.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def resolve(sig: dict):
    """Walk daily bars strictly AFTER the emit timestamp; first SL/TP wins."""
    bars = fetch_daily_ts(sig["ticker"])
    if not bars:
        return
    emit_ts = sig.get("emit_ts", 0)
    d = sig["direction"]
    sl, tp = sig["sl"], sig["tp"]
    for t, o, h, l, c in bars:
        if t <= emit_ts:
            continue
        if d == "BUY":
            if l <= sl:
                sig.update(result="LOSS", r=-1.0, closed=t); return
            if h >= tp:
                sig.update(result="WIN", r=sig["rr"], closed=t); return
        else:
            if h >= sl:
                sig.update(result="LOSS", r=-1.0, closed=t); return
            if l <= tp:
                sig.update(result="WIN", r=sig["rr"], closed=t); return
    sig["result"] = "OPEN"


def _stats(rows):
    closed = [s for s in rows if s.get("result") in ("WIN", "LOSS")]
    n = len(closed)
    wins = [s for s in closed if s["result"] == "WIN"]
    net = sum(s.get("r") or 0 for s in closed)
    return {"closed": n, "open": len([s for s in rows if s.get("result") == "OPEN"]),
            "wins": len(wins), "win_rate": round(100 * len(wins) / n, 1) if n else None,
            "net_r": round(net, 2), "expectancy_r": round(net / n, 3) if n else None}


def main():
    log = _load()
    have = {(s["edge_id"], s["entry"], s["emitted"][:10]) for s in log}

    # 1) capture any new live signal the engine is emitting today
    view = ENG.scan()
    added = 0
    for s in view["live_signals"]:
        # attach the emit timestamp so resolution can't peek at pre-emit bars
        ed = next((e for e in ENG.EDGES if e["id"] == s["edge_id"]), None)
        s = dict(s, ticker=ed["ticker"] if ed else None,
                 emit_ts=int(datetime.now(timezone.utc).timestamp()))
        key = (s["edge_id"], s["entry"], s["emitted"][:10])
        if key not in have and s["ticker"]:
            log.append(s); have.add(key); added += 1

    # 2) resolve everything still open
    for s in log:
        if s.get("result") not in ("WIN", "LOSS"):
            resolve(s)

    LOG.write_text(json.dumps(log, indent=2), encoding="utf-8")

    per_edge = {}
    for e in ENG.EDGES:
        per_edge[e["id"]] = _stats([s for s in log if s["edge_id"] == e["id"]])

    out = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "note": "FORWARD paper track — real signals, scored on real price. Not backtest.",
        "overall": _stats(log),
        "per_edge": per_edge,
        "signals_logged": len(log),
        "new_today": added,
    }
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    # mirror engine state + forward track into HQ for the dashboard
    try:
        (HQ / "engine_v2.json").write_text(json.dumps(view, indent=2), encoding="utf-8")
        (HQ / "engine_v2_track.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    except Exception:
        pass

    o = out["overall"]
    print("FORWARD PAPER TRACK —", out["generated"])
    print("  logged %d signals (%d new today) | %d closed · %s%% WR · expectancy %sR forward"
          % (len(log), added, o["closed"], o["win_rate"], o["expectancy_r"]))
    for eid, st in per_edge.items():
        print("    %-20s %d closed · %s%% · %sR · %d open"
              % (eid, st["closed"], st["win_rate"], st["expectancy_r"], st["open"]))
    if o["closed"] == 0:
        print("  no closed forward trades yet — proof accrues as breakouts fire. "
              "This is how it EARNS live, honestly.")


if __name__ == "__main__":
    main()
