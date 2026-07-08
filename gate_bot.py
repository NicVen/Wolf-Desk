"""THE WOLF — VIP login + growth bot (runs in-process with the dashboard).

Does three jobs, all managed from Telegram on your phone:

  1) VIP LOGIN  — member taps the desk login -> opens this bot -> /start ->
     membership checked -> one-tap "Open Desk" button (signed 15-min token).

  2) REFERRALS  — every user gets a personal invite link
     (t.me/BOT?start=ref_<their id>). New arrivals via that link are credited
     to the referrer. /invite shows a member their link + count; the admin is
     pinged on each referral so rewards (free VIP days) can be comped.

  3) ADMIN      — from Telegram: /stats (members, referrals, top referrers),
     /broadcast <msg> (announce to the free channels), /myid (find your id).

Run in-process (serve.py starts it) or standalone:  python gate_bot.py
Env: TELEGRAM_BOT_TOKEN, VIP_CHANNELS, PUBLIC_CHANNELS, WOLF_URL,
     ADMIN_IDS (comma-sep Telegram ids), GROWTH_DB, SESSION_SECRET.
"""
import os, time, base64, hashlib, hmac, sqlite3

try:
    import truststore; truststore.inject_into_ssl()
except Exception:
    pass
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
VIP     = [c.strip() for c in os.environ.get("VIP_CHANNELS",
          "-1003988735239,-1004401575622").split(",") if c.strip()]
PUBLIC  = [c.strip() for c in os.environ.get("PUBLIC_CHANNELS",
          "@staalwagsignals,@veldrinforex").split(",") if c.strip()]
WOLF_URL = os.environ.get("WOLF_URL", "https://wolf-desk-production.up.railway.app").rstrip("/")
ADMINS  = set(c.strip() for c in os.environ.get("ADMIN_IDS", "").split(",") if c.strip())
SECRET  = os.environ.get("SESSION_SECRET", "") or ("wolf-" + TOKEN)
DB      = os.environ.get("GROWTH_DB", os.path.join(HERE, "growth.db"))
API     = "https://api.telegram.org/bot%s/" % TOKEN


