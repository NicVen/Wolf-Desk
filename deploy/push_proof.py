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

import datetime
import json
import os
import re
import sys
import urllib.request
import urllib.parse
from pathlib import Path

# HQ folder holds the *_view.json the snapshot reads. Defaults to the real HQ
# path so the script runs from anywhere (e.g. Downloads) with no file-moving;
# override with HQ_DIR. Falls back to the script's own folder if that path is
# absent (e.g. running on a different machine).
_HQ_DEFAULT = Path(r"C:\Users\nvent\OneDrive\Desktop\CLAUDE\Projects\STAALWAG-HQ")
HQ_DIR = Path(os.environ.get("HQ_DIR")
              or (_HQ_DEFAULT if _HQ_DEFAULT.exists() else Path(__file__).resolve().parent))
# Where the daily plan is written by the desk (agents/daily-plan.js). Override
# with PLAN_FILE if the desk lives elsewhere.
PLAN_FILE = Path(os.environ.get("PLAN_FILE")
                 or r"C:\Users\nvent\nicos-trading-desk\TODAYS-PLAN.md")
# Live domain by default; override with WOLF_HOST for the sslip fallback
# (https://178.104.88.38.sslip.io) or a local test server.
HOST = (os.environ.get("WOLF_HOST") or "https://staalwag.com").rstrip("/")
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


def _load_plan():
    """Parse the desk's TODAYS-PLAN.md into a public-safe plan block.

    Handles both a live setup (bias + entry/stop/targets) and a STAND-ASIDE day.
    Returns None if no plan file is present.
    """
    try:
        txt = PLAN_FILE.read_text(encoding="utf-8")
    except Exception:
        return None

    def find(pat):
        m = re.search(pat, txt, re.I)
        return m.group(1).strip() if m else None

    plan = {"date": find(r"\*\*Date:\*\*\s*(.+?)\s*\|"),
            "asset": find(r"\|\s*Asset\s*\|\s*([A-Z0-9]+)") or "XAUUSD"}

    if re.search(r"STAND ASIDE", txt, re.I):
        plan.update({"stand_aside": True,
                     "reason": find(r"Reason:\s*(.+)") or "conditions not favourable",
                     "bias": find(r"context only\):\s*(\w+)") or find(r"BIAS:\s*(\w+)")})
        return plan

    plan.update({
        "stand_aside": False,
        "bias": (find(r"\|\s*Bias\s*\|\s*(\w+)") or find(r"BIAS:\s*(\w+)")),
        "entry": find(r"Entry Zone\s*\|\s*([^\|\n]+)"),
        "stop": find(r"Stop Loss\s*\|\s*([^\|\n]+)"),
        "tp1": find(r"Target 1\s*\|\s*([^\|\n]+)"),
        "tp2": find(r"Target 2\s*\|\s*([^\|\n]+)"),
        "lot": find(r"Lot Size\*{0,2}\s*\|\s*\*{0,2}([^\|\n*]+)"),
        "rr": find(r"R:R\s*\|\s*([^\|\n]+)"),
    })
    # Strip desk jargon like "(worst-edge fill)" — the public plan shows a clean R:R.
    if plan.get("rr"):
        plan["rr"] = re.sub(r"\s*\(.*$", "", plan["rr"]).strip()
    return plan


def _load_plans():
    """The full daily slate: the primary Gold plan plus the FX/crypto setups the
    desk writes under '## MORE PLANS'. Returns a list (primary first)."""
    primary = _load_plan()
    plans = [primary] if primary else []
    try:
        txt = PLAN_FILE.read_text(encoding="utf-8")
    except Exception:
        return plans
    # ### SYMBOL — DIR  then  Entry: a – b | Stop: c | TP1: d | TP2: e | R:R f
    for m in re.finditer(
            r"###\s*([A-Z0-9]+)\s*[—\-]\s*(LONG|SHORT|BUY|SELL)\s*\n([^\n]+)", txt, re.I):
        sym, bias, line = m.group(1).upper(), m.group(2).upper(), m.group(3)

        def g(lbl):
            mm = re.search(lbl + r"\s*:?\s*([0-9][0-9.,]*(?:\s*[–—-]\s*[0-9][0-9.,]*)?)", line, re.I)
            return mm.group(1).strip() if mm else None

        rr = re.search(r"R:R\s*([0-9:.]+)", line, re.I)
        plans.append({
            "asset": sym, "bias": bias, "stand_aside": False,
            "entry": g("Entry"), "stop": g("Stop"),
            "tp1": g("TP1"), "tp2": g("TP2"),
            "rr": rr.group(1) if rr else None,
        })
    return plans


def _stats(outcomes):
    """Trades, win-rate, profit-factor, net USD from a list of WIN/LOSS outcomes."""
    wins = [o for o in outcomes if o.get("result") == "WIN"]
    losses = [o for o in outcomes if o.get("result") == "LOSS"]
    gp = sum(o.get("pnl_usd", 0) or 0 for o in wins)
    gl = sum(o.get("pnl_usd", 0) or 0 for o in losses)
    n = len(wins) + len(losses)
    wr = round(100 * len(wins) / n, 1) if n else None
    pf = round(gp / abs(gl), 2) if gl else None
    return n, wr, pf, round(gp + gl, 2)


