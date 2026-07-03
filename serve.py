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


def make_login_token(uid: str, ttl: int = 900) -> str:
    """Short-lived (15 min) one-hop token the bot hands out; /go swaps it for a session."""
    exp = str(int(time.time()) + ttl)
    body = "L.%s.%s" % (uid, exp)
    sig = hmac.new(SESSION_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()[:32]
    return base64.urlsafe_b64encode(("%s.%s" % (body, sig)).encode()).decode()


def verify_login_token(token: str):
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        tag, uid, exp, sig = raw.split(".")
        body = "%s.%s.%s" % (tag, uid, exp)
        good = hmac.new(SESSION_SECRET.encode(), body.encode(),
                        hashlib.sha256).hexdigest()[:32]
        if tag == "L" and hmac.compare_digest(good, sig) and int(exp) > time.time():
            return uid
    except Exception:
        pass
    return None


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


# Central-bank policy rates — auto-scraped from global-rates.com, cached 12h.
# Fallback values (from global-rates) used if the scrape fails. Format:
# currency -> (rate %, last_change ISO).
_RATE_FALLBACK = {
    "USD": (3.75, "2025-11-12"), "EUR": (2.40, "2026-06-11"),
    "GBP": (3.75, "2025-12-18"), "JPY": (1.00, "2026-06-16"),
    "AUD": (4.35, "2026-05-06"), "CAD": (2.25, "2025-10-29"),
    "CHF": (0.00, "2025-06-19"), "NZD": (2.25, "2025-11-26"),
}
# global-rates bank adjective -> currency
_BANK_CCY = {"American": "USD", "European": "EUR", "British": "GBP",
             "Japanese": "JPY", "Australian": "AUD", "Canadian": "CAD",
             "Swiss": "CHF", "Zealand": "NZD"}
_RATES = {"ts": 0.0, "data": {}}

def _scrape_rates() -> dict:
    import re
    r = requests.get("https://www.global-rates.com/en/interest-rates/central-banks/",
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=25)
    pat = re.compile(r"([A-Z][a-z]+) Central Bank.*?(\d+\.\d+)\s*%.*?(\d{2})-(\d{2})-(\d{4})", re.S)
    out = {}
    for adj, rate, mm, dd, yyyy in pat.findall(r.text):
        ccy = _BANK_CCY.get(adj)
        if ccy:
            out[ccy] = (float(rate), "%s-%s-%s" % (yyyy, mm, dd))
    return out

def get_rates() -> list:
    import datetime as _dt
    if time.time() - _RATES["ts"] > 43200 or not _RATES["data"]:   # 12h
        try:
            scraped = _scrape_rates()
            _RATES["data"] = {**_RATE_FALLBACK, **scraped}   # scrape wins, fallback fills gaps
            _RATES["ts"] = time.time()
            print("WOLF: rates refreshed (%d live)" % len(scraped))
        except Exception as e:
            print("WOLF: rates scrape failed, using fallback:", e)
            if not _RATES["data"]:
                _RATES["data"] = dict(_RATE_FALLBACK)
    today = _dt.date.today()
    out = []
    for ccy, (rate, last) in _RATES["data"].items():
        try:
            days_ago = (today - _dt.date.fromisoformat(last)).days
        except Exception:
            days_ago = None
        out.append({"currency": ccy, "rate": rate, "last_change": last,
                    "days_ago": days_ago})
    order = ["USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD"]
    out.sort(key=lambda x: order.index(x["currency"]) if x["currency"] in order else 99)
    return out


_FX = {}   # cache: "USDEUR" -> (rate, ts)

def fx_rate(a: str, b: str):
    """1 unit of currency a expressed in currency b (live Yahoo, cached 10 min)."""
    if not a or not b or a == b:
        return 1.0
    key = a + b
    now = time.time()
    if key in _FX and now - _FX[key][1] < 600:
        return _FX[key][0]
    hdr = {"User-Agent": "Mozilla/5.0"}
    url = "https://query1.finance.yahoo.com/v8/finance/chart/{s}?range=1d&interval=60m"
    for sym, inv in ((a + b + "=X", False), (b + a + "=X", True)):
        try:
            r = requests.get(url.format(s=sym), headers=hdr, timeout=15)
            cl = [c for c in r.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"] if c]
            if cl:
                rate = (1.0 / cl[-1]) if inv else cl[-1]
                _FX[key] = (rate, now)
                return rate
        except Exception:
            continue
    return None


TG_GOLD = os.environ.get("PUBLIC_HANDLE_GOLD", "@staalwagsignals")
TG_FX   = os.environ.get("PUBLIC_HANDLE_FX", "@veldrinforex")
TG_LINK = os.environ.get("TG_LINK", "https://t.me/staalwagsignals")
WOLF_IMG = os.environ.get("WOLF_IMG", "https://wolf-desk-production.up.railway.app/wolf.png")

def _xml_escape(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))

def build_rss() -> str:
    """RSS feed of intraday reads. A free RSS->X service (dlvr.it) turns each
    new item into a post on @thewolfdesk — no paid X API needed. GUIDs are
    per-day+name+verdict so nothing double-posts within a day; a fresh day = new
    posts as verdicts stand."""
    import datetime, json as _j
    day = datetime.datetime.utcnow().strftime("%Y%m%d")
    now = datetime.datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")
    items = []
    tags = {"fx": "#forex", "commodities": "#gold #commodities",
            "indices": "#indices", "stocks": "#stocks"}
    for cls in ("fx", "commodities", "indices", "stocks"):
        try:
            d = _j.load(open(os.path.join("data", "opportunities_%s.json" % cls), encoding="utf-8"))
        except Exception:
            continue
        for o in d.get("opportunities", [])[:3]:
            v = o.get("analysis", {}).get("verdict", "")
            if v not in ("BUY", "SELL"):
                continue
            handle = TG_GOLD if cls == "commodities" else TG_FX
            title = "%s — %s (score %s)" % (o["name"], v, o["score"])
            body = ("🐺 THE WOLF intraday read: %s %s, score %s. %s "
                    "Full case file + signals on the desk. Free: %s %s"
                    % (o["name"], v, o["score"], o.get("trend_desc", ""), handle, tags[cls]))
            guid = "%s-%s-%s" % (day, o["name"].replace(" ", ""), v)
            items.append((title, body, guid))
    if not items:
        items = [("THE WOLF — desk online",
                  "🐺 THE WOLF intraday intel desk — gold, FX, indices & stocks. "
                  "Free reads: %s %s" % (TG_GOLD, TG_FX), "%s-online" % day)]
    xi = "".join(
        "<item><title>%s</title><description>%s</description>"
        "<link>%s</link><guid isPermaLink=\"false\">%s</guid>"
        "<enclosure url=\"%s\" type=\"image/png\" length=\"0\"/>"
        "<media:content url=\"%s\" medium=\"image\" type=\"image/png\"/>"
        "<pubDate>%s</pubDate></item>"
        % (_xml_escape(t), _xml_escape(b), TG_LINK, g, WOLF_IMG, WOLF_IMG, now)
        for t, b, g in items[:12])
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"><channel>'
            '<title>THE WOLF — Intraday Intel</title>'
            '<link>%s</link>'
            '<description>Intraday reads on gold, FX, indices &amp; stocks.</description>'
            '<image><url>%s</url><title>THE WOLF — Intraday Intel</title><link>%s</link></image>'
            '%s</channel></rss>' % (TG_LINK, WOLF_IMG, TG_LINK, xi))


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
<meta name=viewport content="width=device-width,initial-scale=1">
<body style="background:#0c1016;color:#cdd6df;font-family:Segoe UI,Arial;display:flex;
align-items:center;justify-content:center;min-height:100vh;margin:0">
<div style="background:#141a22;border:1px solid #D4A017;border-radius:12px;padding:28px;width:320px;text-align:center">
<div style="font-size:24px;font-weight:800;letter-spacing:2px"><span style="color:#6E767E">THE </span><span style="color:#D4A017">WOLF</span></div>
<div style="color:#8a929b;font-size:12px;letter-spacing:2px;margin-bottom:18px">INTRADAY INTEL DESK</div>
<div style="color:#8a929b;font-size:13px;margin-bottom:18px;line-height:1.5">VIP members only.<br>Tap below — the bot checks your membership and lets you in.</div>
<a href="https://t.me/__BOT__?start=login"
 style="display:block;padding:14px;border-radius:8px;background:#D4A017;color:#1a1404;font-weight:800;text-decoration:none;font-size:15px">🔓 Log in with Telegram</a>
