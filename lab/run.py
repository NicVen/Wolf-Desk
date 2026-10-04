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


FX = {   # yahoo symbol: round-trip cost (about 1.2 pips majors, 1.8 commodity pairs)
    "EURUSD=X": 0.00012, "GBPUSD=X": 0.00015, "USDJPY=X": 0.012,
    "AUDUSD=X": 0.00015, "USDCAD=X": 0.00018, "USDCHF=X": 0.00018,
}
FX_RULES = {
    "current VELDRIN (live rule)": strategies.make_veldrin,
    "breakout + trend": strategies.make_donchian,
    "trend pullback": strategies.make_pullback,
    "London breakout": strategies.make_session_break,
    "time-of-day (walk-forward)": strategies.make_hour_of_day,
    "fade extremes": strategies.make_fade,
    "fade extremes, Asia hours": strategies.make_fade_asia,
    "London 4pm fix reversal": strategies.make_fix_reversal,
    "Sunday gap fill": strategies.make_weekend_gap,
}


def fx():
    """All six VELDRIN pairs pooled: one scorecard per rule, R summed across pairs."""
    data_ = {}
    for sym in FX:
        try:
            data_[sym] = (data.bars(sym, "60m", "730d"), data.bars(sym, "1d", "20y"))
        except Exception as e:
            print(f"(skipped {sym}: {e})")
    print("## VELDRIN pairs pooled: " + ", ".join(data_) + "\n")
    print("| rule | trades | per month | win | PF | PF 1st half | PF 2nd half | PF last 6m (n) | PF longs (n) | PF shorts (n) | total R | worst drawdown R | luck PF (95%) | verdict | PF per pair |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    rules = dict(FX_RULES)
    for name, make in FX_RULES.items():
        if "live" not in name:
            rules[name + " + daily trend"] = ("trend", make)
    rules["daily trend (20y daily bars)"] = ("daily", strategies.make_trend_daily)
    rules["month-end flows (20y daily, walk-forward)"] = ("daily", strategies.make_month_end)
    for name, make in rules.items():
        allt, luck, per, days, mids, ends = [], [], [], 0, {}, []
        for sym, (h, d) in data_.items():
            mk = make
            if isinstance(make, tuple) and make[0] == "daily":
                h, mk = d, make[1]
            elif isinstance(make, tuple):
                mk = strategies.with_daily_trend(make[1], strategies.daily_trend(d))
            tr = engine.run(h, mk(h), FX[sym])
            mid_t = h[len(h) // 2]["t"]
            for t in tr:
                t["half"] = 0 if t["t"] < mid_t else 1
            allt += tr
            per.append(f"{sym[:6]} {engine.stats(tr, 1)['pf']}")
            days = max(days, (h[-1]["t"] - h[0]["t"]) / 86400)
            ends.append(h[-1]["t"])
            for k in range(LUCK_RUNS // 4):          # fewer shuffles per pair, pooled
                sh = shuffled(h, k)
                luck.append(engine.run(sh, mk(sh) if not isinstance(make, tuple) or make[0] == "daily" else
                                       strategies.with_daily_trend(make[1], strategies.daily_trend(d))(sh),
                                       FX[sym]))
        allt.sort(key=lambda t: t["t"])
        a = [t for t in allt if t["half"] == 0]
        b = [t for t in allt if t["half"] == 1]
        last = [t for t in allt if t["t"] >= max(ends) - 180 * 86400]
        st = engine.stats(allt, days)
        sa, sb, sl = engine.stats(a, days / 2), engine.stats(b, days / 2), engine.stats(last, 180)
        # luck: pool shuffle k across pairs
        n_pairs = len(data_)
        pools = [sum((luck[p * (LUCK_RUNS // 4) + k] for p in range(n_pairs)), [])
                 for k in range(LUCK_RUNS // 4)]
        lpf = sorted(engine.stats(x, 1)["pf"] for x in pools)[-1]
        ok = sa["pf"] >= 1.3 and sb["pf"] >= 1.3 and st["n"] >= 30 and st["pf"] > lpf
        lg = engine.stats([t for t in allt if t["dir"] > 0], days)
        shs = engine.stats([t for t in allt if t["dir"] < 0], days)
        print(f"| {name} | {st['n']} | {st['per_month']} | {st['win']}% | {st['pf']} | "
              f"{sa['pf']} | {sb['pf']} | {sl['pf']} ({sl['n']}) | {lg['pf']} ({lg['n']}) | "
              f"{shs['pf']} ({shs['n']}) | {st['total_r']:+} | {st['max_dd_r']} | {lpf} | "
              f"{'PASS' if ok else 'no'} | {'; '.join(per)} |")


FLOWS = {   # pair: (CFTC market name, +1/-1 vs the currency, CME future, cost as share of price)
    "EURUSD=X": ("EURO FX", 1, "6E=F"), "GBPUSD=X": ("BRITISH POUND", 1, "6B=F"),
    "USDJPY=X": ("JAPANESE YEN", -1, "6J=F"), "AUDUSD=X": ("AUSTRALIAN DOLLAR", 1, "6A=F"),
    "USDCAD=X": ("CANADIAN DOLLAR", -1, "6C=F"), "USDCHF=X": ("SWISS FRANC", -1, "6S=F"),
}


def pooled(name, items):
    """items: [(label, bars, make, cost)]. One pooled scorecard line."""
    allt, per, days, ends, lucks = [], [], 0, [], [[] for _ in range(LUCK_RUNS // 4)]
    for label, h, make, cost in items:
        if len(h) < 300:
            per.append(f"{label} n/a")
            continue
        tr = engine.run(h, make(h), cost)
        mid_t = h[len(h) // 2]["t"]
        for t in tr:
            t["half"] = 0 if t["t"] < mid_t else 1
        allt += tr
        per.append(f"{label} {engine.stats(tr, 1)['pf']} ({len(tr)})")
        days = max(days, (h[-1]["t"] - h[0]["t"]) / 86400)
        ends.append(h[-1]["t"])
        for k in range(len(lucks)):
            sh = shuffled(h, k)
            for b, o in zip(sh, h):
                b["v"] = o.get("v", 0)
            lucks[k] += engine.run(sh, make(sh), cost)
    if not allt:
        print(f"| {name} | 0 | | | | | | | | | | | | no data | {'; '.join(per)} |")
        return
    allt.sort(key=lambda t: t["t"])
    a = [t for t in allt if t["half"] == 0]
    b = [t for t in allt if t["half"] == 1]
    last = [t for t in allt if t["t"] >= max(ends) - 180 * 86400]
    st, sa, sb, sl = (engine.stats(allt, days), engine.stats(a, days / 2),
                      engine.stats(b, days / 2), engine.stats(last, 180))
    lpf = sorted(engine.stats(x, 1)["pf"] for x in lucks)[-1]
    ok = sa["pf"] >= 1.3 and sb["pf"] >= 1.3 and st["n"] >= 30 and st["pf"] > lpf
    lg = engine.stats([t for t in allt if t["dir"] > 0], days)
    shs = engine.stats([t for t in allt if t["dir"] < 0], days)
    print(f"| {name} | {st['n']} | {st['per_month']} | {st['win']}% | {st['pf']} | "
          f"{sa['pf']} | {sb['pf']} | {sl['pf']} ({sl['n']}) | {lg['pf']} ({lg['n']}) | "
          f"{shs['pf']} ({shs['n']}) | {st['total_r']:+} | {st['max_dd_r']} | {lpf} | "
          f"{'PASS' if ok else 'no'} | {'; '.join(per)} |")


def flows():
    """Where the big money is: CFTC positioning (weekly, since 2010, daily bars)
    and CME currency-futures volume surges (1h, 2 years)."""
    from datetime import datetime
    years = range(2010, datetime.utcnow().year + 1)
    daily, cots, fut = {}, {}, {}
    for sym, (mkt, sign, f) in FLOWS.items():
        try:
            daily[sym] = data.bars(sym, "1d", "20y")
            cots[sym] = data.cot(mkt, years)
            print(f"({sym}: {len(cots[sym])} weekly reports)")
        except Exception as e:
            print(f"(skipped {sym} COT: {e})")
        try:
            fut[sym] = data.bars(f, "60m", "730d")
        except Exception as e:
            print(f"(skipped {f}: {e})")
    print("\n## VELDRIN pairs: where the big money is\n")
    print("| rule | trades | per month | win | PF | PF 1st half | PF 2nd half | PF last 6m (n) | PF longs (n) | PF shorts (n) | total R | worst drawdown R | luck PF (95%) | verdict | PF per pair (n) |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for who, label in (("lev", "hedge funds"), ("am", "asset managers")):
        for fade in (True, False):
            name = f"positioning: {'fade' if fade else 'follow'} {label} at extremes"
            pooled(name, [(s[:6], daily[s], strategies.make_cot(cots[s], FLOWS[s][1], who, fade), FX[s])
                          for s in daily if cots.get(s)])
    for follow in (True, False):
        name = f"futures volume surge: {'follow' if follow else 'fade'}"
        pooled(name, [(FLOWS[s][2], h, (lambda fo: lambda b: strategies.make_volume_spike(b, follow=fo))(follow),
                       h[-1]["c"] * 0.00011) for s, h in fut.items() if h])


def gold_flows():
    """Gold: hedge-fund (managed money) and miner (producer/merchant) positions
    from the CFTC Disaggregated report since 2010, plus COMEX volume surges."""
    from datetime import datetime
    years = range(2010, datetime.utcnow().year + 1)
    d = data.bars("GC=F", "1d", "20y")
    c = data.cot("GOLD - COMMODITY EXCHANGE", years, report="disagg")
    h = data.bars("GC=F", "60m", "730d")
    print(f"(gold: {len(c)} weekly reports, {len(d)} daily bars, {len(h)} hourly bars)")
    print("\n## Gold: where the big money is\n")
    print("| rule | trades | per month | win | PF | PF 1st half | PF 2nd half | PF last 6m (n) | PF longs (n) | PF shorts (n) | total R | worst drawdown R | luck PF (95%) | verdict | detail |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    cost = MARKETS["gold"][1]
    for who, label in (("lev", "hedge funds"), ("am", "miners/refiners")):
        for fade in (True, False):
            pooled(f"positioning: {'fade' if fade else 'follow'} {label} at extremes",
                   [("GC", d, strategies.make_cot(c, 1, who, fade), cost)])
    for follow in (True, False):
        pooled(f"futures volume surge: {'follow' if follow else 'fade'}",
               [("GC", h, (lambda fo: lambda b: strategies.make_volume_spike(b, follow=fo))(follow), cost)])
    # the live channel rule, only when the big money agrees
    trend = strategies.daily_trend(d)
    live = strategies.with_daily_trend(strategies.make_donchian, trend)
    for who, label in (("lev", "hedge funds"), ("am", "miners")):
        pooled(f"live Gold rule, skip when {label} are crowded the same way",
               [("GC", h, strategies.with_cot_filter(live, c, who), cost)])


def main():
    if sys.argv[1:2] == ["gold-flows"]:
        return gold_flows()
    if sys.argv[1:2] == ["fx"]:
        return fx()
    if sys.argv[1:2] == ["flows"]:
        return flows()
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
