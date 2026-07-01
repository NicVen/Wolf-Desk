"""THE WOLF INTRADAY INTEL DESK — dashboard server (local + Railway-ready).

Access control (the real anti-share gate):
  Primary  = "Log in with Telegram" -> we verify the login is genuine, then
             check the user is a MEMBER of a VIP channel (bot getChatMember).
             Non-members are rejected. Nothing to copy/share: a forwarded link
             is useless to anyone who isn't in the paid channel, and access
             dies automatically when you remove a non-payer from the channel.
  Fallback = WOLF_PASS (admin only) via ?key= — set it for yourself, leave the
             members on Telegram login. Empty WOLF_PASS = open locally.

Env:
  TELEGRAM_BOT_TOKEN   bot token (verifies login signature + membership)
  BOT_USERNAME         bot @username without @ (default Staalwag_wolf_Bot)
  VIP_CHANNELS         comma-separated channel ids members must belong to
  SESSION_SECRET       cookie-signing secret (default derived from bot token)
  WOLF_PASS            optional admin bypass
  PORT / REFRESH_MIN   provided by Railway / defaults

Routes:
  /                 dashboard (or Telegram login if not authed)
  /auth             Telegram login redirect target (verifies + sets session)
  /data?class=fx    that class's opportunities json
  /refresh?class=fx run pipeline for that class, return fresh json
  /news?name=Gold   live headlines on demand
"""
import http.server, socketserver, json, os, sys, io, contextlib, threading, time
import hashlib, hmac, base64
from urllib.parse import urlparse, parse_qs, urlencode

try:
    import truststore; truststore.inject_into_ssl()
except Exception:
    pass
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)
import run                      # noqa
from scout.news import headlines

PORT        = int(os.environ.get("PORT", "8777"))
WOLF_PASS   = os.environ.get("WOLF_PASS", "")           # admin bypass only
REFRESH_MIN = int(os.environ.get("REFRESH_MIN", "20"))
CLASSES     = ("commodities", "fx", "indices", "stocks")

BOT_TOKEN    = os.environ.get("TELEGRAM_BOT_TOKEN", "")
BOT_USERNAME = os.environ.get("BOT_USERNAME", "Staalwag_wolf_Bot")
VIP_CHANNELS = [c.strip() for c in os.environ.get(
    "VIP_CHANNELS", "-1003988735239,-1004401575622").split(",") if c.strip()]
SESSION_SECRET = os.environ.get("SESSION_SECRET", "") or ("wolf-" + BOT_TOKEN)
# Short session = near-instant revoke: a removed member's session dies within
# SESSION_HOURS. Members just re-tap "Log in with Telegram" (one tap). Env override.
SESSION_TTL  = int(float(os.environ.get("SESSION_HOURS", "12")) * 3600)


# ---------------------------------------------------------------- auth helpers
def verify_telegram_login(params: dict) -> str | None:
    """Validate the Telegram Login Widget signature. Returns user id or None."""
    if not BOT_TOKEN or "hash" not in params:
        return None
    recv_hash = params.get("hash", [""])[0]
    pairs = {k: v[0] for k, v in params.items() if k != "hash"}
    data_check = "\n".join("%s=%s" % (k, pairs[k]) for k in sorted(pairs))
    secret = hashlib.sha256(BOT_TOKEN.encode()).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, recv_hash):
        return None
    try:
        if time.time() - int(pairs.get("auth_date", "0")) > 86400:
            return None   # stale login (>1 day)
    except ValueError:
        return None
    return pairs.get("id")


def is_vip_member(uid: str) -> bool:
    """True if the user is in any VIP channel (creator/admin/member)."""
    if not BOT_TOKEN or not uid:
        return False
    for cid in VIP_CHANNELS:
        try:
            r = requests.get("https://api.telegram.org/bot%s/getChatMember" % BOT_TOKEN,
                             params={"chat_id": cid, "user_id": uid}, timeout=15)
            j = r.json()
            if j.get("ok") and j["result"].get("status") in (
                    "creator", "administrator", "member"):
                return True
        except Exception as e:
            print("WOLF: getChatMember error:", e)
    return False


def make_session(uid: str) -> str:
    exp = str(int(time.time()) + SESSION_TTL)
    body = "%s.%s" % (uid, exp)
    sig = hmac.new(SESSION_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()[:32]
    return base64.urlsafe_b64encode(("%s.%s" % (body, sig)).encode()).decode()


def check_session(token: str) -> bool:
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        uid, exp, sig = raw.split(".")
        body = "%s.%s" % (uid, exp)
        good = hmac.new(SESSION_SECRET.encode(), body.encode(),
                        hashlib.sha256).hexdigest()[:32]
        return hmac.compare_digest(good, sig) and int(exp) > time.time()
    except Exception:
        return False


# ---------------------------------------------------------------- FX tools
_CAL = {"ts": 0.0, "data": []}

def get_calendar() -> list:
    """This week's economic calendar (free faireconomy feed), cached 30 min."""
    if time.time() - _CAL["ts"] < 1800 and _CAL["data"]:
        return _CAL["data"]
    try:
        r = requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=25)
        rows = []
        for e in r.json():
            rows.append({
                "date": (e.get("date") or "")[:10],
                "time": (e.get("date") or "")[11:16],
                "currency": e.get("country", ""),
                "impact": e.get("impact", ""),
                "title": e.get("title", ""),
                "forecast": e.get("forecast", ""),
                "previous": e.get("previous", ""),
            })
        _CAL["data"] = rows; _CAL["ts"] = time.time()
    except Exception as e:
        print("WOLF: calendar fetch error:", e)
    return _CAL["data"]