<div style="color:#6b727a;font-size:11px;margin-top:14px">Opens @__BOT__ — press START, then tap the link it sends you.</div>
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

        # Bot login: /go?t=<login token> -> swap for a session cookie, enter desk.
        if path == "/go":
            uid = verify_login_token(q.get("t", [""])[0])
            if not uid:
                self._send(200, "<body style='background:#0c1016;color:#cdd6df;font-family:Arial;text-align:center;padding-top:60px'>Login link expired — tap the bot again to get a fresh one.</body>",
                           "text/html; charset=utf-8"); return
            cookie = ("wolf_session=%s; Path=/; Max-Age=%d; HttpOnly; SameSite=Lax"
                      % (make_session(uid), SESSION_TTL))
            self._redirect("/", cookie); return

        # Public FX tools (generic market data) — not gated, so they load even
        # inside Telegram's in-app browser where the session cookie may not ride
        # along on fetch. The VIP intel (/data, /news) stays gated below.
        if path == "/calendar":
            self._send(200, json.dumps({"events": get_calendar()})); return
        if path == "/rates":
            self._send(200, json.dumps({"rates": get_rates()})); return
        if path == "/fx":
            fr = q.get("from", [""])[0].upper(); to = q.get("to", [""])[0].upper()
            self._send(200, json.dumps({"rate": fx_rate(fr, to)})); return
        if path in ("/rss", "/feed", "/rss.xml"):
            self._send(200, build_rss(), "application/rss+xml; charset=utf-8"); return
        if path in ("/wolf.png", "/logo.png"):
            self._send(200, _read("wolf.png", b""), "image/png"); return

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
        else:
            self._send(404, b'{"error":"not found"}')


if __name__ == "__main__":
    gate = "Telegram-VIP" if BOT_TOKEN else ("WOLF_PASS" if WOLF_PASS else "OPEN")
    print(f"WOLF dashboard -> port {PORT}  (gate: {gate}, auto-refresh: {REFRESH_MIN}m)")
    if REFRESH_MIN > 0:
        threading.Thread(target=refresh_loop, daemon=True).start()
    # Run the VIP login bot in-process (no separate worker service needed).
    # Set RUN_BOT=0 to disable on any duplicate instance so only ONE polls.
    if BOT_TOKEN and os.environ.get("RUN_BOT", "1") != "0":
        try:
            import gate_bot
            threading.Thread(target=gate_bot.main, daemon=True).start()
            print("WOLF: login bot started in-process")
        except Exception as e:
            print("WOLF: could not start login bot:", e)
    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True
    with Server(("0.0.0.0", PORT), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nWOLF: stopped")
