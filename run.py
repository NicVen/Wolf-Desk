"""THE WOLF PROJECT — pipeline runner (multi asset class).

scout (prices) -> compiler (score + analysis + broker match) -> data/opportunities_<class>.json
News is pulled on demand by the server (/news), not here, to keep refresh fast.

Run:  python run.py            (all classes)
      python run.py fx         (one class)
"""
import json, os, sys, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
from scout.prices import price_metrics
from compiler.score import score_one, rank
from compiler.analysis import analyze


def load(path):
    with open(os.path.join(C.DATA_DIR, path), "r", encoding="utf-8") as f:
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
        row["category"] = cat
        row["ticker"]   = ticker
        row["covkey"]   = covkey
        row["coverage"] = coverage_for(covkey, brokers)
        row["analysis"] = analyze(row)
        rows.append(row)
        print(f"  {row['score']:5.1f}  {name:14} {row['trend_desc']}")
    return rank(rows)


def write_class(clskey, cls, rows):
    payload = {"generated": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
               "asset": cls["label"], "class": clskey, "opportunities": rows}
    out = os.path.join(C.DATA_DIR, f"opportunities_{clskey}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"  wrote {out}")


def main(only=None):
    brokers = load("brokers.json")
    for key, cls in C.ASSET_CLASSES.items():
        if only and key != only:
            continue
        rows = build_class(key, cls, brokers)
        write_class(key, cls, rows)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
