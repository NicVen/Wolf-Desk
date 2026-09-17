"""Excalibur → MT5 bridge: write per-symbol Markov regime files that EA Forge
EAs read to gate trades to the current regime (bull → longs, bear → shorts,
sideways → block both).

The reader contract (EA Forge's generated MarkovBias() in MT5):
  * The EA opens one file, reads the WHOLE thing, uppercases it, then:
      contains BULL or LONG  → allow longs  (returns  1)
      contains BEAR or SHORT → allow shorts (returns -1)
      otherwise              → block both   (returns  0)
      file missing/unreadable→ no gate      (returns  2, fail-open)
  * So a file must carry ONE state token and NOTHING else that contains any of
    those four keywords. We keep the state on line 1 and only keyword-free
    metadata after it, and hard-verify that before writing.

Gate policy (matches Excalibur's sample-size discipline):
  a confident directional regime (state BULL/BEAR AND it clears the n≥8 vote
  gate) → gate to that direction; SIDE, a thin/non-voting regime, or no data →
  "SIDE" → the EA blocks both. We never emit a direction we don't trust, and
  never leave a stale directional file implying a trend that isn't there.

Output directory (first that applies):
  $MARKOV_OUT_DIR, else MT5 Common\\Files under %APPDATA% (Windows), else a
  local ./markov_out. Set MARKOV_EXPORT=0 to turn the writer off entirely.

Files written per run:
  markov_<SYMBOL>.txt   one per instrument (the gate the EA reads)
  markov_regime.txt     alias = Gold/XAUUSD, so the proven-edge EA works with
                        its default InpMarkovFile out of the box
  markov_regime.json    full human/debug summary (states, persist, n, vote)
"""
import os, json, datetime, re

import atomicio

try:
    from scout.regime import MIN_N_VOTE
except Exception:
    MIN_N_VOTE = 8   # keep in lockstep with scout.regime

# Display name → MT5 symbol. FX pairs are derived by stripping "/". Indices and
# stocks vary by broker: these are sensible defaults — rename the file, or point
# the EA's InpMarkovFile at your broker's exact symbol, if yours differs.
_SYMBOL = {
    "Gold": "XAUUSD", "Silver": "XAGUSD", "Copper": "XCUUSD",
    "Platinum": "XPTUSD", "Palladium": "XPDUSD",
    "WTI Crude": "USOIL", "Brent": "UKOIL", "Natural Gas": "NATGAS",
    "Wheat": "WHEAT", "Corn": "CORN", "Soybeans": "SOYBEAN",
    "Coffee": "COFFEE", "Sugar": "SUGAR", "Cocoa": "COCOA",
    "S&P 500": "US500", "Nasdaq 100": "US100", "Dow Jones": "US30",
    "Russell 2000": "US2000", "DAX": "DE40", "FTSE 100": "UK100",
    "Euro Stoxx 50": "EU50", "Nikkei 225": "JP225", "Hang Seng": "HK50",
    "ASX 200": "AU200",
    # stocks fall through to their ticker (see mt5_symbol)
}

_BANNED = ("BULL", "BEAR", "LONG", "SHORT")


def mt5_symbol(name, ticker=None):
    if name in _SYMBOL:
        return _SYMBOL[name]
    if "/" in name:                                  # FX pair, e.g. EUR/USD
        return name.replace("/", "").upper()
    if ticker and re.fullmatch(r"[A-Za-z.]+", ticker or ""):
        return ticker.upper().replace(".", "")       # stock ticker
    return re.sub(r"[^A-Za-z0-9]", "", name).upper()


def _gate_state(regime):
    """Confident BULL/BEAR (voting) → that direction; everything else → SIDE."""
    r = regime or {}
    st = r.get("state")
    vote = r.get("vote")
    if vote is None:                                 # older payload: derive
        vote = (r.get("n") or 0) >= MIN_N_VOTE
    return st if (st in ("BULL", "BEAR") and vote) else "SIDE"


def out_dir():
    d = os.environ.get("MARKOV_OUT_DIR")
    if d:
        return d
    appdata = os.environ.get("APPDATA")              # Windows: MT5 Common\Files
    if appdata:
        return os.path.join(appdata, "MetaQuotes", "Terminal", "Common", "Files")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "markov_out")


def _compose(state, meta):
    """state on line 1; keyword-free metadata on line 2. If the metadata would
    smuggle in a conflicting keyword (e.g. a symbol containing 'LONG'), drop the
    metadata rather than mislead the EA — the gate token must stay unambiguous."""
    line2 = "# " + meta
    if any(k in line2.upper() for k in _BANNED):
        line2 = "#"
    return state + "\n" + line2 + "\n"


def _write(path, text):
    atomicio.write_text(path, text)   # atomic: an EA never reads a half-written gate


def export(rows):
    """rows: iterable of opportunity dicts (name, regime, ticker). Writes one
    markov_<SYMBOL>.txt per instrument, a Gold-aliased markov_regime.txt, and a
    markov_regime.json summary. Returns (files_written, directory), or (0, None)
    if disabled or the directory can't be created."""
    if os.environ.get("MARKOV_EXPORT", "1") == "0":
        return 0, None
    d = out_dir()
    try:
        os.makedirs(d, exist_ok=True)
    except Exception as e:
        print(f"  [markov] cannot create {d}: {e}")
        return 0, None

    asof = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ")
    summary, n_written = [], 0
    for o in rows:
        reg = o.get("regime") or {}
        sym = mt5_symbol(o.get("name", ""), o.get("ticker"))
        gate = _gate_state(reg)
        persist = reg.get("persist")
        meta = ("sym=%s persist=%s n=%s conf=%s asof=%s src=wolf-desk"
                % (sym, persist if persist is not None else "NA",
                   reg.get("n", 0), reg.get("confidence", "NA"), asof))
        _write(os.path.join(d, "markov_%s.txt" % sym), _compose(gate, meta))
        n_written += 1
        if o.get("name") == "Gold":                  # default-alias for proven EA
            _write(os.path.join(d, "markov_regime.txt"), _compose(gate, meta))
        summary.append({"name": o.get("name"), "symbol": sym, "gate": gate,
                        "state": reg.get("state"), "persist": persist,
                        "n": reg.get("n", 0), "confidence": reg.get("confidence"),
                        "vote": reg.get("vote")})
    try:
        _write(os.path.join(d, "markov_regime.json"),
               json.dumps({"asof": asof, "instruments": summary}, indent=2))
    except Exception:
        pass
    print("  [markov] wrote %d regime file(s) -> %s" % (n_written, d))
    return n_written, d