# ------------------------------------------------------------------ storage
def _db():
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS members(
        uid TEXT PRIMARY KEY, name TEXT, joined REAL, ref_by TEXT)""")
    return c

def register(uid, name, ref_by=None):
    """Insert a first-seen user; returns True if newly referred (for pinging)."""
    c = _db(); newref = False
    row = c.execute("SELECT ref_by FROM members WHERE uid=?", (uid,)).fetchone()
    if row is None:
        # only credit a referrer that isn't the user themself
        rb = ref_by if (ref_by and ref_by != uid) else None
        c.execute("INSERT INTO members(uid,name,joined,ref_by) VALUES(?,?,?,?)",
                  (uid, name, time.time(), rb))
        newref = rb is not None
    c.commit(); c.close()
    return newref

def ref_count(uid):
    c = _db(); n = c.execute("SELECT COUNT(*) FROM members WHERE ref_by=?", (uid,)).fetchone()[0]; c.close()
    return n

def stats():
    c = _db()
    total = c.execute("SELECT COUNT(*) FROM members").fetchone()[0]
    referred = c.execute("SELECT COUNT(*) FROM members WHERE ref_by IS NOT NULL").fetchone()[0]
    top = c.execute("""SELECT ref_by, COUNT(*) n FROM members WHERE ref_by IS NOT NULL
                       GROUP BY ref_by ORDER BY n DESC LIMIT 5""").fetchall()
    names = {}
    for uid, _ in top:
        r = c.execute("SELECT name FROM members WHERE uid=?", (uid,)).fetchone()
        names[uid] = r[0] if r else uid
    c.close()
    return total, referred, [(names[u], n, u) for u, n in top]


# ------------------------------------------------------------------ telegram
def make_login_token(uid, ttl=900):
    exp = str(int(time.time()) + ttl)
    body = "L.%s.%s" % (uid, exp)
    sig = hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()[:32]
    return base64.urlsafe_b64encode(("%s.%s" % (body, sig)).encode()).decode()

def is_vip(uid):
    for cid in VIP:
        try:
            j = requests.get(API + "getChatMember",
                             params={"chat_id": cid, "user_id": uid}, timeout=15).json()
            if j.get("ok") and j["result"].get("status") in ("creator", "administrator", "member"):
                return True
        except Exception as e:
            print("gate_bot: getChatMember error:", e)
    return False

def send(chat_id, text, button=None):
    body = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if button:
        body["reply_markup"] = {"inline_keyboard": [[{"text": button[0], "url": button[1]}]]}
    try:
        requests.post(API + "sendMessage", json=body, timeout=15)
    except Exception as e:
        print("gate_bot: send error:", e)

def ping_admins(text):
    for a in ADMINS:
        send(a, text)


# ------------------------------------------------------------------ handlers
def bot_username():
    try:
        return requests.get(API + "getMe", timeout=15).json()["result"]["username"]
    except Exception:
        return "Staalwag_wolf_Bot"

def handle(msg):
    chat = msg.get("chat", {})
    if chat.get("type") != "private":
        return
    frm = msg.get("from", {})
    uid = str(frm.get("id", ""))
    name = frm.get("first_name", "there")
    text = (msg.get("text") or "").strip()
    if not uid:
        return

    # referral capture from /start ref_<id>
    ref_by = None
    if text.startswith("/start") and "ref_" in text:
        ref_by = text.split("ref_", 1)[1].split()[0]
    if register(uid, name, ref_by) and ref_by:
        rc = ref_count(ref_by)
        ping_admins("🎯 Referral: %s (%s) joined via member %s — that member now has %d referral(s)."
                    % (name, uid, ref_by, rc))

    low = text.lower()

    if low.startswith("/myid"):
        send(chat["id"], "Your Telegram ID: %s" % uid); return

    if low.startswith("/stats") and uid in ADMINS:
        total, referred, top = stats()
        lines = ["📊 WOLF growth", "Members seen: %d" % total,
                 "Referred signups: %d" % referred, "", "Top referrers:"]
        lines += ["  %d. %s — %d" % (i + 1, nm, n) for i, (nm, n, _u) in enumerate(top)] or ["  none yet"]
        send(chat["id"], "\n".join(lines)); return

    if low.startswith("/broadcast") and uid in ADMINS:
        payload = text[len("/broadcast"):].strip()
        if not payload:
            send(chat["id"], "Usage: /broadcast your announcement text"); return
        ok = 0
        for ch in PUBLIC:
            r = requests.post(API + "sendMessage",
                              json={"chat_id": ch, "text": payload,
                                    "disable_web_page_preview": True}, timeout=15).json()
            ok += 1 if r.get("ok") else 0
        send(chat["id"], "Broadcast sent to %d/%d channels." % (ok, len(PUBLIC))); return

    if low.startswith("/tweetdaily") and uid in ADMINS:
        import promo_x
        ok, info = promo_x.post(promo_x.compose_daily())
        send(chat["id"], "X daily digest: %s (%s)" % ("posted" if ok else "FAILED", info)); return

    if low.startswith("/tweet") and uid in ADMINS:
        payload = text[len("/tweet"):].strip()
        if not payload:
            send(chat["id"], "Usage: /tweet your post text (or /tweetdaily for the auto digest)"); return
        import promo_x
        ok, info = promo_x.post(payload)
        send(chat["id"], "X: %s (%s)" % ("posted" if ok else "FAILED", info)); return

    if low.startswith("/invite"):
        link = "https://t.me/%s?start=ref_%s" % (bot_username(), uid)
        send(chat["id"],
             "🔗 Your personal invite link:\n%s\n\nShare it. Everyone who joins through it is "
             "credited to you — you've referred %d so far. Bring people in and earn VIP perks."
             % (link, ref_count(uid)))
        return

    # default: login flow
    if is_vip(uid):
        link = "%s/go?t=%s" % (WOLF_URL, make_login_token(uid))
        send(chat["id"],
             "✅ Verified, %s — WOLF VIP.\nTap to open the Intraday Intel Desk (your link, expires in 15 min).\n\n"
             "Tip: /invite for your referral link · /myid for your id" % name,
             button=("🔓 Open WOLF Desk", link))
    else:
        link = "https://t.me/%s?start=ref_%s" % (bot_username(), uid)
        send(chat["id"],
             "🔒 You're not a WOLF VIP member yet, so I can't open the desk.\n"
             "Free signals: %s\n\nWant in? Ask about VIP. Meanwhile, your invite link (earn perks): %s"
             % (", ".join(PUBLIC), link))


def main():
    if not TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN missing")
    import watchdog
    print("WOLF gate_bot up. VIP:", VIP, "admins:", ADMINS or "(none set)", "db:", DB)
    offset = None
    while True:
        try:
            r = requests.get(API + "getUpdates",
                             params={"timeout": 50, "offset": offset,
                                     "allowed_updates": '["message"]'}, timeout=60)
            for u in r.json().get("result", []):
                offset = u["update_id"] + 1
                if "message" in u:
                    handle(u["message"])
            watchdog.beat("gate_bot")
        except Exception as e:
            print("gate_bot: loop error:", e)
            watchdog.beat("gate_bot", ok=False, err=e)
            time.sleep(5)


if __name__ == "__main__":
    main()
