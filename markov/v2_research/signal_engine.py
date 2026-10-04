"""STAALWAG SIGNAL ENGINE v2 — the ground-up rebuild.

The old 18-pair bot sprayed unvalidated signals and lost (10% WR, -0.69R). This
one is the opposite by construction: it emits a signal ONLY for edges that have
already survived out-of-sample walk-forward + PSR/DSR validation in
`signal_research.py`. No edge enters the registry without passing that gate.
No "confidence" is invented; each signal carries its real validated track.

Validated 2026-08-17 on 5y daily bars (see signal_research.py):
  * XAUUSD Donchian-55 breakout  — PROVEN: +0.62R full, +0.27R out-of-sample,
    positive in all 5 of 5 years, PSR ~1.0, 189 trades. Full weight.
  * GBPJPY Bollinger-2.5 revert  — MARGINAL: +0.42R full, +0.15R OOS, positive
    in 3/5 years. Half weight, kept on probation.

Rejected (did NOT survive OOS): EURJPY rsi2 (2/5 yrs), GBPJPY rsi2 (0/5),
XAGUSD donchian (fails OOS), and every other combo in the 294-combo sweep.

Run:  python signal_engine.py            # print today's validated signals
      python signal_engine.py --json     # machine output for HQ / dispatch
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import signal_research as R  # reuse the vetted indicators, strategies, resolver

HERE = Path(__file__).resolve().parent
OUT = HERE / "engine_signals.json"

# ── the registry: ONLY validated edges, with their real proof + risk weight ──
EDGES = [
    {
        "id": "xauusd-donchian55",
        "instrument": "XAUUSD", "ticker": "GC=F",
        "strategy": "donchian55", "params": {"n": 55},
        "atr_mult": 3.0, "rr": 2.0,
        "weight": 1.0,
        "status": "PROVEN",
        "validation": {"full_exp_r": 0.62, "oos_exp_r": 0.27,
                       "years_positive": "5/5", "psr": 1.00, "trades": 189},
        "signal_fn": lambda bars: R.s_donchian(bars, 55),
    },
    {
        "id": "gbpjpy-boll2.5",
        "instrument": "GBPJPY", "ticker": "GBPJPY=X",
        "strategy": "boll2.5", "params": {"n": 20, "dev": 2.5},
        "atr_mult": 2.0, "rr": 2.0,
        "weight": 0.5,
        "status": "MARGINAL (probation)",
        "validation": {"full_exp_r": 0.42, "oos_exp_r": 0.15,
                       "years_positive": "3/5", "psr": 1.00, "trades": 89},
        "signal_fn": lambda bars: R.s_boll_revert(bars, 20, 2.5),
    },
]


def current_signal(edge: dict):
    """Is this edge firing on the most recently CLOSED daily bar? Returns a
    ready-to-trade signal dict with entry/SL/TP in price, and the R geometry."""
    bars = R.fetch_daily(edge["ticker"], "6mo")
    if len(bars) < 120:
        return None
    entries = edge["signal_fn"](bars)
    if not entries:
        return None
    last_i = len(bars) - 1                     # most recent CLOSED bar
    fire = [(i, d) for (i, d) in entries if i == last_i - 1 or i == last_i]
    if not fire:
        return None
    i, d = fire[-1]
    a = R.atr(bars, i)
    if not a or a <= 0:
        return None
    entry = bars[i][3]
    am, rr = edge["atr_mult"], edge["rr"]
    if d == "BUY":
        sl, tp = entry - am * a, entry + am * a * rr
    else:
        sl, tp = entry + am * a, entry - am * a * rr
    return {
        "edge_id": edge["id"], "instrument": edge["instrument"],
        "direction": d,
        "entry": round(entry, 5), "sl": round(sl, 5), "tp": round(tp, 5),
        "rr": rr, "risk_weight": edge["weight"],
        "status": edge["status"],
        "validated": edge["validation"],
        "emitted": datetime.now(timezone.utc).isoformat(timespec="minutes"),
    }


def scan():
    signals = []
    for e in EDGES:
        try:
            s = current_signal(e)
        except Exception:
            s = None
        if s:
            signals.append(s)
    return {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "engine": "STAALWAG Signal Engine v2",
        "principle": "emits only OOS-validated edges; no unproven signals, ever",
        "edges_registered": [{"id": e["id"], "status": e["status"],
                               "weight": e["weight"], "validation": e["validation"]}
                              for e in EDGES],
        "live_signals": signals,
    }


def main():
    view = scan()
    OUT.write_text(json.dumps(view, indent=2), encoding="utf-8")
    if "--json" in sys.argv:
        print(json.dumps(view, indent=2))
        return
    print("STAALWAG SIGNAL ENGINE v2 —", view["generated"])
    print("Registered edges (validated only):")
    for e in view["edges_registered"]:
        v = e["validation"]
        print("  %-20s %-20s w%.1f | full %+.2fR · OOS %+.2fR · yrs %s · PSR %.2f · %d tr"
              % (e["id"], e["status"], e["weight"], v["full_exp_r"], v["oos_exp_r"],
                 v["years_positive"], v["psr"], v["trades"]))
    print("Live signals today: %d" % len(view["live_signals"]))
    for s in view["live_signals"]:
        print("  %s %s @ %s  SL %s  TP %s  (%.0f:1)  weight %.1f  [%s]"
              % (s["instrument"], s["direction"], s["entry"], s["sl"], s["tp"],
                 s["rr"], s["risk_weight"], s["status"]))
    if not view["live_signals"]:
        print("  (no validated edge is firing right now — correct behaviour: "
              "silence beats a bad signal)")


if __name__ == "__main__":
    main()
