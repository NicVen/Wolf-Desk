"""THE WOLF PROJECT — dashboard server (local + Railway-ready).

Local:  python serve.py            (open, no password)
Cloud:  set env WOLF_PASS=secret   -> members enter it once (cookie remembers)
        set env PORT (Railway provides it automatically)

Routes:
  /                 dashboard (or login page if gated)
  /data?class=fx    that class's opportunities json
  /refresh?class=fx run pipeline for that class, return fresh json
  /news?name=Gold   live headlines on demand
"""
import http.server, socketserver, json, os, sys, io, contextlib, threading, time
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)
import run                      # noqa
from scout.news import headlines

PORT        = int(os.environ.get("PORT", "8777"))
WOLF_PASS   = os.environ.get("WOLF_PASS", "")      # empty = open (local)
REFRESH_MIN = int(os.environ.get("REFRESH_MIN", "20"))   # auto-refresh interval; 0 = off
CLASSES     = ("commodities", "fx", "indices", "stocks")


def refresh_loop():
    """Background: rebuild all classes on boot, then every REFRESH_MIN minutes."""
    while True:
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                run.main()
            print("WOLF: auto-refresh complete")
        except Exception as e:
            print("WOLF: auto-refresh error:", e)
        time.sleep(REFRESH_MIN * 60)

LOGIN = """<!doctype html><meta charset=utf-8><title>THE WOLF</title>
<body style="background:#0c1016;color:#cdd6df;font-family:Segoe UI,Arial;display:flex;
align-items:center;justify-content:center;height:100vh;margin:0">
<form method=get action="/" style="background:#141a22;border:1px solid #D4A017;border-radius:12px;padding:28px;width:300px;text-align:center">
<div style="font-size:24px;font-weight:800;letter-spacing:2px"><span style="color:#6E767E">THE </span><span style="color:#D4A017">WOLF</span></div>
<div style="color:#8a929b;font-size:12px;letter-spacing:2px;margin-bottom:16px">MARKET INTEL DESK</div>
<input name=key type=password placeholder="Members password" autofocus
 style="width:100%;padding:10px;border-radius:6px;border:1px solid #222b36;background:#1a212b;color:#fff;margin-bottom:12px">
<button style="width:100%;padding:10px;border:0;border-radius:6px;background:#D4A017;color:#1a1404;font-weight:800;cursor:pointer">ENTER</button>
</form></body>"""


def _read(path, default=b"{}"):
    try:
        with open(path, "rb") as f:
            return f.read()
    except Exception:
        return default


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, body, ctype="application/json", cookie=None):
        if isinstance(body, str): body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def _authed(self, q):
        if not WOLF_PASS:
            return True, None                         # open locally
        if q.get("key", [""])[0] == WOLF_PASS:        # just logged in
            return True, f"wolf={WOLF_PASS}; Path=/; Max-Age=2592000; HttpOnly"
        ck = self.headers.get("Cookie", "")
        return (f"wolf={WOLF_PASS}" in ck), None

    def do_GET(self):
        u = urlparse(self.path); path = u.path; q = parse_qs(u.query)
        ok, cookie = self._authed(q)
        cls = (q.get("class", ["commodities"])[0]).lower()
        if cls not in CLASSES: cls = "commodities"

        if path in ("/", "/index.html"):
            if not ok:
                self._send(200, LOGIN, "text/html; charset=utf-8")
            else:
                self._send(200, _read(os.path.join("dashboard", "index.html")),
                           "text/html; charset=utf-8", cookie)
            return
        if not ok:
            self._send(401, b'{"error":"auth required"}'); return

        if path == "/data":
            self._send(200, _read(os.path.join("data", f"opportunities_{cls}.json")))
        elif path == "/refresh":
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    run.main(only=cls)
                self._send(200, _read(os.path.join("data", f"opportunities_{cls}.json")))
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}))
        elif path == "/news":
            try:
                news, tilt = headlines(q.get("name", [""])[0])
                self._send(200, json.dumps({"news": news, "tilt": tilt}))
            except Exception as e:
                self._send(200, json.dumps({"news": [], "tilt": "no news", "error": str(e)}))
        else:
            self._send(404, b'{"error":"not found"}')


if __name__ == "__main__":
    print(f"WOLF dashboard -> port {PORT}  (gate: {'ON' if WOLF_PASS else 'OFF/local'}, "
          f"auto-refresh: {REFRESH_MIN}m)")
    if REFRESH_MIN > 0:
        threading.Thread(target=refresh_loop, daemon=True).start()
    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True
    with Server(("0.0.0.0", PORT), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nWOLF: stopped")
