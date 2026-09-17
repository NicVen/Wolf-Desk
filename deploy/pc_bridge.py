"""PC-side MT5 bridge.

The engine now runs on the VPS, so it writes the Markov gate files on the VPS —
useless to the EAs on THIS PC. This script pulls the VPS's regime summary
(GET /markov.json) and writes the gate files into this PC's MetaTrader
Common\\Files, so your local EAs keep gating on the desk's regime.

It writes exactly what the on-server writer does: one state token per file,
keyword-free metadata, atomic replace, same gate policy (the server already
applied the n>=8 vote gate, so we just mirror its 'gate' field).

Environment:
  WOLF_HOST     e.g. https://178.104.88.38.sslip.io   (required)
  WOLF_PASS     your access key                        (required)
  MT5_FILES     target dir (default: %APPDATA%\\MetaQuotes\\Terminal\\Common\\Files)
  POLL_SECONDS  repeat every N seconds (default 300; 0 = run once and exit)
"""
import os
import sys
import time
import json
import tempfile
import urllib.request
import urllib.parse

HOST = (os.environ.get("WOLF_HOST") or "").rstrip("/")
KEY = os.environ.get("WOLF_PASS", "")
OUT = os.environ.get("MT5_FILES") or os.path.join(
    os.environ.get("APPDATA", ""), "MetaQuotes", "Terminal", "Common", "Files")
POLL = int(os.environ.get("POLL_SECONDS", "300"))
BANNED = ("BULL", "BEAR", "LONG", "SHORT")


def _atomic(path, text):
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="ascii", errors="ignore", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _compose(state, meta):
    line2 = "# " + meta
    if any(k in line2.upper() for k in BANNED):
        line2 = "#"
    return state + "\n" + line2 + "\n"


def sync_once():
    url = HOST + "/markov.json?key=" + urllib.parse.quote(KEY)
    with urllib.request.urlopen(url, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8"))
    inst = data.get("instruments", [])
    n = 0
    for it in inst:
        sym = it.get("symbol")
        gate = it.get("gate", "SIDE")
        if not sym:
            continue
        meta = "sym=%s persist=%s n=%s conf=%s asof=%s src=vps" % (
            sym, it.get("persist"), it.get("n", 0), it.get("confidence", "NA"),
            data.get("asof", ""))
        _atomic(os.path.join(OUT, "markov_%s.txt" % sym), _compose(gate, meta))
        n += 1
        if it.get("name") == "Gold":
            _atomic(os.path.join(OUT, "markov_regime.txt"), _compose(gate, meta))
    print("[pc_bridge] wrote %d gate file(s) -> %s" % (n, OUT))
    return n


def main():
    if not HOST or not KEY:
        print("Set WOLF_HOST and WOLF_PASS first.")
        sys.exit(1)
    while True:
        try:
            sync_once()
        except Exception as e:
            print("[pc_bridge] sync failed:", e)
        if POLL <= 0:
            break
        time.sleep(POLL)


if __name__ == "__main__":
    main()
