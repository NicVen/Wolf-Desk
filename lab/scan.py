"""Scan every market a prop firm lets you trade with every rule in the lab.

    python lab/scan.py

Markets are the CFDs prop firms offer (gold, silver, oil, gas, the big stock
indices, crypto, FX), priced from free Yahoo futures/index/spot history.
Costs are a typical prop-firm spread + commission, as a share of price.
Same pass bar as the rest of the lab: PF >= 1.3 in both halves, >= 30 trades,
better than the rule on shuffled (pattern-free) copies of the market.
Testing ~10 rules on ~30 markets WILL throw up a few lucky passes, so a pass
here only earns a place in a paper test, never a live channel.

Prop-firm view: risking 0.5% of the account per trade, worst drawdown R x 0.5
is the % drawdown; most firms fail you at 10% total (5% in one day).
"""
import data
import engine
import run
import strategies

MARKETS = {   # name prop firms use: (yahoo symbol, round-trip cost as share of price)
    "XAUUSD gold": ("GC=F", 0.00013),
    "XAGUSD silver": ("SI=F", 0.0006),
    "XPTUSD platinum": ("PL=F", 0.001),
    "COPPER": ("HG=F", 0.0008),
    "USOIL WTI": ("CL=F", 0.0004),
    "UKOIL Brent": ("BZ=F", 0.0004),
    "NATGAS": ("NG=F", 0.002),
    "US500": ("ES=F", 0.0001),
    "NAS100": ("NQ=F", 0.0001),
    "US30": ("YM=F", 0.0001),
    "US2000": ("RTY=F", 0.0002),
    "GER40": ("^GDAXI", 0.0001),
    "UK100": ("^FTSE", 0.00015),
    "JP225": ("^N225", 0.0002),
    "EU50": ("^STOXX50E", 0.0002),
    "HK50": ("^HSI", 0.0003),
    "AUS200": ("^AXJO", 0.0003),
    "BTCUSD": ("BTC-USD", 0.0008),
    "ETHUSD": ("ETH-USD", 0.001),
    "SOLUSD": ("SOL-USD", 0.0015),
    "XRPUSD": ("XRP-USD", 0.0015),
    "EURUSD": ("EURUSD=X", 0.00011),
    "GBPUSD": ("GBPUSD=X", 0.00012),
    "USDJPY": ("JPY=X", 0.00011),
    "AUDUSD": ("AUDUSD=X", 0.00015),
    "USDCAD": ("CAD=X", 0.00015),
    "EURJPY": ("EURJPY=X", 0.00015),
    "GBPJPY": ("GBPJPY=X", 0.0002),
    "AUDJPY": ("AUDJPY=X", 0.0002),
    "EURGBP": ("EURGBP=X", 0.00015),
}

HOURLY = {
    "breakout + trend": strategies.make_donchian,
    "trend pullback": strategies.make_pullback,
    "session breakout": strategies.make_session_break,
    "fade extremes": strategies.make_fade,
    "time-of-day (walk-forward)": strategies.make_hour_of_day,
    "volume surge": strategies.make_volume_spike,
}
WITH_TREND = ("breakout + trend", "trend pullback", "session breakout")


