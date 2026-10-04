"""Trade simulator: one position at a time, no look-ahead, costs included.

A strategy looks at bars[0..i] and may return an order. The trade opens at the
NEXT bar's open. Each later bar checks stop first, then target (the
conservative order when one bar touches both), then the time-stop at close.
Results are in R (multiples of the risk taken), after costs.
"""
from dataclasses import dataclass


@dataclass
class Order:
    direction: int        # +1 long, -1 short
    stop_dist: float      # price distance from entry to stop
    target_r: float       # target in R (0 = no target)
    max_bars: int         # time-stop
    runner: bool = False  # VELDRIN-style: bank 50% at 1R + stop to entry,
                          # stop to 1R at 2R, rest out at 3R


def run(bars, strategy, cost: float) -> list[dict]:
    trades, i, n = [], 0, len(bars)
    while i < n - 1:
        o = strategy(bars, i)
        if o is None or o.stop_dist <= 0:
            i += 1
            continue
        e = bars[i + 1]["o"]
        d = o.direction
        stop = e - d * o.stop_dist
        tgt = e + d * o.target_r * o.stop_dist if o.target_r else None
        exit_px, j, why = None, i + 1, "time"
        banked, part = 0.0, 1.0           # runner: R already banked, share still open
        if o.runner:
            tgt = e + d * 3 * o.stop_dist
        while j < n:
            b = bars[j]
            if o.runner:                  # move the stop on the levels reached so far
                best = b["h"] if d > 0 else b["l"]
                reached = d * (best - e) / o.stop_dist
                if reached >= 1 and part == 1.0:
                    banked, part, stop = 0.5, 0.5, e
                    if (d > 0 and b["l"] <= stop) or (d < 0 and b["h"] >= stop):
                        exit_px, why = stop, "stop"   # same bar came back: conservative
                        break
                if reached >= 2 and d * (stop - e) < o.stop_dist:
                    stop = e + d * o.stop_dist      # same-bar dip below it counts (conservative)
            if (d > 0 and b["l"] <= stop) or (d < 0 and b["h"] >= stop):
                exit_px, why = stop, "stop"
                break
            if tgt is not None and ((d > 0 and b["h"] >= tgt) or (d < 0 and b["l"] <= tgt)):
                exit_px, why = tgt, "target"
                break
            if j - i >= o.max_bars:
                exit_px = b["c"]
                break
            j += 1
        if exit_px is None:
            break                       # still open at the end of the data
        r = (banked * o.stop_dist + part * d * (exit_px - e) - cost) / o.stop_dist
        trades.append({"t": bars[i + 1]["t"], "r": round(r, 3), "why": why, "dir": d})
        i = j                           # flat again: look for the next setup
    return trades


def stats(trades: list[dict], days: float) -> dict:
    if not trades:
        return {"n": 0, "per_month": 0, "win": 0, "pf": 0, "avg_r": 0, "total_r": 0, "max_dd_r": 0}
    rs = [t["r"] for t in trades]
    gain = sum(r for r in rs if r > 0)
    loss = -sum(r for r in rs if r < 0)
    eq = peak = dd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {"n": len(rs), "per_month": round(len(rs) / (days / 30.4), 1),
            "win": round(100 * sum(r > 0 for r in rs) / len(rs)),
            "pf": round(gain / loss, 2) if loss else 99.0,
            "avg_r": round(sum(rs) / len(rs), 3), "total_r": round(sum(rs), 1),
            "max_dd_r": round(dd, 1)}
