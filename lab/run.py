"""Test every candidate on one market and print a plain scorecard.

    python lab/run.py gold        (or: python lab/run.py GC=F 0.45)

Pass bar: profit factor >= 1.3 in BOTH halves of the history, after costs,
with enough trades to matter, AND better than the same rule manages on 20
shuffled copies of the market (luck). Parameters are never tuned on this data.
"""
import math
import random
import sys

import data
import engine
import strategies

MARKETS = {
    # name: (yahoo symbol, round-trip cost in price units: spread + slippage)
    "gold": ("GC=F", 0.45),
}


LUCK_RUNS = 20


def shuffled(bars, seed):
    """Same volatility and timestamps, but the bar-to-bar moves in random order:
    any real pattern is destroyed. What a rule earns here is pure luck."""
    rng = random.Random(seed)
    moves = [(math.log(b["c"] / a["c"]),                       # close-to-close move
              (b["h"] - max(b["o"], b["c"])) / b["c"],            # upper wick
              (min(b["o"], b["c"]) - b["l"]) / b["c"])            # lower wick
             for a, b in zip(bars, bars[1:])]
    rng.shuffle(moves)
    out, c = [dict(bars[0])], bars[0]["c"]
    for b, (lr, up, dn) in zip(bars[1:], moves):
        o, c = c, c * math.exp(lr)
        out.append({"t": b["t"], "o": o, "h": max(o, c) + c * up, "l": min(o, c) - c * dn, "c": c})
    return out


def luck_pf(bars, make, cost):
    """95th-percentile profit factor of the rule on shuffled markets."""
    pfs = sorted(engine.stats(engine.run(sh, make(sh), cost), 1)["pf"]
                 for sh in (shuffled(bars, k) for k in range(LUCK_RUNS)))
    return pfs[int(0.95 * (LUCK_RUNS - 1))]


def score(name, bars, make, cost):
    trades = engine.run(bars, make(bars), cost)
    days = (bars[-1]["t"] - bars[0]["t"]) / 86400
    mid_t = bars[len(bars) // 2]["t"]
    a = [t for t in trades if t["t"] < mid_t]
    b = [t for t in trades if t["t"] >= mid_t]
    last = [t for t in trades if t["t"] >= bars[-1]["t"] - 180 * 86400]
    s_all, s_a, s_b, s_l = (engine.stats(x, d) for x, d in
                            ((trades, days), (a, days / 2), (b, days / 2), (last, 180)))
    luck = luck_pf(bars, make, cost)
    ok = s_a["pf"] >= 1.3 and s_b["pf"] >= 1.3 and s_all["n"] >= 30 and s_all["pf"] > luck
    lg = engine.stats([t for t in trades if t["dir"] > 0], days)
    sh = engine.stats([t for t in trades if t["dir"] < 0], days)
    return (f"| {name} | {s_all['n']} | {s_all['per_month']} | {s_all['win']}% | "
            f"{s_all['pf']} | {s_a['pf']} | {s_b['pf']} | {s_l['pf']} ({s_l['n']}) | "
            f"{lg['pf']} ({lg['n']}) | {sh['pf']} ({sh['n']}) | "
            f"{s_all['total_r']:+} | {s_all['max_dd_r']} | {luck} | {'PASS' if ok else 'no'} |")


def main():
    key = sys.argv[1] if len(sys.argv) > 1 else "gold"
    sym, cost = MARKETS.get(key, (key, float(sys.argv[2]) if len(sys.argv) > 2 else 0))
    print(f"## {key} ({sym}), cost {cost} per trade\n")
    print("| rule | trades | per month | win | PF | PF 1st half | PF 2nd half | PF last 6m (n) | PF longs (n) | PF shorts (n) | total R | worst drawdown R | luck PF (95%) | verdict |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    h = data.bars(sym, "60m", "730d")
    d = data.bars(sym, "1d", "20y")
    trend = strategies.daily_trend(d)
    for name, make in strategies.HOURLY.items():
        print(score(name, h, make, cost))
        if name != "current (live rule)":
            print(score(name + " + daily trend", h, strategies.with_daily_trend(make, trend), cost))
    for name, make in strategies.DAILY.items():
        print(score(name, d, make, cost))
    print(f"\n1h bars: {len(h)}, daily bars: {len(d)}. "
          f"Market move over the 1h window: {100 * (h[-1]['c'] / h[0]['c'] - 1):+.0f}% "
          f"(a rising market flatters longs, so check the shorts column too).")


if __name__ == "__main__":
    main()