def score(bars, make, cost):
    tr = engine.run(bars, make(bars), cost)
    if len(tr) < 10:
        return None
    days = (bars[-1]["t"] - bars[0]["t"]) / 86400
    mid = bars[len(bars) // 2]["t"]
    a = [t for t in tr if t["t"] < mid]
    b = [t for t in tr if t["t"] >= mid]
    last = [t for t in tr if t["t"] >= bars[-1]["t"] - 180 * 86400]
    s, sa, sb, sl = (engine.stats(tr, days), engine.stats(a, days / 2),
                     engine.stats(b, days / 2), engine.stats(last, 180))
    lucks = []
    for k in range(5):
        sh = run.shuffled(bars, k)
        for x, o in zip(sh, bars):
            x["v"] = o.get("v", 0)
        lucks.append(engine.stats(engine.run(sh, make(sh), cost), 1)["pf"])
    luck = max(lucks)
    ok = sa["pf"] >= 1.3 and sb["pf"] >= 1.3 and s["n"] >= 30 and s["pf"] > luck
    if ok:      # a candidate: re-check luck harder (95th percentile of 20 shuffles)
        for k in range(5, 20):
            sh = run.shuffled(bars, k)
            for x, o in zip(sh, bars):
                x["v"] = o.get("v", 0)
            lucks.append(engine.stats(engine.run(sh, make(sh), cost), 1)["pf"])
        luck = sorted(lucks)[18]
        ok = s["pf"] > luck
    months = max(days / 30.4, 1)
    return {"n": s["n"], "pm": s["per_month"], "win": s["win"], "pf": s["pf"],
            "a": sa["pf"], "b": sb["pf"], "l6": sl["pf"], "ln": sl["n"],
            "r": s["total_r"], "dd": s["max_dd_r"], "luck": luck, "ok": ok,
            "month_pct": round(s["total_r"] * 0.5 / months, 2)}


DAILY = {}


def main():
    rows = []
    for name, (sym, pct) in MARKETS.items():
        try:
            h = data.bars(sym, "60m", "730d")
            d = data.bars(sym, "1d", "20y")
        except Exception as e:
            print(f"(skipped {name}: {e})")
            continue
        h = [b for b in h if b["l"] > 0]      # WTI went negative in April 2020
        d = [b for b in d if b["l"] > 0]
        if len(h) < 1000:
            print(f"(skipped {name}: only {len(h)} hourly bars)")
            continue
        cost_h, cost_d = h[-1]["c"] * pct, d[-1]["c"] * pct
        DAILY[name] = (d, cost_d)
        trend = strategies.daily_trend(d)
        rules = dict(HOURLY)
        for k in WITH_TREND:
            rules[k + " + daily trend"] = strategies.with_daily_trend(HOURLY[k], trend)
        for rule, make in rules.items():
            try:
                r = score(h, make, cost_h)
            except Exception as e:
                print(f"({name} / {rule}: {e})")
                continue
            if r:
                rows.append((name, rule, r))
        try:
            r = score(d, strategies.make_trend_daily, cost_d)
            if r:
                rows.append((name, "daily trend (20y daily bars)", r))
        except Exception as e:
            print(f"({name} / daily trend: {e})")

    passed = sorted((x for x in rows if x[2]["ok"]), key=lambda x: -min(x[2]["a"], x[2]["b"]))
    print(f"\n## Prop-firm market scan: {len(passed)} of {len(rows)} market/rule pairs pass\n")
    print("| market | rule | trades | per month | win | PF | PF 1st half | PF 2nd half | PF last 6m (n) | "
          "worst drawdown R | drawdown at 0.5% risk | avg month at 0.5% risk | luck PF |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for m, rule, r in passed:
        print(f"| {m} | {rule} | {r['n']} | {r['pm']} | {r['win']}% | {r['pf']} | {r['a']} | {r['b']} | "
              f"{r['l6']} ({r['ln']}) | {r['dd']} | {r['dd'] * 0.5:.1f}% | {r['month_pct']:+}% | {r['luck']} |")
    print("\n## One portfolio: daily trend on EVERY non-FX market at once (no picking)\n")
    print("| portfolio | trades | per month | win | PF | PF 1st half | PF 2nd half | PF last 6m (n) | PF longs (n) | PF shorts (n) | total R | worst drawdown R | luck PF (95%) | verdict | PF per market (n) |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    nonfx = [m for m in DAILY if not any(c in m for c in ("USD", "JPY", "GBP", "CAD")) or m in ("XAUUSD gold", "XAGUSD silver", "XPTUSD platinum", "BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD")]
    run.pooled("daily trend, all metals + energy + indices + crypto",
               [(m.split()[0], DAILY[m][0], strategies.make_trend_daily, DAILY[m][1]) for m in nonfx])
    run.pooled("daily trend, all FX pairs",
               [(m, DAILY[m][0], strategies.make_trend_daily, DAILY[m][1]) for m in DAILY if m not in nonfx])
    print("\n## Best rule per market (pass or not)\n")
    print("| market | best rule | trades | PF | PF 1st half | PF 2nd half | PF last 6m (n) | verdict |")
    print("|---|---|---|---|---|---|---|---|")
    for m in MARKETS:
        mine = [x for x in rows if x[0] == m]
        if not mine:
            continue
        _, rule, r = max(mine, key=lambda x: min(x[2]["a"], x[2]["b"]))
        print(f"| {m} | {rule} | {r['n']} | {r['pf']} | {r['a']} | {r['b']} | {r['l6']} ({r['ln']}) | "
              f"{'PASS' if r['ok'] else 'no'} |")


if __name__ == "__main__":
    main()
