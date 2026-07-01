"""THE WOLF — VIP login bot (always-on worker).

Replaces the flaky Telegram Login Widget. Flow that works everywhere
(in-app or any browser):
  member taps "Log in" on the desk  ->  opens this bot  ->  /start
  bot checks VIP-channel membership  ->  sends a one-tap "Open Desk" button
  button -> desk /go?t=<token> -> session cookie -> dashboard.

Non-members get a polite "not a member" reply. The login token is signed
+ short-lived (15 min), so a forwarded button dies fast.

Run as a Railway WORKER service:  python gate_bot.py
Env: TELEGRAM_BOT_TOKEN, VIP_CHANNELS, WOLF_URL, SESSION_SECRET (optional).
"""
import os, time, base64, hashlib, hmac

try:
    import truststore; truststore.inject_into_ssl()
except Exception:
    pass
import requests

TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
VIP     = [c.strip() for c in os.environ.get(
    "VIP_CHANNELS", "-1003988735239,-1004401575622").split(",") if c.strip()]
WOLF_URL = os.environ.get("WOLF_URL", "https://wolf-desk-production.up.railway.app").rstrip("/")
SECRET  = os.environ.get("SESSION_SECRET", "") or ("wolf-" + TOKEN)
API     = "https://api.telegram.org/bot%s/" % TOKEN


def make_login_token(uid: str, ttl: int = 900) -> str:
    exp = str(int(time.time()) + ttl)
    body = "L.%s.%s" % (uid, exp)
    sig = hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()[:32]
    return base64.urlsafe_b64encode(("%s.%s" % (body, sig)).encode()).decode()


def is_vip(uid) -> bool:
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


def handle(msg):
    chat = msg.get("chat", {})
    if chat.get("type") != "private":
        return
    uid = msg.get("from", {}).get("id")
    name = msg.get("from", {}).get("first_name", "there")
    if not uid:
        return
    if is_vip(str(uid)):
        link = "%s/go?t=%s" % (WOLF_URL, make_login_token(str(uid)))
        send(chat["id"],
             "✅ Verified, %s. You're a WOLF VIP member.\nTap below to open the Intraday Intel Desk — "
             "this link is just for you and expires in 15 minutes." % name,
             button=("🔓 Open WOLF Desk", link))
    else:
        send(chat["id"],
             "🔒 You're not in a WOLF VIP channel yet, so I can't open the desk.\n"
             "Once you're a paid VIP member and added to the channel, tap /start again.")


def main():
    if not TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN missing")
    print("WOLF gate_bot up. VIP channels:", VIP, "-> desk", WOLF_URL)
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
        except Exception as e:
            print("gate_bot: loop error:", e)
            time.sleep(5)


if __name__ == "__main__":
    main()
