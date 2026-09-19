"""THE WOLF PROJECT — pipeline runner (multi asset class).

scout (prices) -> compiler (score + analysis + broker match) -> data/opportunities_<class>.json
News is pulled on demand by the server (/news), not here, to keep refresh fast.

Run:  python run.py            (all classes)
      python run.py fx         (one class)
"""
import json, os, sys, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
import atomicio
from scout.prices import price_metrics
from compiler.score import score_one, rank
from compiler.analysis import analyze
from compiler.validation import validate
from compiler.outlook import outlook

# Multiple-testing universe: how many markets the desk scans in total. Used to
# deflate each DSR (best-of-N shouldn't look like a proven edge).
TOTAL_UNIVERSE = sum(len(c["universe"]) for c in C.ASSET_CLASSES.values())


def _side(verdict):
    if not verdict:
        return 0
    if verdict.startswith("BUY"):
        return 1
    if verdict == "SELL":
        return -1
    return 0


def load(path):
    # tolerant: a class with no manual signals file scores on price metrics alone
    p = os.path.join(C.DATA_DIR, path)
    if not os.path.exists(p):
        return {}
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def coverage_for(key, brokers):
    out = []
    for b in brokers["brokers"] + brokers["propfirms"]:
        if b.get(key):
            out.append({"name": b["name"], "type": b["type"],
                        "leverage": b.get("max_leverage", b.get("rules", "")),
                        "notes": b.get("notes", "")})
    return out


def build_class(clskey, cls, brokers):
    signals = load(cls["signals"])
    rows = []
    print(f"WOLF [{clskey}]: scouting prices ...")
    for name, (ticker, cat, covkey) in cls["universe"].items():
        pm = price_metrics(ticker)
        row = score_one(name, pm, signals.get(name, {}))
        row["regime"]   = pm.get("regime") if pm else None
        row["spark"]    = pm.get("spark") if pm else None
        row["atr_abs"]  = pm.get("atr_abs") if pm else None
        row["swing_lo"] = pm.get("swing_lo") if pm else None
        row["swing_hi"] = pm.get("swing_hi") if pm else None
        row["daily"]    = pm.get("daily") if pm else None
        row["category"] = cat
        row["ticker"]   = ticker
        row["covkey"]   = covkey
        row["coverage"] = coverage_for(covkey, brokers)
        row["analysis"] = analyze(row)
        # DSR real-vs-noise label, in the verdict's direction (label only —
        # never folded into the score or verdict).
        row["validation"] = validate((pm or {}).get("returns"),
                                     _side(row["analysis"].get("verdict")),
                                     TOTAL_UNIVERSE)
        row["outlook"] = outlook(row)   # daily plain-language brief per instrument
        rows.append(row)
        print(f"  {row['score']:5.1f}  {name:14} {row['trend_desc']}")
    return rank(rows)


def write_class(clskey, cls, rows):
    payload = {"generated": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
               "asset": cls["label"], "class": clskey, "opportunities": rows}
    out = os.path.join(C.DATA_DIR, f"opportunities_{clskey}.json")
    atomicio.write_json(out, payload)   # atomic: a crash mid-write can't corrupt it
    print(f"  wrote {out}")


def main(only=None):
    brokers = load("brokers.json")
    built = []
    for key, cls in C.ASSET_CLASSES.items():
        if only and key != only:
            continue
        rows = build_class(key, cls, brokers)
        write_class(key, cls, rows)
        built.extend(rows)
    # Bridge: write per-symbol Markov regime files for EA Forge EAs to gate on.
    try:
        import markov_export
        markov_export.export(built)
    except Exception as e:
        print(f"  [markov] export skipped: {e}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