# Central-bank policy rates. EDIT these as banks move — remaining days auto-computed
# from next_meeting. Format: currency -> (rate %, last_change ISO, next_meeting ISO).
RATES = {
    "USD": (4.50, "2026-06-18", "2026-07-29"),
    "EUR": (2.15, "2026-06-05", "2026-07-24"),
    "GBP": (4.25, "2026-06-19", "2026-08-07"),
    "JPY": (0.50, "2026-01-24", "2026-07-31"),
    "AUD": (3.85, "2026-05-20", "2026-08-12"),
    "CAD": (2.75, "2026-06-04", "2026-07-30"),
    "CHF": (0.25, "2026-06-19", "2026-09-25"),
    "NZD": (3.25, "2026-05-28", "2026-07-09"),
}

def get_rates() -> list:
    import datetime as _dt
    today = _dt.date.today()
    out = []
    for ccy, (rate, last, nxt) in RATES.items():
        try:
            nd = _dt.date.fromisoformat(nxt)
            rem = (nd - today).days
        except Exception:
            rem = None
        out.append({"currency": ccy, "rate": rate, "last_change": last,
                    "next_release": nxt, "remaining_days": rem})
    out.sort(key=lambda x: (x["remaining_days"] is None, x["remaining_days"]))
    return out


def refresh_loop():
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
<div style="background:#141a22;border:1px solid #D4A017;border-radius:12px;padding:28px;width:320px;text-align:center">
<div style="font-size:24px;font-weight:800;letter-spacing:2px"><span style="color:#6E767E">THE </span><span style="color:#D4A017">WOLF</span></div>
<div style="color:#8a929b;font-size:12px;letter-spacing:2px;margin-bottom:18px">INTRADAY INTEL DESK</div>
<div style="color:#8a929b;font-size:12px;margin-bottom:16px">VIP members only — verify with Telegram</div>
<div style="display:flex;justify-content:center">
<script async src="https://telegram.org/js/telegram-widget.js?22"
 data-telegram-login="__BOT__" data-size="large" data-auth-url="__AUTHURL__"
 data-request-access="write"></script></div>
</div></body>"""

DENIED = """<!doctype html><meta charset=utf-8><title>THE WOLF</title>
<body style="background:#0c1016;color:#cdd6df;font-family:Segoe UI,Arial;display:flex;
align-items:center;justify-content:center;height:100vh;margin:0;text-align:center">
<div style="background:#141a22;border:1px solid #b3402f;border-radius:12px;padding:28px;width:340px">
<div style="font-size:22px;font-weight:800;color:#D4A017;margin-bottom:8px">ACCESS DENIED</div>
<div style="color:#cdd6df;font-size:13px;margin-bottom:14px">This desk is for VIP members. Your Telegram isn't in a VIP channel.</div>
<a href="/" style="color:#D4A017;font-size:12px">&larr; back</a></div></body>"""


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

    def _redirect(self, location, cookie=None):
        self.send_response(302)
        self.send_header("Location", location)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def _authed(self, q) -> bool:
        # admin bypass
        if WOLF_PASS and q.get("key", [""])[0] == WOLF_PASS:
            return True
        ck = self.headers.get("Cookie", "")
        for part in ck.split(";"):
            part = part.strip()
            if part.startswith("wolf_session="):
                return check_session(part.split("=", 1)[1])
            if WOLF_PASS and part == ("wolf=%s" % WOLF_PASS):
                return True
        return not (WOLF_PASS or BOT_TOKEN)   # fully open only if nothing configured

    def do_GET(self):
        u = urlparse(self.path); path = u.path; q = parse_qs(u.query)
        cls = (q.get("class", ["commodities"])[0]).lower()
        if cls not in CLASSES: cls = "commodities"

        # Telegram login redirect target
        if path == "/auth":
            uid = verify_telegram_login(q)
            if not uid:
                self._send(403, "Login verification failed.", "text/html; charset=utf-8"); return
            if not is_vip_member(uid):
                self._send(200, DENIED, "text/html; charset=utf-8"); return
            cookie = ("wolf_session=%s; Path=/; Max-Age=%d; HttpOnly; SameSite=Lax"
                      % (make_session(uid), SESSION_TTL))
            self._redirect("/", cookie); return

        ok = self._authed(q)

        if path in ("/", "/index.html"):
            if not ok:
                host = self.headers.get("Host", "")
                scheme = "https"   # Railway terminates TLS
                auth_url = "%s://%s/auth" % (scheme, host) if host else "/auth"
                page = LOGIN.replace("__BOT__", BOT_USERNAME).replace("__AUTHURL__", auth_url)
                self._send(200, page, "text/html; charset=utf-8")
            else:
                cookie = None
                if WOLF_PASS and q.get("key", [""])[0] == WOLF_PASS:
                    cookie = "wolf=%s; Path=/; Max-Age=2592000; HttpOnly" % WOLF_PASS
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
        elif path == "/calendar":
            self._send(200, json.dumps({"events": get_calendar()}))
        elif path == "/rates":
            self._send(200, json.dumps({"rates": get_rates()}))
        else:
            self._send(404, b'{"error":"not found"}')


if __name__ == "__main__":
    gate = "Telegram-VIP" if BOT_TOKEN else ("WOLF_PASS" if WOLF_PASS else "OPEN")
    print(f"WOLF dashboard -> port {PORT}  (gate: {gate}, auto-refresh: {REFRESH_MIN}m)")
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
