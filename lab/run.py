"""Test every candidate on one market and print a plain scorecard.

    python lab/run.py gold        (or: python lab/run.py GC=F 0.45)

Pass bar: profit factor >= 1.3 in BOTH halves of the history, after costs,
with enough trades to matter. Parameters are never tuned on this data.
"""
import sys

import data
import engine
import strategies

MARKETS = {
    # name: (yahoo symbol, round-trip cost in price units: spread + slippage)
    "gold": ("GC=F", 0.45),
}


def score(name, bars, make, cost):
    trades = engine.run(bars, make(bars), cost)
    days = (bars[-1]["t"] - bars[0]["t"]) / 86400
    mid_t = bars[len(bars) // 2]["t"]
    a = [t for t in trades if t["t"] < mid_t]
    b = [t for t in trades if t["t"] >= mid_t]
    last = [t for t in trades if t["t"] >= bars[-1]["t"] - 180 * 86400]
    s_all, s_a, s_b, s_l = (engine.stats(x, d) for x, d in
                            ((trades, days), (a, days / 2), (b, days / 2), (last, 180)))
    ok = s_a["pf"] >= 1.3 and s_b["pf"] >= 1.3 and s_all["n"] >= 30
    return (f"| {name} | {s_all['n']} | {s_all['per_month']} | {s_all['win']}% | "
            f"{s_all['pf']} | {s_a['pf']} | {s_b['pf']} | {s_l['pf']} | "
            f"{s_all['total_r']:+} | {s_all['max_dd_r']} | {'PASS' if ok else 'no'} |")


def main():
    key = sys.argv[1] if len(sys.argv) > 1 else "gold"
    sym, cost = MARKETS.get(key, (key, float(sys.argv[2]) if len(sys.argv) > 2 else 0))
    print(f"## {key} ({sym}), cost {cost} per trade\n")
    print("| rule | trades | per month | win | PF | PF 1st half | PF 2nd half | PF last 6m | total R | worst drawdown R | verdict |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    h = data.bars(sym, "60m", "730d")
    for name, make in strategies.HOURLY.items():
        print(score(name, h, make, cost))
    d = data.bars(sym, "1d", "20y")
    for name, make in strategies.DAILY.items():
        print(score(name, d, make, cost))
    print(f"\n1h bars: {len(h)}, daily bars: {len(d)}")


if __name__ == "__main__":
    main()
