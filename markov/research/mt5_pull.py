"""Pull deep H1 history from the DEMO MT5 terminal into ./cache in Yahoo-bar format.

Why: Yahoo caps hourly data at 730d, so the 2y sample gives only ~2 drawdown
cycles -- not enough to judge whether the recent 5-month flat stretch is normal.
MT5 holds years of H1 bars.

SAFETY: this attaches ONLY to the demo install and hard-aborts if the connected
account is not a demo (the FundedNext / live terminal is off-limits, standing rule).
It is read-only: bars only, no orders, no account changes.

Usage: python mt5_pull.py [years]
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5

DEMO_TERMINAL = r"C:\Program Files\MetaTrader\terminal64.exe"
FORBIDDEN_LOGINS = {13947862}  # FundedNext live -- never touch
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
YEARS = int(sys.argv[1]) if len(sys.argv) > 1 else 8

# bot symbol -> yahoo symbol (cache filenames follow the yahoo name so backtest.mjs finds them)
PAIRS = {
    "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "USDJPY=X",
    "USDCHF": "USDCHF=X", "AUDUSD": "AUDUSD=X", "NZDUSD": "NZDUSD=X",
    "USDCAD": "USDCAD=X", "GBPJPY": "GBPJPY=X", "EURJPY": "EURJPY=X",
    "EURGBP": "EURGBP=X", "XAUUSD": "GC=F", "XAGUSD": "SI=F",
    "USOIL": "CL=F", "NAS100": "NQ=F", "SPX500": "ES=F", "US30": "YM=F",
    "BTCUSD": "BTC-USD", "ETHUSD": "ETH-USD",
}
# broker naming varies; try these in order for the awkward ones
ALIASES = {
    "USOIL": ["USOIL", "XTIUSD", "WTI", "CRUDOIL", "UKOIL", "USOUSD"],
    "NAS100": ["NAS100", "USTEC", "NDX100", "US100", "NAS100.cash"],
    "SPX500": ["SPX500", "US500", "SP500", "SPX500.cash"],
    "US30": ["US30", "DJ30", "USA30", "US30.cash"],
    "BTCUSD": ["BTCUSD", "BTCUSD.", "BTC/USD"],
    "ETHUSD": ["ETHUSD", "ETHUSD.", "ETH/USD"],
}


def die(msg):
    print(f"ABORT: {msg}")
    mt5.shutdown()
    sys.exit(1)


def resolve(sym, available):
    for cand in ALIASES.get(sym, [sym]):
        if cand in available:
            return cand
    # suffix match (broker suffixes like .r, m, _SB, +)
    for a in available:
        if a.upper().startswith(sym.upper()) and len(a) <= len(sym) + 4:
            return a
    return None


def main():
    if not os.path.exists(DEMO_TERMINAL):
        print(f"ABORT: demo terminal not found at {DEMO_TERMINAL}")
        sys.exit(1)

    # bare attach to the DEMO install only -- no login/password (see MT5 investor downgrade note)
    if not mt5.initialize(path=DEMO_TERMINAL, portable=False):
        print(f"ABORT: initialize failed {mt5.last_error()}")
        sys.exit(1)

    info = mt5.account_info()
    if info is None:
        die("no account_info -- cannot verify this is a demo")
    is_demo = info.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO
    print(f"connected: login={info.login} server={info.server} trade_mode={info.trade_mode} demo={is_demo}")
    if info.login in FORBIDDEN_LOGINS or not is_demo:
        die(f"account {info.login} is not a demo -- refusing to touch it")

    os.makedirs(CACHE, exist_ok=True)
    available = {s.name for s in (mt5.symbols_get() or [])}
    print(f"{len(available)} symbols on server")

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=365 * YEARS)
    summary = {}

    for sym, yahoo in PAIRS.items():
        broker = resolve(sym, available)
        if not broker:
            print(f"  {sym:8s} NO MATCH -- skip")
            continue
        mt5.symbol_select(broker, True)
        rates = mt5.copy_rates_range(broker, mt5.TIMEFRAME_H1, start, end)
        if rates is None or len(rates) == 0:
            print(f"  {sym:8s} ({broker}) no H1 bars {mt5.last_error()}")
            continue
        bars = [
            {"t": int(r["time"]), "open": float(r["open"]), "high": float(r["high"]),
             "low": float(r["low"]), "close": float(r["close"]), "volume": int(r["tick_volume"])}
            for r in rates
        ]
        d1 = mt5.copy_rates_range(broker, mt5.TIMEFRAME_D1, start, end)
        dbars = [
            {"t": int(r["time"]), "open": float(r["open"]), "high": float(r["high"]),
             "low": float(r["low"]), "close": float(r["close"]), "volume": int(r["tick_volume"])}
            for r in (d1 if d1 is not None else [])
        ]
        safe = "".join(c if c.isalnum() else "_" for c in yahoo)
        with open(os.path.join(CACHE, f"{safe}_1h_mt5.json"), "w") as f:
            json.dump(bars, f)
        with open(os.path.join(CACHE, f"{safe}_1d_mt5.json"), "w") as f:
            json.dump(dbars, f)
        span = f"{datetime.utcfromtimestamp(bars[0]['t']):%Y-%m-%d}..{datetime.utcfromtimestamp(bars[-1]['t']):%Y-%m-%d}"
        summary[sym] = {"broker": broker, "h1_bars": len(bars), "d1_bars": len(dbars), "span": span}
        print(f"  {sym:8s} ({broker:12s}) H1 {len(bars):6d} bars  D1 {len(dbars):5d}  {span}")

    with open(os.path.join(CACHE, "mt5_pull_summary.json"), "w") as f:
        json.dump({"pulled": datetime.now(timezone.utc).isoformat(), "years": YEARS,
                   "server": info.server, "demo": is_demo, "symbols": summary}, f, indent=2)
    mt5.shutdown()
    print(f"\ndone: {len(summary)}/{len(PAIRS)} symbols -> cache/*_mt5.json")


if __name__ == "__main__":
    main()
