"""STAALWAG Signal Engine v2 — cloud service (admin/Nico only).

Replaces the retired Markov 18-pair bot on Railway. Runs the validated engine
on a schedule, DMs Nico when a validated edge fires, forward-tracks every signal
in R, and serves its state over HTTP. Emits NOTHING when no validated edge is
firing — silence is correct.

Env (reused from the old service; set on Railway):
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID   Telegram DM target (Nico)
  DATA_DIR                               persistent volume for the forward log
  SCAN_INTERVAL_MIN                      how often to scan (default 720 = 12h)
  PORT                                   provided by Railway
"""
import os
import json
import time
import threading
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

try:
    import truststore; truststore.inject_into_ssl()
except Exception:
    pass
import urllib.request
import urllib.parse

import signal_engine as ENG
import paper_track as PT

DATA = os.getenv("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(DATA, "paper_log.json")
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT = os.getenv("TELEGRAM_CHAT_ID", "")
SCAN_MIN = int(os.getenv("SCAN_INTERVAL_MIN", "720"))
PORT = int(os.getenv("PORT", "3000"))

_state = {"view": None, "track": None, "last_scan": None}


def tg(text: str):
    if not (TOKEN and CHAT):
        return
    try:
        data = urllib.parse.urlencode({
            "chat_id": CHAT, "text": text, "parse_mode": "HTML",
            "disable_web_page_preview": "true"}).encode()
        urllib.request.urlopen(
            "https://api.telegram.org/bot%s/sendMessage" % TOKEN, data=data, timeout=15)
    except Exception as e:
        print("tg error:", e)


def _load():
    try:
        with open(LOG, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save(log):
    try:
        os.makedirs(DATA, exist_ok=True)
        with open(LOG, "w", encoding="utf-8") as f:
            json.dump(log, f, indent=2)
    except Exception as e:
        print("save error:", e)


def cycle(announce=False):
    """One scan: capture new engine signals, resolve open ones, DM Nico, update state."""
    log = _load()
    have = {(s["edge_id"], s["entry"], s["emitted"][:10]) for s in log}
    view = ENG.scan()
    fresh = []
    for s in view["live_signals"]:
        ed = next((e for e in ENG.EDGES if e["id"] == s["edge_id"]), None)
        s = dict(s, ticker=ed["ticker"] if ed else None,
                 emit_ts=int(datetime.now(timezone.utc).timestamp()))
        key = (s["edge_id"], s["entry"], s["emitted"][:10])
        if key not in have and s["ticker"]:
            log.append(s); have.add(key); fresh.append(s)
    for s in log:
        if s.get("result") not in ("WIN", "LOSS"):
            PT.resolve(s)
    _save(log)

    per_edge = {e["id"]: PT._stats([s for s in log if s["edge_id"] == e["id"]])
                for e in ENG.EDGES}
    track = {"overall": PT._stats(log), "per_edge": per_edge,
             "signals_logged": len(log)}
    _state.update(view=view, track=track,
                  last_scan=datetime.now(timezone.utc).isoformat(timespec="minutes"))

    for s in fresh:
        v = next((e["validation"] for e in ENG.EDGES if e["id"] == s["edge_id"]), {})
        tg("⚙ <b>Signal Engine v2 — validated signal</b>\n"
           "<b>%s %s</b> @ %s\nSL %s · TP %s (%s:1) · weight %s\n"
           "edge: %s [%s] · OOS %+.2fR · yrs %s"
           % (s["direction"], s["instrument"], s["entry"], s["sl"], s["tp"],
              s["rr"], s["risk_weight"], s["edge_id"], s["status"],
              v.get("oos_exp_r", 0), v.get("years_positive", "?")))
    if announce:
        n = len(view["live_signals"])
        edges = ", ".join("%s(%s)" % (e["id"], e["status"]) for e in ENG.EDGES)
        tg("⚙ <b>Signal Engine v2 online.</b>\nValidated edges: %s\n"
           "Scanning every %dh. %s\n<i>Silent unless a validated edge fires — that is by design.</i>"
           % (edges, SCAN_MIN // 60,
              "%d signal(s) live now." % n if n else "No signal firing now."))


def loop():
    cycle(announce=True)
    while True:
        time.sleep(SCAN_MIN * 60)
        try:
            cycle()
        except Exception as e:
            print("cycle error:", e)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/signals"):
            return self._send(_state.get("view") or {})
        if self.path.startswith("/track"):
            return self._send(_state.get("track") or {})
        self._send({"service": "STAALWAG Signal Engine v2",
                    "ok": True, "last_scan": _state.get("last_scan"),
                    "principle": "only OOS-validated edges fire; silence otherwise"})


if __name__ == "__main__":
    threading.Thread(target=loop, daemon=True).start()
    print("Signal Engine v2 serving on :%d (scan every %dm)" % (PORT, SCAN_MIN))
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
