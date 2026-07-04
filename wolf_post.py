"""THE WOLF — daily Telegram auto-post (tailored per channel).

  STAALWAG channel  <-  Gold & Commodities desk
  VELDRIN channel   <-  FX desk

Builds fresh data, composes a branded post per desk, posts to each channel.

Env:
  TELEGRAM_BOT_TOKEN   bot token (@BotFather); bot must be ADMIN of each channel
  STAALWAG_CHANNEL     @handle or -100id   (gold/commodities)
  VELDRIN_CHANNEL      @handle or -100id   (FX)
  STAALWAG_VIP         join/CTA link (optional)
  VELDRIN_VIP          join/CTA link (optional)

No token = DRY RUN: prints both posts instead of sending.
Run:  python wolf_post.py
"""
import os, sys, json, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
import run

try:
    import truststore; truststore.inject_into_ssl()
except Exception:
    pass
import requests

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

# desk -> (env channel, env vip, asset-class key, brand header, lead name or None)
DESKS = [
    ("STAALWAG_CHANNEL", "STAALWAG_VIP", "commodities",
     "🥇 <b>STAALWAG — Gold &amp; Commodities Desk</b>", "Gold"),
    ("VELDRIN_CHANNEL",  "VELDRIN_VIP",  "fx",
     "💱 <b>VELDRIN — FX Desk</b>", None),
]


def load(cls):
    with open(os.path.join(C.DATA_DIR, f"opportunities_{cls}.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def line(o):
    v = o.get("analysis", {}).get("verdict", "")
    return f"• <b>{o['name']}</b> — {v} · score <b>{o['score']}</b>\n   <i>{o.get('trend_desc','')}</i>"


def compose(clskey, brand, lead, vip):
    today = datetime.datetime.utcnow().strftime("%d %b %Y")
    ops = load(clskey).get("opportunities", [])
    L = [brand, f"<i>{today} · WOLF intel read</i>", ""]
    if lead:
        led = next((o for o in ops if o["name"] == lead), None)
        if led:
            L.append("<b>Headline:</b>")
            L.append(line(led)); L.append("")
    L.append("<b>Top opportunities today:</b>")
    for o in ops[:3]:
        L.append(line(o))
    L.append("")
    if vip:
        # VIP is live: full signals behind the paywall
        L.append("Full case files + exact levels + trade management → <b>VIP</b>.")
        L.append(f"👉 <a href=\"{vip}\">Join</a>")
    else:
        # No VIP yet: draw with transparency, not a promise we can't back
        L.append("We post our read every day and log every call publicly —")
        L.append("<b>follow to watch the track record build in the open.</b>")
    L.append("")
    L.append("<i>Research/education, not financial advice. Trade your own plan.</i>")
    return "\n".join(L)


def send(channel, msg):
    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      json={"chat_id": channel, "text": msg, "parse_mode": "HTML",
                            "disable_web_page_preview": True}, timeout=20)
    ok = r.status_code == 200 and r.json().get("ok")
    return ok, (r.text[:200] if not ok else "")


def main():
    print("WOLF: refreshing data for daily posts ...")
    run.main()
    for ch_env, vip_env, clskey, brand, lead in DESKS:
        channel = os.environ.get(ch_env, "")
        vip = os.environ.get(vip_env, "")
        msg = compose(clskey, brand, lead, vip)
        if not TOKEN or not channel:
            print(f"\n--- DRY RUN [{ch_env or clskey}] ---\n")
            plain = (msg.replace("<b>", "").replace("</b>", "").replace("<i>", "")
                        .replace("</i>", "").replace("&amp;", "&"))
            print(plain)
            continue
        ok, err = send(channel, msg)
        print(f"WOLF: {'posted' if ok else 'FAILED'} -> {ch_env} {err}")


if __name__ == "__main__":
    main()
