"""Publish STAALWAG's public track record: PC HQ -> VPS proof wall.

Run this on the PC, in the STAALWAG-HQ folder, AFTER a dashboard "Refresh".
It reads the HQ's already-computed, append-only view files and POSTs a
public-safe snapshot to the VPS, which serves it at  https://<host>/proof .

It NEVER re-scores anything -- it forwards the exact numbers HQ already banked,
so the public page can never disagree with your private cockpit. Losses are
sent too; the honesty is the point.

Environment (set once with `setx`, or edit the defaults below):
  WOLF_HOST         e.g. https://178.104.88.38.sslip.io   (or your real domain)
  WOLF_PASS         your admin key (same one the WOLF desk uses)   [required]
  HQ_DIR            folder holding the *_view.json (default: this script's dir)
  GOLD_PROVENANCE   how to label a featured Gold EA number: live | backtest
                    (only used if you opt to feature it; off by default)

Run:  python push_proof.py
      python push_proof.py --dry     # print the snapshot, do NOT send
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
import urllib.parse
from pathlib import Path

HQ_DIR = Path(os.environ.get("HQ_DIR") or Path(__file__).resolve().parent)
HOST = (os.environ.get("WOLF_HOST") or "https://178.104.88.38.sslip.io").rstrip("/")
KEY = os.environ.get("WOLF_PASS", "")

RULES = [
    "Scored on real market price, not on anyone's execution.",
    "Fills use the worst edge of the entry zone -- the realistic fill, never the flattering one.",
    "When one bar touches both stop and target, it is counted as a LOSS.",
    "Unfilled setups are shown separately, never quietly counted as wins.",
    "Append-only: once a result is banked it is never re-derived, edited, or deleted.",
]
DISCLAIMER = ("Signals, not financial advice. Past performance does not "
              "guarantee future results.")


def _load(name):
    p = HQ_DIR / name
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _num(v):
    try:
        return round(float(v), 2)
    except Exception:
        return None


def build_snapshot():
    """Assemble the public-safe proof from HQ's own view files."""
    bank = _load("desk_bank_view.json") or {}
    research = _load("paperclip_view.json") or {}

    overall = bank.get("overall") or {}
    by_desk = bank.get("by_desk") or {}

    # Per-desk rows (real, append-only, banked at 0.1 lot).
    desks = []
    for name, d in by_desk.items():
        trades = int(d.get("trades") or 0)
        net = _num(d.get("net_usd"))
        conclusive = bool(d.get("conclusive"))
        # Honest status: only "proven" once the sample is conclusive AND positive.
        if conclusive and (net or 0) > 0 and trades >= 30:
            status = "proven"
        else:
            status = "proving"
        desks.append({
            "name": name, "status": status, "provenance": "live",
            "trades": trades, "win_rate": _num(d.get("win_rate")),
            "pf": _num(d.get("profit_factor")), "net_usd": net,
            "note": None if conclusive else "building sample, not yet conclusive",
        })
    desks.sort(key=lambda x: (x["status"] != "proven", -(x["net_usd"] or 0)))

    # Headline: only feature a desk that is genuinely proven. Otherwise feature
    # the whole-firm banked record, labelled honestly -- never invent a winner.
    headline = None
    proven = [d for d in desks if d["status"] == "proven"]
    if proven:
        h = proven[0]
        headline = {"name": h["name"], "provenance": "live", "pf": h["pf"],
                    "net_usd": h["net_usd"], "trades": h["trades"],
                    "win_rate": h["win_rate"], "note": "the anchor"}
    elif overall.get("trades"):
        headline = {
            "name": "STAALWAG — all desks", "provenance": "live",
            "pf": _num(overall.get("profit_factor")),
            "net_usd": _num(overall.get("net_usd")),
            "trades": int(overall.get("trades") or 0),
            "win_rate": _num(overall.get("win_rate")),
            "note": "every dispatched signal, banked once at 0.1 lot on real price",
        }

    # Research desk (shadow -- scored, never traded).
    ro = research.get("overall") or {}
    research_out = None
    if ro.get("calls"):
        research_out = {
            "calls": int(ro.get("calls") or 0),
            "filled": int(ro.get("filled") or 0),
            "accuracy": _num(ro.get("accuracy")),
            "pf": _num(ro.get("profit_factor")),
            "note": ("Paperclip research desk -- calls scored on real price. "
                     "Shadow only; nothing is traded off it."),
        }

    # Recent resolved (last 8), from the banked ledger.
    recent = []
    for r in (bank.get("recent") or [])[:8]:
        recent.append({
            "desk": r.get("desk"), "pair": r.get("pair"),
            "direction": r.get("direction"), "result": r.get("result"),
            "r": _num(r.get("r")),
            "date": (r.get("closed") or r.get("time") or "")[:10],
        })

    return {
        "firm": "STAALWAG",
        "generated": bank.get("generated") or research.get("generated"),
        "headline": headline,
        "desks": desks,
        "research": research_out,
        "recent": recent,
        "rules": RULES,
        "disclaimer": DISCLAIMER,
    }


def main():
    dry = "--dry" in sys.argv
    snap = build_snapshot()

    if not snap["desks"] and not snap["headline"]:
        print("[push_proof] No banked data found in %s -- run an HQ Refresh first."
              % HQ_DIR)
        sys.exit(1)

    if dry:
        print(json.dumps(snap, indent=2))
        return

    if not KEY:
        print("[push_proof] WOLF_PASS not set. Set it, then re-run.")
        sys.exit(1)

    body = json.dumps(snap).encode("utf-8")
    url = HOST + "/proof?key=" + urllib.parse.quote(KEY)
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read().decode("utf-8"))
        if resp.get("ok"):
            print("[push_proof] Published -> %s/proof  (%d desks, %d recent)"
                  % (HOST, len(snap["desks"]), len(snap["recent"])))
        else:
            print("[push_proof] Server rejected it:", resp)
    except Exception as e:
        print("[push_proof] Failed to publish:", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
