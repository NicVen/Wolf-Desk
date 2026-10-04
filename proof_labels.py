"""Honest provenance on the public proof wall.

EA results from a DEMO trading account must never be shown as "live" / "real".
The PC HQ publishes /proof.json; this relabels any row whose fills come from a
known demo account, on ingest and again on read, so the public page is right
even if an older push_proof.py on the PC still says "live". Numbers are never
touched -- only the labels.

Env: DEMO_ACCOUNTS  comma-separated MT5 account numbers that are demo accounts
                    (default: 109223212, the MetaQuotes-Demo account).
"""
import os
import re

DEMO_ACCOUNTS = [a.strip() for a in
                 os.environ.get("DEMO_ACCOUNTS", "109223212").split(",") if a.strip()]


def _is_demo_row(row, accounts):
    note = str((row or {}).get("note") or "")
    return any(re.search(r"\baccount %s\b" % re.escape(a), note) for a in accounts)


def _relabel_note(note):
    note = re.sub(r"^real EA fills", "EA fills on a demo account", note)
    return note.replace("live EA", "demo EA")


def label_demo(data, accounts=None):
    """Return `data` with demo-account rows labelled provenance="demo"."""
    if not isinstance(data, dict):
        return data
    accounts = DEMO_ACCOUNTS if accounts is None else accounts
    demo_names = set()
    for row in data.get("desks") or []:
        if isinstance(row, dict) and _is_demo_row(row, accounts):
            row["provenance"] = "demo"
            row["note"] = _relabel_note(str(row.get("note") or ""))
            demo_names.add(row.get("name"))
    # Older pushes wrote empty EA rows as "live EA — no fills in the window"
    # without an account number; they come from the same EA account.
    if demo_names:
        for row in data.get("desks") or []:
            if isinstance(row, dict) and str(row.get("note") or "").startswith("live EA"):
                row["provenance"] = "demo"
                row["note"] = _relabel_note(str(row.get("note") or ""))
                demo_names.add(row.get("name"))
    h = data.get("headline")
    if isinstance(h, dict) and (h.get("name") in demo_names or h.get("provenance") == "demo"):
        h["provenance"] = "demo"
        h["note"] = "the anchor — demo forward-test (EA fills on a demo account)"
    return data