def build_snapshot():
    """Assemble the public-safe proof from HQ's own view files.

    EVERY record goes on the wall, good or bad -- the losers show where to
    focus. Nothing is hidden and nothing is invented; each row is labelled with
    what it actually is (real EA fills / dispatched signals / raw scanner).
    """
    ea = _load("ea_results.json") or {}
    bank = _load("desk_bank_view.json") or {}
    research = _load("paperclip_view.json") or {}
    scanner = _load("signals_view.json") or {}

    desks = []

    # 1) REAL EA fills, per product -- the actual executed money record.
    acct, win = ea.get("account"), ea.get("window_days")
    for p in (ea.get("products") or []):
        n, wr, pf, net = _stats(p.get("outcomes") or [])
        if n == 0:
            desks.append({"name": p.get("product"), "status": "parked",
                          "provenance": "live", "trades": 0, "win_rate": None,
                          "pf": None, "net_usd": 0,
                          "note": "live EA — no fills in the window"})
            continue
        proven = net > 0 and pf and pf >= 1.3 and n >= 30
        desks.append({
            "name": p.get("product"), "status": "proven" if proven else "proving",
            "provenance": "live", "trades": n, "win_rate": wr, "pf": pf,
            "net_usd": net,
            "note": "real EA fills — account %s, last %sd" % (acct, win),
        })

    # 2) Banked dispatched signals (the Telegram desks), scored on real price.
    for name, d in (bank.get("by_desk") or {}).items():
        trades = int(d.get("trades") or 0)
        net = _num(d.get("net_usd"))
        conclusive = bool(d.get("conclusive"))
        proven = conclusive and (net or 0) > 0 and trades >= 30
        desks.append({
            "name": "%s — signals" % name,
            "status": "proven" if proven else "proving", "provenance": "live",
            "trades": trades, "win_rate": _num(d.get("win_rate")),
            "pf": _num(d.get("profit_factor")), "net_usd": net,
            "note": "dispatched signals scored on real price"
                    + ("" if conclusive else " — building sample"),
        })

    # 3) Raw Markov scanner -- the unfiltered firehose. Shown honestly, parked:
    #    it is research signal, not a traded desk, and the win rate says so.
    ss = scanner.get("stats") or {}
    if ss.get("closed"):
        desks.append({
            "name": "Markov signal bot (raw scanner)", "status": "parked",
            "provenance": "shadow", "trades": int(ss.get("closed") or 0),
            "win_rate": _num(ss.get("win_rate")), "pf": None, "net_usd": None,
            "note": "unfiltered scanner output — research only, never traded",
        })

    # 4) Signal Engine v2 ("My Trading Bot") -- forward paper track, scored on
    #    real price. Small and currently red; shown because every record counts.
    ev2 = _load("engine_v2_track.json") or {}
    eo = ev2.get("overall") or {}
    if eo.get("closed") is not None:
        closed = int(eo.get("closed") or 0)
        openn = int(eo.get("open") or 0)
        net_r = _num(eo.get("net_r"))
        edges = ", ".join((ev2.get("per_edge") or {}).keys())
        desks.append({
            "name": "Signal Engine v2 (My Trading Bot)", "status": "proving",
            "provenance": "shadow", "trades": closed,
            "win_rate": _num(eo.get("win_rate")), "pf": None, "net_usd": None,
            "note": "forward paper — scored on real price; %s net R over %d closed (%d open)%s"
                    % (net_r, closed, openn, (" · edges: " + edges) if edges else ""),
        })

    # Proven first, then by biggest net.
    desks.sort(key=lambda x: (x["status"] != "proven", -((x["net_usd"] or 0))))

    # Headline: the strongest genuinely-proven record (real fills win over signals).
    headline = None
    proven_rows = [d for d in desks if d["status"] == "proven"]
    if proven_rows:
        h = proven_rows[0]
        headline = {"name": h["name"], "provenance": h["provenance"], "pf": h["pf"],
                    "net_usd": h["net_usd"], "trades": h["trades"],
                    "win_rate": h["win_rate"], "note": "the anchor — real executed record"}

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

    return {
        "firm": "STAALWAG",
        "generated": bank.get("generated") or research.get("generated"),
        # When this snapshot was published. The page uses it to mark a plan
        # "fresh" or "expired" (older than 4h) so an old plan never looks current.
        "published_at": datetime.datetime.now(datetime.timezone.utc)
                        .replace(microsecond=0).isoformat(),
        "plans": _load_plans(),
        "headline": headline,
        "desks": desks,
        "research": research_out,
        "rules": RULES,
        "disclaimer": DISCLAIMER,
    }


def main():
    dry = "--dry" in sys.argv
    snap = build_snapshot()

    if not snap["desks"] and not snap["headline"]:
        print("[push_proof] No banked data found in %s" % HQ_DIR)
        print("             Expected desk_bank_view.json (from desk_bank.py). "
              "Run an HQ Refresh first, then re-run this.")
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
            print("[push_proof] Published -> %s/proof  (%d desks, %d plans)"
                  % (HOST, len(snap["desks"]), len(snap.get("plans") or [])))
        else:
            print("[push_proof] Server rejected it:", resp)
    except Exception as e:
        print("[push_proof] Failed to publish:", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
